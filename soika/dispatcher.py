"""Диспетчер: превращает входящее сообщение в вызов команды или вотчера."""

from __future__ import annotations

import contextlib
import inspect
import logging
import re
import time
import traceback
import typing

from telethon import events
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.custom import Message

from . import utils
from .security import SecurityManager

logger = logging.getLogger(__name__)

DEFAULT_PREFIXES = ["."]
SETTINGS = "soika.settings"

#: Раскладка: «.реды» → «.help»
LAYOUT_RU = "йцукенгшщзхъфывапролджэячсмитьбю.ё"
LAYOUT_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`"
_LAYOUT_TABLE = str.maketrans(LAYOUT_RU + LAYOUT_RU.upper(), LAYOUT_EN + LAYOUT_EN.upper())

GREP_RE = re.compile(r"\s\|\s?grep\s+(?P<pattern>.+)$", re.IGNORECASE)

RATE_LIMIT_WINDOW = 30
RATE_LIMIT_COMMANDS = 20


class CommandDispatcher:
    """Разбор префиксов, прав, фильтров и запуск обработчиков."""

    def __init__(
        self,
        modules: typing.Any,
        client: typing.Any,
        db: typing.Any,
        translator: typing.Any,
    ) -> None:
        self._modules = modules
        self._client = client
        self._db = db
        self._translator = translator

        self.security = SecurityManager(client, db)
        self._ratelimit: dict[int, list[float]] = {}
        self._warned: set[int] = set()

    # ------------------------------------------------------------------ #
    #  Настройки
    # ------------------------------------------------------------------ #
    @property
    def prefixes(self) -> list[str]:
        stored = self._db.get(SETTINGS, "prefixes", DEFAULT_PREFIXES)
        return stored if isinstance(stored, list) and stored else DEFAULT_PREFIXES

    def set_prefixes(self, prefixes: list[str]) -> None:
        self._db.set(SETTINGS, "prefixes", prefixes)

    def register(self, client: typing.Any) -> None:
        """Подписаться на события клиента."""
        client.add_event_handler(self.handle_command, events.NewMessage())
        client.add_event_handler(self.handle_command, events.MessageEdited())
        client.add_event_handler(self.handle_watchers, events.NewMessage())
        client.add_event_handler(self.handle_watchers, events.MessageEdited())
        client.add_event_handler(self.handle_raw, events.Raw())

    # ------------------------------------------------------------------ #
    #  Разбор команды
    # ------------------------------------------------------------------ #
    def is_command(self, message: Message) -> bool:
        text = getattr(message, "raw_text", None) or ""
        return any(text.startswith(prefix) for prefix in self.prefixes)

    def _parse(self, message: Message) -> tuple[str, str, typing.Callable] | None:
        """→ (префикс, имя команды, функция) либо None, если это не наша команда."""
        text = message.raw_text or ""

        prefix = next((p for p in self.prefixes if text.startswith(p)), None)

        if prefix is None:
            return None

        body = text[len(prefix) :]

        # «..команда» — экранирование, чтобы написать точку и не выполнить команду
        if body.startswith(prefix):
            return None

        raw_command = body.split(maxsplit=1)[0] if body.split() else ""

        if not raw_command:
            return None

        # «.команда@username» — адресация конкретному аккаунту при мультиаккаунте
        if "@" in raw_command:
            raw_command, _, target = raw_command.partition("@")
            username = getattr(self._client.soika_me, "username", None) or ""

            if target.lower() not in {username.lower(), str(self._client.tg_id)}:
                return None

        name, func = self._modules.dispatch(raw_command)

        if func is None:
            # Возможно, команду набрали в русской раскладке
            name, func = self._modules.dispatch(raw_command.translate(_LAYOUT_TABLE))

        if func is None:
            return None

        return prefix, name, func

    # ------------------------------------------------------------------ #
    #  Основной обработчик команд
    # ------------------------------------------------------------------ #
    async def handle_command(self, event: typing.Any) -> None:
        message = getattr(event, "message", event)

        if not isinstance(message, Message) or not message.raw_text:
            return

        parsed = self._parse(message)

        if parsed is None:
            return

        _, command, func = parsed

        if not await self.security.check(message, func, command=command):
            if message.out:
                await utils.answer(message, self._translator.gettext("no_permission").format(command))

            return

        if not message.out and not self._check_ratelimit(message.sender_id):
            return

        if self._should_skip(func, message):
            return

        grep = self._extract_grep(message)

        if grep is not None:
            self._apply_grep(message, grep)

        try:
            await func(message)
        except FloodWaitError as e:
            logger.warning("FLOOD_WAIT на команде %s: %s c.", command, e.seconds)
            await self._report(
                message,
                self._translator.gettext("flood_wait").format(utils.format_timedelta(e.seconds)),
            )
        except Exception as e:  # noqa: BLE001 — падение команды не должно ронять юзербот
            await self._command_failed(message, command, e)

    async def _command_failed(self, message: Message, command: str, error: Exception) -> None:
        logger.exception("Команда %s упала", command)

        text = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        ).strip()
        short = f"{type(error).__name__}: {error}"

        inline = getattr(self._client, "inline", None)

        if inline is not None and inline.init_complete:
            with contextlib.suppress(Exception):
                await inline.send_traceback(message, command, short, text)
                return

        await self._report(
            message,
            self._translator.gettext("command_error").format(command, utils.escape_html(short)),
        )

    async def _report(self, message: Message, text: str) -> None:
        if not message.out:
            return

        with contextlib.suppress(RPCError):
            await utils.answer(message, text)

    # ------------------------------------------------------------------ #
    #  Вотчеры
    # ------------------------------------------------------------------ #
    async def handle_watchers(self, event: typing.Any) -> None:
        message = getattr(event, "message", event)

        if not isinstance(message, Message):
            return

        for handler in list(self._modules.watchers):
            if self._should_skip(handler, message, is_watcher=True):
                continue

            utils.spawn(self._run_watcher(handler, message))

    async def _run_watcher(self, handler: typing.Callable, message: Message) -> None:
        try:
            await handler(message)
        except Exception:
            module = type(getattr(handler, "__self__", None)).__name__
            logger.exception("Вотчер модуля %s упал", module)

    async def handle_raw(self, update: typing.Any) -> None:
        for handler in list(self._modules.raw_handlers):
            if not isinstance(update, tuple(handler.updates)):
                continue

            with contextlib.suppress(Exception):
                await handler(update)

    # ------------------------------------------------------------------ #
    #  Фильтры
    # ------------------------------------------------------------------ #
    def _should_skip(
        self,
        func: typing.Callable,
        message: Message,
        *,
        is_watcher: bool = False,
    ) -> bool:
        tags = set(getattr(func, "tags", []))

        def flag(name: str) -> bool:
            return name in tags or bool(getattr(func, name, False))

        checks = {
            "out": lambda: not message.out,
            "in": lambda: message.out,
            "only_messages": lambda: not isinstance(message, Message),
            "only_pm": lambda: not message.is_private,
            "no_pm": lambda: message.is_private,
            "only_chats": lambda: message.is_private,
            "no_chats": lambda: not message.is_private,
            "only_groups": lambda: not message.is_group,
            "no_groups": lambda: message.is_group,
            "only_channels": lambda: not message.is_channel or message.is_group,
            "no_channels": lambda: message.is_channel and not message.is_group,
            "only_media": lambda: not message.media,
            "no_media": lambda: bool(message.media),
            "no_forwards": lambda: bool(message.fwd_from),
            "only_forwards": lambda: not message.fwd_from,
            "no_stickers": lambda: bool(message.sticker),
            "no_docs": lambda: bool(message.document),
            "no_photos": lambda: bool(message.photo),
            "no_videos": lambda: bool(message.video),
            "no_audios": lambda: bool(message.audio),
            "no_inline": lambda: bool(message.via_bot_id),
            "only_inline": lambda: not message.via_bot_id,
            "no_commands": lambda: self.is_command(message),
            "only_commands": lambda: not self.is_command(message),
        }

        for name, predicate in checks.items():
            if flag(name):
                with contextlib.suppress(AttributeError, TypeError):
                    if predicate():
                        return True

        text = message.raw_text or ""

        if (startswith := getattr(func, "startswith", None)) and not text.startswith(startswith):
            return True

        if (endswith := getattr(func, "endswith", None)) and not text.endswith(endswith):
            return True

        if (contains := getattr(func, "contains", None)) and contains not in text:
            return True

        if (pattern := getattr(func, "regex", None)) and not re.search(pattern, text):
            return True

        if (chat_id := getattr(func, "chat_id", None)) and utils.get_chat_id(message) != chat_id:
            return True

        if (from_id := getattr(func, "from_id", None)) and message.sender_id != from_id:
            return True

        if custom := getattr(func, "filter", None):
            with contextlib.suppress(Exception):
                result = custom(message)

                if inspect.isawaitable(result):
                    return False  # асинхронный фильтр проверит сам обработчик

                if not result:
                    return True

        # Вотчеры не должны реагировать на собственные служебные сообщения
        return bool(is_watcher and message.out and getattr(func, "no_self", False))

    # ------------------------------------------------------------------ #
    #  Ограничение частоты
    # ------------------------------------------------------------------ #
    def _check_ratelimit(self, user_id: int | None) -> bool:
        if user_id is None or user_id == self._client.tg_id:
            return True

        now = time.time()
        recent = [ts for ts in self._ratelimit.get(user_id, []) if now - ts < RATE_LIMIT_WINDOW]
        recent.append(now)
        self._ratelimit[user_id] = recent

        if len(recent) <= RATE_LIMIT_COMMANDS:
            self._warned.discard(user_id)
            return True

        if user_id not in self._warned:
            self._warned.add(user_id)
            logger.warning("Пользователь %s спамит командами — притормозил его", user_id)

        return False

    # ------------------------------------------------------------------ #
    #  grep
    # ------------------------------------------------------------------ #
    def _extract_grep(self, message: Message) -> str | None:
        """``.cmd args | grep что-то`` — вырезаем фильтр из текста команды."""
        text = message.raw_text or ""

        if "||grep" in text or "|| grep" in text:
            message.message = text.replace("||grep", "| grep").replace("|| grep", "| grep")
            return None

        match = GREP_RE.search(text)

        if not match:
            return None

        message.message = text[: match.start()]
        return match.group("pattern").strip()

    @staticmethod
    def _apply_grep(message: Message, pattern: str) -> None:
        """Подменяем ответы команды на отфильтрованные строки."""
        negative = pattern.startswith("!")
        needle = pattern[1:] if negative else pattern

        def sieve(text: typing.Any) -> typing.Any:
            if not isinstance(text, str):
                return text

            lines = [
                line
                for line in text.splitlines()
                if (needle not in utils.remove_html(line)) == negative
            ]

            if not lines:
                return f"🔎 <b>По запросу</b> <code>{utils.escape_html(needle)}</code> <b>ничего нет</b>"

            header = f"🔎 <b>grep:</b> <code>{utils.escape_html(needle)}</code>\n\n"
            return header + "\n".join(lines)

        original_edit = message.edit
        original_respond = message.respond

        async def edit(text: typing.Any = None, *args: typing.Any, **kwargs: typing.Any):
            return await original_edit(sieve(text), *args, **kwargs)

        async def respond(text: typing.Any = None, *args: typing.Any, **kwargs: typing.Any):
            return await original_respond(sieve(text), *args, **kwargs)

        message.edit = edit
        message.respond = respond
