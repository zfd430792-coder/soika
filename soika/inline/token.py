"""Автосоздание инлайн-бота через диалог с @BotFather.

Пользователь не должен идти к BotFather руками — Сойка создаёт бота сама:
имя, юзернейм, аватарка, инлайн-режим и обратная связь по инлайн-результатам.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import typing
from pathlib import Path

from telethon.errors import YouBlockedUserError
from telethon.tl.functions.contacts import UnblockRequest

from .. import utils
from ..channels import flood_pause
from ..version import BOT_PREFIX, BRAND_LATIN
from .types import BotCreationError

logger = logging.getLogger(__name__)

BOTFATHER = "@BotFather"
DB_OWNER = "soika.inline"
TOKEN_RE = re.compile(r"\b(\d{8,12}:[A-Za-z0-9_-]{30,})\b")
INLINE_PLACEHOLDER = "user@soika:~$"
STEP_TIMEOUT = 40


async def get_token(
    client: typing.Any,
    db: typing.Any,
    *,
    avatar: Path | None = None,
) -> tuple[str, str]:
    """Вернуть (токен, юзернейм бота), создав бота при необходимости."""
    token = db.get(DB_OWNER, "bot_token")
    username = db.get(DB_OWNER, "bot_username", "")

    if token:
        alive_username = await check_token(token)

        if alive_username:
            return token, alive_username or username

        logger.warning("Сохранённый токен бота не работает — создаю бота заново")

    return await create_bot(client, db, avatar=avatar)


async def check_token(token: str) -> str | None:
    """Проверить токен через Bot API. Возвращает юзернейм или None."""
    from aiogram import Bot

    bot = Bot(token=token)

    try:
        me = await bot.get_me()
        return me.username
    except Exception as e:  # noqa: BLE001 — токен могли отозвать, это ожидаемо
        logger.debug("Токен не прошёл проверку: %s", e)
        return None
    finally:
        with contextlib.suppress(Exception):
            await bot.session.close()


def generate_username() -> str:
    return f"{BOT_PREFIX}_{utils.rand(6).lower()}_bot"


async def create_bot(
    client: typing.Any,
    db: typing.Any,
    *,
    avatar: Path | None = None,
) -> tuple[str, str]:
    """Пройти весь диалог с BotFather и вернуть готовый токен."""
    await _unblock(client)

    display_name = f"{BRAND_LATIN} Userbot of {utils.get_display_name(client.soika_me)}"[:64]
    username = db.get(DB_OWNER, "custom_bot") or generate_username()

    async with client.conversation(BOTFATHER, timeout=STEP_TIMEOUT, exclusive=False) as conv:
        await conv.send_message("/newbot")
        response = await _response(conv)

        if response and "20" in response and "too many" in response.lower():
            raise BotCreationError(
                "У аккаунта уже 20 ботов — удали лишнего через @BotFather и повтори"
            )

        await conv.send_message(display_name)
        await _response(conv)

        token = ""

        for _ in range(5):
            await flood_pause()
            await conv.send_message(username)
            response = await _response(conv)

            if response and (match := TOKEN_RE.search(response)):
                token = match.group(1)
                break

            logger.info("Юзернейм %s занят, пробую другой", username)
            username = generate_username()

        if not token:
            raise BotCreationError("BotFather не отдал токен — попробуй позже")

        await _configure(conv, username, avatar)

    with contextlib.suppress(Exception):
        await client.send_read_acknowledge(BOTFATHER)

    db.set(DB_OWNER, "bot_token", token)
    db.set(DB_OWNER, "bot_username", username)

    logger.info("Создан инлайн-бот @%s", username)
    return token, username


async def _configure(conv: typing.Any, username: str, avatar: Path | None) -> None:
    """Включить инлайн-режим, обратную связь и поставить аватарку."""
    steps: list[tuple[str, ...]] = [
        ("/setinline", f"@{username}", INLINE_PLACEHOLDER),
        ("/setinlinefeedback", f"@{username}", "Enabled"),
        ("/setdescription", f"@{username}", "Инлайн-бот юзербота Сойка"),
    ]

    for step in steps:
        for text in step:
            await flood_pause()
            await conv.send_message(text)
            await _response(conv)

    if avatar and avatar.is_file():
        await flood_pause()
        await conv.send_message("/setuserpic")
        await _response(conv)
        await conv.send_message(f"@{username}")
        await _response(conv)
        await conv.send_file(str(avatar))
        await _response(conv)


async def _response(conv: typing.Any) -> str | None:
    try:
        message = await conv.get_response()
        return message.raw_text or ""
    except asyncio.TimeoutError:
        logger.warning("BotFather не ответил вовремя — продолжаю")
        return None


async def _unblock(client: typing.Any) -> None:
    with contextlib.suppress(Exception):
        await client(UnblockRequest(BOTFATHER))


async def revoke_token(client: typing.Any, db: typing.Any) -> str | None:
    """Перевыпустить токен — спасает, когда бот запущен где-то ещё."""
    username = db.get(DB_OWNER, "bot_username")

    if not username:
        return None

    try:
        async with client.conversation(BOTFATHER, timeout=STEP_TIMEOUT, exclusive=False) as conv:
            await conv.send_message("/revoke")
            await _response(conv)
            await conv.send_message(f"@{username}")
            response = await _response(conv)
    except YouBlockedUserError:
        await _unblock(client)
        return None

    if response and (match := TOKEN_RE.search(response)):
        db.set(DB_OWNER, "bot_token", match.group(1))
        logger.info("Токен бота перевыпущен")
        return match.group(1)

    return None
