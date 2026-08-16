"""Права доступа к командам.

По умолчанию команды доступны только владельцу аккаунта и списку sudo. Модуль
может расширить доступ декораторами (``@loader.everyone``, ``@loader.group_admin``…),
а владелец — точечно поменять права любой команды через ``.security``.
"""

from __future__ import annotations

import contextlib
import logging
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

DEFAULT_PERMISSIONS = OWNER | SUDO
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

    def mask_for(self, command: str, func: typing.Callable) -> int:
        """Права команды: сохранённая маска важнее декораторов в коде."""
        return int(self.masks.get(command, get_flags(func)))

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

        if user_id is None:
            return False

        # Свой аккаунт может всё и всегда
        if user_id == self._client.tg_id:
            return True

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
    def chat_rules(self) -> dict[str, list[str]]:
        """``{"chat:-100123": ["ping", "info"]}`` — что разрешено в конкретном чате."""
        return self._db.pointer(DB_OWNER, "rules", {}, item_type=dict)

    async def _check_chat_rules(self, message: Message, command: str, user_id: int) -> bool:
        if not command:
            return False

        rules = self.chat_rules

        for key in (f"user:{user_id}", f"chat:{getattr(message, 'chat_id', 0)}"):
            allowed = rules.get(key)

            if allowed and (command in allowed or "*" in allowed):
                return True

        return False

    def allow(self, target: str, command: str) -> None:
        rules = self.chat_rules
        allowed = list(rules.get(target, []))

        if command not in allowed:
            allowed.append(command)

        rules[target] = allowed

    def disallow(self, target: str, command: str) -> None:
        rules = self.chat_rules
        allowed = [item for item in rules.get(target, []) if item != command]

        if allowed:
            rules[target] = allowed
        else:
            rules.pop(target, None)
