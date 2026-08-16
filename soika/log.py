"""Логирование: цветная консоль, ротация файла и кольцевой буфер для команды ``.logs``.

Всё, что проходит через логгер, прогоняется через :func:`censor` — токены ботов,
api_hash и строки сессий не должны утечь ни в консоль, ни в файл, ни в чат.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import typing
from collections import deque

from . import configuration

_BOT_TOKEN_RE = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")
_HASH_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
_SESSION_RE = re.compile(r"\b1[A-Za-z0-9_\-+=]{200,}\b")

_LEVEL_COLOR = {
    logging.DEBUG: "\033[38;5;245m",
    logging.INFO: "\033[38;5;39m",
    logging.WARNING: "\033[38;5;214m",
    logging.ERROR: "\033[38;5;203m",
    logging.CRITICAL: "\033[1;38;5;196m",
}
_RESET = "\033[0m"
_DIM = "\033[38;5;240m"

_DATE_FORMAT = "%H:%M:%S"
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def censor(text: str) -> str:
    """Замазать секреты в тексте (токены ботов, api_hash, строковые сессии)."""
    text = _BOT_TOKEN_RE.sub("[токен бота скрыт]", text)
    text = _SESSION_RE.sub("[сессия скрыта]", text)
    return _HASH_RE.sub("[hash скрыт]", text)


class _PlainFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(_FORMAT, datefmt=_DATE_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        return censor(super().format(record))


class _ColorFormatter(_PlainFormatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        color = _LEVEL_COLOR.get(record.levelno, "")
        asctime, _, rest = text.partition(" ")
        return f"{_DIM}{asctime}{_RESET} {color}{rest}{_RESET}"


class MemoryHandler(logging.Handler):
    """Кольцевой буфер последних записей.

    Из него ``.logs`` собирает файл, а модуль лог-канала забирает только то,
    что появилось с прошлой отправки — поэтому у каждой записи есть номер.
    """

    def __init__(self, capacity: int = 3000) -> None:
        super().__init__(logging.DEBUG)
        self.entries: deque[tuple[int, int, str]] = deque(maxlen=capacity)
        self._counter = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._counter += 1
            self.entries.append((self._counter, record.levelno, self.format(record)))
        except Exception:  # noqa: BLE001 — падать из-за логгера нельзя ни при каких условиях
            self.handleError(record)

    @property
    def last_id(self) -> int:
        return self._counter

    def dumps(self, level: int = logging.INFO) -> list[str]:
        return [text for _, lvl, text in self.entries if lvl >= level]

    def dumps_since(self, last_id: int, level: int = logging.WARNING) -> tuple[int, list[str]]:
        """Записи новее ``last_id`` и не ниже уровня → (новый номер, строки)."""
        fresh = [(seq, text) for seq, lvl, text in self.entries if seq > last_id and lvl >= level]

        if not fresh:
            return max(last_id, self._counter), []

        return fresh[-1][0], [text for _, text in fresh]

    def clear(self) -> None:
        self.entries.clear()


_memory_handler: MemoryHandler | None = None


def memory_handler() -> MemoryHandler:
    global _memory_handler

    if _memory_handler is None:
        _memory_handler = MemoryHandler()
        _memory_handler.setFormatter(_PlainFormatter())

    return _memory_handler


def setup_logging(level: int = logging.INFO, *, log_to_file: bool = True) -> MemoryHandler:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(_ColorFormatter() if _colors_supported() else _PlainFormatter())
    root.addHandler(console)

    if log_to_file:
        logs_dir = configuration.data_root() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "soika.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(min(level, logging.INFO))
        file_handler.setFormatter(_PlainFormatter())
        root.addHandler(file_handler)

    root.addHandler(memory_handler())

    # Библиотеки шумят на INFO — в отладке разрешаем, в обычном режиме глушим
    noisy_level = logging.INFO if level <= logging.DEBUG else logging.WARNING

    for name in ("telethon", "aiogram", "aiohttp", "asyncio", "git", "PIL"):
        logging.getLogger(name).setLevel(noisy_level)

    sys.excepthook = _excepthook

    return memory_handler()


def _colors_supported() -> bool:
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False

    return sys.platform != "win32" or "WT_SESSION" in __import__("os").environ


def _excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: typing.Any,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    logging.getLogger("soika").critical(
        "Необработанное исключение",
        exc_info=(exc_type, exc_value, exc_tb),
    )


def asyncio_exception_handler(loop: typing.Any, context: dict[str, typing.Any]) -> None:
    """Ставится на event loop, чтобы падения фоновых задач не проходили молча."""
    exception = context.get("exception")
    message = context.get("message", "Ошибка в event loop")

    logging.getLogger("soika").error(
        message,
        exc_info=exception if exception else None,
    )
