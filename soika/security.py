"""Права доступа к командам.

По умолчанию команды доступны только владельцу аккаунта и списку sudo. Модуль
может расширить доступ декораторами (``@loader.everyone``, ``@loader.group_admin``…),
а владелец — точечно поменять права любой команды через ``.security``.
"""

from __future__ import annotations

import contextlib
import logging
import time
import typing

from telethon.tl.types import Channel, Chat, Message, User

logger = logging.getLogger(__name__)

OWNER = 1 << 0
SUDO = 1 << 1
SUPPORT = 1 << 2
GROUP_OWNER = 1 << 3
GROUP_ADMIN = 1 << 4
GROUP_MEMBER = 1 << 5
PM = 1 << 6
EVERYONE = 1 << 7

#: По умолчанию команду выполняет только владелец и те, кого он добавил в owner.
#: Так же устроена Hikka: sudo и support там объявлены устаревшими, потому что
#: «неполный доступ» через них всё равно позволял ставить модули, то есть
#: выполнять любой код от имени аккаунта
DEFAULT_PERMISSIONS = OWNER
BITS = {
    "owner": OWNER,
    "sudo": SUDO,
    "support": SUPPORT,
    "group_owner": GROUP_OWNER,
    "group_admin": GROUP_ADMIN,
    "group_member": GROUP_MEMBER,
    "pm": PM,
    "everyone": EVERYONE,
}
TITLES = {
    OWNER: "владелец",
    SUDO: "sudo",
    SUPPORT: "support",
    GROUP_OWNER: "владелец чата",
    GROUP_ADMIN: "админ чата",
    GROUP_MEMBER: "участник чата",
    PM: "любой в личке",
    EVERYONE: "все подряд",
}

DB_OWNER = "soika.security"

#: Потолок прав: выше него не поднимется ни одна команда, что бы ни просил модуль
ALL_PERMISSIONS = OWNER | SUDO | SUPPORT | GROUP_OWNER | GROUP_ADMIN | GROUP_MEMBER | PM | EVERYONE


# --------------------------------------------------------------------------- #
#  Декораторы прав
# --------------------------------------------------------------------------- #
def _grant(bit: int) -> typing.Callable:
    def decorator(func: typing.Callable) -> typing.Callable:
        func.security = getattr(func, "security", 0) | bit
        return func

    return decorator


owner = _grant(OWNER)
sudo = _grant(SUDO)
support = _grant(SUPPORT)
group_owner = _grant(GROUP_OWNER)
group_admin = _grant(GROUP_ADMIN)
group_member = _grant(GROUP_MEMBER)
pm = _grant(PM)
everyone = _grant(EVERYONE)
unrestricted = everyone


def inline_everyone(func: typing.Callable) -> typing.Callable:
    """Инлайн-обработчик доступен всем, а не только владельцу."""
    func.inline_everyone = True
    return func


def get_flags(func: typing.Callable) -> int:
    return getattr(func, "security", 0) or DEFAULT_PERMISSIONS


def describe(mask: int) -> str:
    return ", ".join(title for bit, title in TITLES.items() if mask & bit) or "никто"


# --------------------------------------------------------------------------- #
#  Проверка
# --------------------------------------------------------------------------- #
class SecurityManager:
    """Решает, можно ли конкретному человеку выполнить конкретную команду."""

    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self._client = client
        self._db = db

    # -- списки доверенных ------------------------------------------------ #
    @property
    def owner(self) -> list[int]:
        return self._db.pointer(DB_OWNER, "owner", [], item_type=list)

    @property
    def sudo(self) -> list[int]:
        return self._db.pointer(DB_OWNER, "sudo", [], item_type=list)

    @property
    def support(self) -> list[int]:
        return self._db.pointer(DB_OWNER, "support", [], item_type=list)

    @property
    def masks(self) -> dict[str, int]:
        return self._db.pointer(DB_OWNER, "masks", {}, item_type=dict)

    @property
    def bounding_mask(self) -> int:
        """Глобальный потолок: что бы ни просил модуль, выше этого не дадим."""
        return int(self._db.get(DB_OWNER, "bounding_mask", ALL_PERMISSIONS))

    def set_bounding_mask(self, mask: int) -> None:
        self._db.set(DB_OWNER, "bounding_mask", int(mask))

    def mask_for(self, command: str, func: typing.Callable) -> int:
        """Права команды: сохранённая маска важнее декораторов, потолок важнее всех."""
        return int(self.masks.get(command, get_flags(func))) & self.bounding_mask

    def set_mask(self, command: str, mask: int) -> None:
        self.masks[command] = int(mask)

    def reset_mask(self, command: str) -> None:
        self.masks.pop(command, None)

    # -- собственно проверка ---------------------------------------------- #
    async def check(
        self,
        message: Message | None,
        func: typing.Callable,
        *,
        command: str = "",
        user_id: int | None = None,
    ) -> bool:
        if user_id is None:
            user_id = getattr(message, "sender_id", None)

        edited_by_other = False

        # Пост в канале Telegram подписывает самим каналом, а не автором: sender_id
        # там чужой. Если пост правили, настоящего автора правки видно только в
        # журнале админов — иначе сосед-админ выполнил бы команду от твоего имени
        if self._is_channel_post(message) and getattr(message, "edit_date", None):
            editor = await self._channel_editor(message)

            if editor is not None:
                user_id = editor
                edited_by_other = editor != self._client.tg_id

        # Свой аккаунт может всё и всегда
        if user_id == self._client.tg_id:
            return True

        # Своё сообщение — своя команда. Так работают команды в собственных
        # каналах (например, в soika-backups) и от имени группы
        if not edited_by_other and getattr(message, "out", False):
            return True

        if user_id is None:
            return False

        mask = self.mask_for(command, func)

        if mask & EVERYONE:
            return True

        if mask & OWNER and user_id in self.owner:
            return True

        if mask & SUDO and user_id in self.sudo:
            return True

        if mask & SUPPORT and user_id in self.support:
            return True

        if message is None:
            return False

        if mask & PM and getattr(message, "is_private", False):
            return True

        if await self._check_chat_rules(message, command, user_id):
            return True

        if not mask & (GROUP_OWNER | GROUP_ADMIN | GROUP_MEMBER):
            return False

        return await self._check_group(message, mask, user_id)

    @staticmethod
    def _is_channel_post(message: Message | None) -> bool:
        """Пост в канале (не в супергруппе) — у него нет автора-человека."""
        return bool(
            message is not None
            and getattr(message, "is_channel", False)
            and not getattr(message, "is_group", False)
        )

    async def _channel_editor(self, message: Message) -> int | None:
        """Кто на самом деле поправил пост в канале — по журналу админов."""
        with contextlib.suppress(Exception):
            async for event in self._client.iter_admin_log(
                message.chat_id,
                limit=10,
                edit=True,
            ):
                if event.action.prev_message.id == message.id:
                    return event.user_id

        return None

    async def _check_group(self, message: Message, mask: int, user_id: int) -> bool:
        chat = await self._get_chat(message)

        if chat is None or isinstance(chat, User):
            return False

        if mask & GROUP_MEMBER:
            return True

        with contextlib.suppress(Exception):
            participant = await self._client.get_permissions(chat, user_id)

            if mask & GROUP_OWNER and participant.is_creator:
                return True

            if mask & GROUP_ADMIN and participant.is_admin:
                return True

        return False

    async def _get_chat(self, message: Message) -> Chat | Channel | User | None:
        with contextlib.suppress(Exception):
            return await message.get_chat()

        return None

    # -- точечные разрешения ---------------------------------------------- #
    @property
    def chat_rules(self) -> dict[str, dict[str, float]]:
        """``{"user:123": {"ping": 0}}`` — кому что разрешено и до какого времени.

        ``0`` — бессрочно, иначе метка времени, после которой правило протухает.
        """
        rules = self._db.pointer(DB_OWNER, "rules", {}, item_type=dict)

        # Старый формат — список команд без срока
        for key, value in list(rules.items()):
            if isinstance(value, list):
                rules[key] = dict.fromkeys(value, 0)

        return rules

    def rules_for(self, target: str) -> dict[str, float]:
        """Живые правила цели: протухшие выбрасываем на месте."""
        rules = self.chat_rules
        allowed = rules.get(target) or {}
        now = time.time()
        fresh = {command: until for command, until in allowed.items() if not until or until > now}

        if fresh != allowed:
            if fresh:
                rules[target] = fresh
            else:
                rules.pop(target, None)

        return fresh

    async def _check_chat_rules(self, message: Message, command: str, user_id: int) -> bool:
        if not command:
            return False

        for key in (f"user:{user_id}", f"chat:{getattr(message, 'chat_id', 0)}"):
            allowed = self.rules_for(key)

            if command in allowed or "*" in allowed:
                return True

        return False

    def allow(self, target: str, command: str, seconds: float = 0) -> None:
        """Разрешить команду. ``seconds`` — на сколько; 0 — навсегда."""
        rules = self.chat_rules
        allowed = dict(self.rules_for(target))
        allowed[command] = time.time() + seconds if seconds else 0
        rules[target] = allowed

    def disallow(self, target: str, command: str) -> None:
        rules = self.chat_rules
        allowed = dict(self.rules_for(target))
        allowed.pop(command, None)

        if allowed:
            rules[target] = allowed
        else:
            rules.pop(target, None)
