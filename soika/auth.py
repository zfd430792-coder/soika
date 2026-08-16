"""Авторизация в Telegram: QR-код, вход по номеру, 2FA, хранение сессий.

Сценарии входа собраны из «кирпичиков», которым скармливают колбэки ввода —
поэтому один и тот же код обслуживает и консоль, и веб-установщик.
"""

from __future__ import annotations

import asyncio
import io
import logging
import sys
import typing
from getpass import getpass
from pathlib import Path
from urllib.parse import urlparse

from telethon.errors import (
    ApiIdInvalidError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import SQLiteSession, StringSession
from telethon.tl.types import User

from . import configuration
from .client import SoikaClient
from .configuration import ApiCredentials
from .version import BRAND, BRAND_EMOJI, __version_str__

logger = logging.getLogger(__name__)

DEVICE_MODEL = "Soika Userbot"
SYSTEM_VERSION = f"Soika {__version_str__}"

Prompt = typing.Callable[[], typing.Awaitable[str]]


class AuthError(Exception):
    """Вход не удался — сообщение предназначено пользователю."""


# --------------------------------------------------------------------------- #
#  Создание клиента
# --------------------------------------------------------------------------- #
def parse_proxy(spec: str | None) -> tuple | None:
    """``socks5://user:pass@host:1080`` → кортеж, который понимает Telethon."""
    if not spec:
        return None

    try:
        import socks
    except ImportError:
        logger.error("Для прокси нужен PySocks: pip install PySocks")
        return None

    parsed = urlparse(spec)
    kinds = {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}

    if parsed.scheme not in kinds or not parsed.hostname or not parsed.port:
        logger.error("Не понимаю прокси %r, жду socks5://user:pass@host:port", spec)
        return None

    proxy = [kinds[parsed.scheme], parsed.hostname, parsed.port, True]

    if parsed.username:
        proxy += [parsed.username, parsed.password or ""]

    return tuple(proxy)


def build_client(
    session: typing.Any,
    credentials: ApiCredentials,
    proxy: tuple | None = None,
) -> SoikaClient:
    return SoikaClient(
        session,
        credentials.api_id,
        credentials.api_hash,
        device_model=DEVICE_MODEL,
        system_version=SYSTEM_VERSION,
        app_version=__version_str__,
        lang_code="ru",
        system_lang_code="ru",
        proxy=proxy,
        connection_retries=None,
        retry_delay=2,
        flood_sleep_threshold=60,
    )


def persist_session(client: SoikaClient) -> Path:
    """Перенести сессию из памяти в файл ``soika-<id>.session``."""
    path = configuration.session_path(client.tg_id)

    if isinstance(client.session, SQLiteSession):
        client.session.save()
        return path

    session = SQLiteSession(str(path))
    session.set_dc(
        client.session.dc_id,
        client.session.server_address,
        client.session.port,
    )
    session.auth_key = client.session.auth_key
    session.save()
    client.session = session

    logger.info("Сессия сохранена: %s", path.name)
    return path


# --------------------------------------------------------------------------- #
#  QR-код
# --------------------------------------------------------------------------- #
def render_qr_ascii(data: str) -> str:
    import qrcode

    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(data)
    qr.make(fit=True)

    buffer = io.StringIO()
    qr.print_ascii(out=buffer, invert=True)
    return buffer.getvalue()


def render_qr_png(data: str) -> bytes:
    import qrcode

    image = qrcode.make(data)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def qr_login(
    client: SoikaClient,
    *,
    on_url: typing.Callable[[str], typing.Awaitable[None]],
    ask_password: Prompt,
    refresh: int = 30,
    attempts: int = 20,
) -> User:
    """Вход по QR: показываем ссылку, ждём скан, при 2FA просим пароль."""
    qr = await client.qr_login()

    for _ in range(attempts):
        await on_url(qr.url)

        try:
            await qr.wait(refresh)
        except asyncio.TimeoutError:
            await qr.recreate()
            continue
        except SessionPasswordNeededError:
            return await _two_factor(client, ask_password)

        return await client.refresh_me()

    raise AuthError("QR-код так и не отсканировали")


# --------------------------------------------------------------------------- #
#  Номер телефона
# --------------------------------------------------------------------------- #
async def phone_login(
    client: SoikaClient,
    *,
    ask_phone: Prompt,
    ask_code: Prompt,
    ask_password: Prompt,
    phone: str | None = None,
) -> User:
    phone = phone or await ask_phone()

    for _ in range(3):
        try:
            sent = await client.send_code_request(phone)
            break
        except PhoneNumberInvalidError:
            logger.error("Такого номера не существует")
            phone = await ask_phone()
        except ApiIdInvalidError:
            raise AuthError("api_id/api_hash не подходят — проверь их на my.telegram.org") from None
    else:
        raise AuthError("Не удалось отправить код подтверждения")

    for _ in range(3):
        code = await ask_code()

        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
            return await client.refresh_me()
        except PhoneCodeInvalidError:
            logger.error("Неверный код, попробуй ещё раз")
        except PhoneCodeExpiredError:
            logger.error("Код протух, высылаю новый")
            sent = await client.send_code_request(phone)
        except SessionPasswordNeededError:
            return await _two_factor(client, ask_password)

    raise AuthError("Три раза подряд неверный код — вход отменён")


async def _two_factor(client: SoikaClient, ask_password: Prompt) -> User:
    for _ in range(3):
        password = await ask_password()

        try:
            await client.sign_in(password=password)
            return await client.refresh_me()
        except PasswordHashInvalidError:
            logger.error("Неверный пароль двухфакторки")

    raise AuthError("Три раза подряд неверный пароль 2FA — вход отменён")


# --------------------------------------------------------------------------- #
#  Консольный сценарий
# --------------------------------------------------------------------------- #
async def _ask(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


async def _ask_secret(prompt: str) -> str:
    return (await asyncio.to_thread(getpass, prompt)).strip()


async def _print_qr(url: str) -> None:
    print(render_qr_ascii(url), flush=True)
    print("  Telegram → Настройки → Устройства → Подключить устройство\n", flush=True)


def console_available() -> bool:
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


async def console_login(
    credentials: ApiCredentials,
    *,
    prefer_qr: bool = True,
    phone: str | None = None,
    proxy: tuple | None = None,
) -> SoikaClient:
    """Полный вход в новый аккаунт через терминал."""
    if not console_available():
        raise AuthError(
            "Нет интерактивного терминала. Запусти без --no-web и зайди в веб-интерфейс"
        )

    client = build_client(StringSession(), credentials, proxy)
    await client.connect()

    if phone:
        prefer_qr = False
    elif prefer_qr:
        print(f"\n{BRAND_EMOJI} {BRAND}: как заходим?")
        print("  1 — QR-код (по умолчанию)")
        print("  2 — номер телефона")
        prefer_qr = (await _ask("> ")) != "2"

    try:
        if prefer_qr:
            await qr_login(
                client,
                on_url=_print_qr,
                ask_password=lambda: _ask_secret("Пароль двухфакторки: "),
            )
        else:
            await phone_login(
                client,
                ask_phone=lambda: _ask("Номер телефона (+7...): "),
                ask_code=lambda: _ask("Код из Telegram: "),
                ask_password=lambda: _ask_secret("Пароль двухфакторки: "),
                phone=phone,
            )
    except AuthError:
        await client.disconnect()
        raise

    persist_session(client)
    logger.info("Вошли как %s", client.soika_me.first_name if client.soika_me else "?")
    return client


# --------------------------------------------------------------------------- #
#  Восстановление сохранённых сессий
# --------------------------------------------------------------------------- #
async def restore_clients(
    credentials: ApiCredentials,
    proxy: tuple | None = None,
) -> list[SoikaClient]:
    """Поднять все аккаунты, чьи сессии лежат в каталоге данных."""
    clients: list[SoikaClient] = []

    for path in configuration.discover_sessions():
        client = build_client(SQLiteSession(str(path)), credentials, proxy)

        try:
            await client.connect()

            if not await client.is_user_authorized():
                logger.warning("Сессия %s протухла — пропускаю (удали файл вручную)", path.name)
                await client.disconnect()
                continue

            await client.refresh_me()
        except ApiIdInvalidError:
            await client.disconnect()
            raise AuthError("api_id/api_hash не подходят к сохранённым сессиям") from None
        except Exception as e:  # noqa: BLE001 — один битый аккаунт не должен ронять остальные
            logger.error("Не удалось поднять %s: %s", path.name, e)
            await client.disconnect()
            continue

        clients.append(client)
        logger.info("Аккаунт подключён: %s (%s)", client.soika_me.first_name, client.tg_id)

    return clients
