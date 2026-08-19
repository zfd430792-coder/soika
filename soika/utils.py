"""Общий инструментарий Сойки.

Имена функций намеренно повторяют утилиты Hikka/FTG — так сторонние модули,
написанные под них, работают без правок.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import io
import json
import os
import random
import re
import shlex
import string
import sys
import time
import typing
from pathlib import Path
from urllib.parse import urlparse

import telethon
from telethon.errors import (
    ChatAdminRequiredError,
    MessageIdInvalidError,
    MessageNotModifiedError,
)
from telethon.hints import EntityLike
from telethon.tl.custom import Message
from telethon.tl.types import Channel, Chat, User

from .configuration import data_root, repo_root
from .log import censor

#: Лимит длины одного сообщения в Telegram
MESSAGE_LIMIT = 4096
CAPTION_LIMIT = 1024

_init_ts = time.perf_counter()

_HTML_TAG_RE = re.compile(r"(<!--.*?-->|<[^>]*>)")


# --------------------------------------------------------------------------- #
#  Аргументы команд
# --------------------------------------------------------------------------- #
def get_args_raw(message: Message | str) -> str:
    """Всё, что идёт после команды, одной строкой."""
    if not (message := getattr(message, "message", message)):
        return ""

    parts = message.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def get_args(message: Message | str) -> list[str]:
    """Аргументы, разбитые по пробелам с уважением к кавычкам."""
    raw = get_args_raw(message)

    if not raw:
        return []

    try:
        split = shlex.split(raw)
    except ValueError:
        return raw.split()

    return [arg for arg in split if arg]


def get_args_split_by(message: Message | str, separator: str) -> list[str]:
    raw = get_args_raw(message)
    return [section.strip() for section in raw.split(separator) if section.strip()]


def get_args_html(message: Message) -> str:
    """Аргументы с сохранением форматирования (HTML)."""
    text = message.text or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def get_kwargs(message: Message | str) -> dict[str, str]:
    """``-key value`` → ``{"key": "value"}`` — удобный разбор флагов."""
    args = get_args(message)
    kwargs: dict[str, str] = {}
    key: str | None = None

    for arg in args:
        if arg.startswith("-") and not arg[1:].isdigit():
            key = arg.lstrip("-")
            kwargs[key] = ""
        elif key is not None:
            kwargs[key] = f"{kwargs[key]} {arg}".strip()

    return kwargs


# --------------------------------------------------------------------------- #
#  Идентификаторы и ссылки
# --------------------------------------------------------------------------- #
def get_chat_id(message: Message) -> int:
    """ID чата без приставки -100."""
    return telethon.utils.get_peer_id(message.peer_id, add_mark=False)


def get_entity_id(entity: EntityLike) -> int:
    return telethon.utils.get_peer_id(entity, add_mark=False)


def get_display_name(entity: typing.Any) -> str:
    return telethon.utils.get_display_name(entity) or "???"


def get_link(user: User | Channel | Chat | int) -> str:
    """Ссылка на профиль/чат — работает и без юзернейма."""
    if isinstance(user, int):
        return f"tg://openmessage?user_id={user}"

    if getattr(user, "username", None):
        return f"https://t.me/{user.username}"

    if isinstance(user, User):
        return f"tg://user?id={user.id}"

    return f"https://t.me/c/{user.id}"


def get_message_link(message: Message, chat: typing.Any = None) -> str:
    if getattr(message, "is_private", False):
        return f"tg://openmessage?user_id={get_chat_id(message)}&message_id={message.id}"

    chat = chat or getattr(message, "chat", None)

    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}/{message.id}"

    return f"https://t.me/c/{get_chat_id(message)}/{message.id}"


def get_topic(message: Message) -> int | None:
    """ID темы форума, если сообщение в теме."""
    reply_to = getattr(message, "reply_to", None)

    if not reply_to:
        return None

    if getattr(reply_to, "forum_topic", False):
        return reply_to.reply_to_top_id or reply_to.reply_to_msg_id

    return None


async def get_target_user(message: Message) -> User | None:
    """Пользователь из реплая, юзернейма или ID в аргументах."""
    client = message.client

    reply = await message.get_reply_message()

    if reply and reply.sender_id:
        with contextlib.suppress(ValueError, TypeError):
            return await client.get_entity(reply.sender_id)

    args = get_args(message)

    if not args:
        return None

    target = args[0]

    with contextlib.suppress(ValueError, TypeError, OverflowError):
        return await client.get_entity(int(target) if target.lstrip("-").isdigit() else target)

    return None


# --------------------------------------------------------------------------- #
#  Текст
# --------------------------------------------------------------------------- #
def escape_html(text: typing.Any) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_quotes(text: typing.Any) -> str:
    return str(text).replace('"', "&quot;")


def remove_html(text: str, *, escape: bool = False) -> str:
    """Выкинуть HTML-теги (или экранировать текст целиком)."""
    return (escape_html if escape else str)(_HTML_TAG_RE.sub("", text))


def smart_split(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Разрезать длинный текст по строкам/словам, не ломая теги грубо."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]

        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line

    if current:
        chunks.append(current)

    return chunks


def chunks(source: typing.Sequence[typing.Any], size: int) -> list[list[typing.Any]]:
    return [list(source[i : i + size]) for i in range(0, len(source), size)]


def array_sum(array: typing.Iterable[typing.Iterable[typing.Any]]) -> list[typing.Any]:
    return [item for sub in array for item in sub]


def rand(size: int = 8) -> str:
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(size))


def check_url(url: typing.Any) -> bool:
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False

    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_serializable(value: typing.Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False

    return True


def unparse_entities(text: str, entities: list[typing.Any] | None) -> str:
    """Собрать HTML обратно из текста и энтити (нужно инлайн-формам)."""
    if not entities:
        return escape_html(text)

    return telethon.extensions.html.unparse(text, entities)


# --------------------------------------------------------------------------- #
#  Ответы в чат
# --------------------------------------------------------------------------- #
async def answer(
    message: Message | list[Message],
    response: str | typing.Any,
    *,
    reply_markup: typing.Any = None,
    **kwargs: typing.Any,
) -> Message | list[Message] | typing.Any:
    """Ответить на команду: своё сообщение редактируем, чужое — отвечаем реплаем.

    Если передан ``reply_markup`` и инлайн-бот жив — уходим в инлайн-форму с кнопками.
    Слишком длинный текст автоматически уезжает файлом.
    """
    if isinstance(message, list):
        message = message[0]

    client = message.client
    kwargs.setdefault("link_preview", False)
    parse_mode = kwargs.pop("parse_mode", "html")

    if reply_markup is not None:
        inline = getattr(client, "inline", None)

        if inline is not None and inline.init_complete:
            return await inline.form(
                message=message,
                text=response,
                reply_markup=reply_markup,
                **kwargs,
            )

    if not isinstance(response, str):
        return await answer_file(message, response, **kwargs)

    if len(response) > MESSAGE_LIMIT:
        return await answer_file(
            message,
            io.BytesIO(remove_html(response).encode()),
            caption="<emoji document_id=5188377234380954537>📄</emoji> <b>Вывод слишком длинный</b>",
            attributes_filename="output.txt",
            **kwargs,
        )

    if message.out:
        try:
            return await message.edit(response, parse_mode=parse_mode, **kwargs)
        except MessageNotModifiedError:
            return message
        except (MessageIdInvalidError, ChatAdminRequiredError):
            # Своё сообщение отредактировать не дают — отправим новое
            pass

    kwargs.pop("reply_to", None)

    return await message.respond(
        response,
        parse_mode=parse_mode,
        reply_to=message.reply_to_msg_id or message.id,
        **kwargs,
    )


async def answer_file(
    message: Message | list[Message],
    file: typing.Any,
    caption: str | None = None,
    **kwargs: typing.Any,
) -> Message:
    """Отправить файл/медиа вместо текстового ответа, подчистив команду."""
    if isinstance(message, list):
        message = message[0]

    filename = kwargs.pop("attributes_filename", None)
    kwargs.pop("link_preview", None)
    kwargs.setdefault("parse_mode", "html")

    if filename and hasattr(file, "read"):
        file.name = filename

    try:
        result = await message.client.send_file(
            message.peer_id,
            file,
            caption=caption,
            reply_to=message.reply_to_msg_id or (None if message.out else message.id),
            **kwargs,
        )
    except Exception:
        if hasattr(file, "seek"):
            file.seek(0)

        raise

    if message.out:
        with contextlib.suppress(Exception):
            await message.delete()

    return result


async def answer_with_banner(
    message: Message | list[Message],
    text: str,
    banner: str | None = None,
    **kwargs: typing.Any,
) -> typing.Any:
    """Ответить текстом, а если у модуля есть баннер — картинкой с подписью.

    Баннер берётся из ``# meta banner:`` в шапке модуля. Если он не ссылка или
    текст не влезает в подпись, спокойно отправляем обычное сообщение.
    """
    if banner and check_url(banner) and len(remove_html(text)) <= CAPTION_LIMIT:
        with contextlib.suppress(Exception):
            return await answer_file(message, banner, caption=text, **kwargs)

    return await answer(message, text, **kwargs)


def get_banner(module: typing.Any) -> str | None:
    """Ссылка на баннер модуля из его метаданных."""
    meta = getattr(module, "__meta__", None) or {}
    return meta.get("banner") or meta.get("pic") or None


async def send_typing(message: Message) -> None:
    with contextlib.suppress(Exception):
        async with message.client.action(message.peer_id, "typing"):
            await asyncio.sleep(0)


# --------------------------------------------------------------------------- #
#  Асинхронщина
# --------------------------------------------------------------------------- #
async def run_sync(func: typing.Callable[..., typing.Any], *args: typing.Any, **kwargs: typing.Any):
    """Выполнить блокирующую функцию, не вешая event loop."""
    return await asyncio.get_running_loop().run_in_executor(
        None,
        functools.partial(func, *args, **kwargs),
    )


def run_async(loop: asyncio.AbstractEventLoop, coro: typing.Coroutine) -> typing.Any:
    """Запустить корутину из синхронного кода (например, из потока)."""
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


_background: set[asyncio.Task] = set()


def spawn(coro: typing.Coroutine) -> asyncio.Task:
    """Фоновая задача с удержанием ссылки — иначе её может съесть сборщик мусора."""
    task = asyncio.ensure_future(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


async def maybe_await(value: typing.Any) -> typing.Any:
    return await value if inspect.isawaitable(value) else value


def find_caller(stack: typing.Any = None) -> typing.Any:
    """Найти в стеке ближайший объект модуля Сойки — нужно загрузчику и логам."""
    caller = next(
        (
            frame_info
            for frame_info in stack or inspect.stack()
            if hasattr(frame_info, "function") and frame_info.function
        ),
        None,
    )
    return caller


# --------------------------------------------------------------------------- #
#  Система
# --------------------------------------------------------------------------- #
def uptime() -> int:
    """Секунд с момента запуска процесса."""
    return round(time.perf_counter() - _init_ts)


def formatted_uptime() -> str:
    return format_timedelta(uptime())


def format_timedelta(seconds: int) -> str:
    days, seconds = divmod(int(seconds), 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    if days:
        return f"{days} д. {hours:02}:{minutes:02}:{seconds:02}"

    return f"{hours:02}:{minutes:02}:{seconds:02}"


def get_named_platform() -> str:
    """Человекочитаемая площадка, на которой крутится Сойка."""
    if os.path.isfile("/.dockerenv"):
        return "🐳 Docker"

    if "com.termux" in os.environ.get("PREFIX", ""):
        return "📱 Termux"

    if os.environ.get("WSL_DISTRO_NAME"):
        return "🐧 WSL"

    if os.name == "nt":
        return "🪟 Windows"

    if sys.platform == "darwin":
        return "🍏 macOS"

    with contextlib.suppress(OSError), open("/proc/1/cgroup", encoding="utf-8") as f:
        if "lxc" in f.read():
            return "📦 LXC"

    return "💎 VDS"


def get_ram_usage() -> float:
    """Потребление памяти процессом (МБ)."""
    try:
        import psutil

        process = psutil.Process(os.getpid())
        mem = process.memory_info().rss / 1024 / 1024

        for child in process.children(recursive=True):
            with contextlib.suppress(Exception):
                mem += child.memory_info().rss / 1024 / 1024

        return round(mem, 1)
    except Exception:  # noqa: BLE001 — статистика не стоит падения команды
        return 0.0


def get_cpu_usage() -> float:
    try:
        import psutil

        return round(psutil.Process(os.getpid()).cpu_percent(interval=0.1), 1)
    except Exception:  # noqa: BLE001 — статистика не стоит падения команды
        return 0.0


def get_build() -> tuple[str, str, str]:
    """(короткий хеш, дата сборки, адрес репозитория) — для .info и .version.

    Хеш нужен ссылке на коммит, а человеку показываем дату: «сборка от 19.08.2026»
    читается, а «сборка a3f9c2e1» — нет.
    """
    try:
        from git import Repo

        repo = Repo(repo_root())
        commit = repo.head.commit

        return (
            commit.hexsha[:8],
            commit.committed_datetime.strftime("%d.%m.%Y"),
            next(repo.remote().urls, ""),
        )
    except Exception:  # noqa: BLE001 — git может отсутствовать целиком
        return "", "", ""


def build_link(url: str, commit: str = "") -> str:
    """Ссылка на исходники: на конкретный коммит, если он известен."""
    url = str(url or "").removesuffix(".git").rstrip("/")

    if not url.startswith("http"):
        return ""

    return f"{url}/commit/{commit}" if commit else url


def get_git_info() -> tuple[str | None, str]:
    """(хеш коммита, ссылка на репозиторий) — для .info и обновлятора."""
    try:
        from git import Repo

        repo = Repo(repo_root())
        return repo.head.commit.hexsha, next(repo.remote().urls, "")
    except Exception:  # noqa: BLE001 — git может отсутствовать целиком
        return None, ""


def get_base_dir() -> str:
    """Совместимость с Hikka: каталог, из которого запущен юзербот."""
    return str(repo_root())


def get_data_dir() -> Path:
    return data_root()


__all__ = [
    "MESSAGE_LIMIT",
    "answer",
    "answer_file",
    "answer_with_banner",
    "array_sum",
    "build_link",
    "censor",
    "check_url",
    "chunks",
    "escape_html",
    "escape_quotes",
    "find_caller",
    "format_timedelta",
    "formatted_uptime",
    "get_args",
    "get_args_html",
    "get_args_raw",
    "get_args_split_by",
    "get_banner",
    "get_base_dir",
    "get_build",
    "get_chat_id",
    "get_cpu_usage",
    "get_data_dir",
    "get_display_name",
    "get_entity_id",
    "get_git_info",
    "get_kwargs",
    "get_link",
    "get_message_link",
    "get_named_platform",
    "get_ram_usage",
    "get_target_user",
    "get_topic",
    "is_serializable",
    "maybe_await",
    "rand",
    "remove_html",
    "run_async",
    "run_sync",
    "smart_split",
    "unparse_entities",
    "uptime",
]
