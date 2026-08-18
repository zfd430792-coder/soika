"""Служебные каналы Сойки: логи, бэкапы и хранилище файлов.

Каналы создаются автоматически при первом запуске. Перед созданием Сойка
проверяет, нет ли уже канала с таким названием среди диалогов — иначе после
восстановления базы из бэкапа появлялись бы дубли.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import random
import typing

from telethon.errors import ChannelsTooMuchError
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.channels import CreateChannelRequest, EditPhotoRequest
from telethon.tl.functions.folders import EditPeerFoldersRequest
from telethon.tl.types import (
    InputChatUploadedPhoto,
    InputFolderPeer,
    InputNotifyPeer,
    InputPeerNotifySettings,
)

logger = logging.getLogger(__name__)

DB_OWNER = "soika.channels"
MUTE_FOREVER = 2**31 - 1

#: Аватарка для служебных каналов — то же перо, что у бота
AVATAR_URL = "https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/bot_pfp.png"

#: Ключ в базе → (название канала, описание, спрятать ли с глаз)
CHANNELS = {
    "assets": ("soika-assets", "🗃 Здесь Сойка хранит файлы модулей", True),
    "logs": ("soika-logs", "📜 Сюда падают ошибки и предупреждения Сойки", True),
    "backups": ("soika-backups", "🗄 Резервные копии базы Сойки", False),
}


async def flood_pause() -> None:
    """Пауза перед «тяжёлым» запросом.

    При первом запуске Сойка подряд создаёт бота через BotFather и пару
    каналов — без задержек это верный способ поймать FLOOD_WAIT.
    """
    await asyncio.sleep(random.uniform(1.0, 2.5))


async def ensure_channel(
    client: typing.Any,
    db: typing.Any,
    key: str,
    *,
    archive: bool | None = None,
    mute: bool | None = None,
) -> typing.Any:
    """Найти служебный канал по ключу или создать его."""
    title, about, hidden = CHANNELS[key]
    archive = hidden if archive is None else archive
    mute = hidden if mute is None else mute

    if stored := db.get(DB_OWNER, key):
        try:
            return await client.get_entity(int(stored))
        except Exception:  # noqa: BLE001 — канал могли удалить, ищем дальше
            logger.warning("Канал %s не открывается по сохранённому id", title)

    # Канал мог остаться от прошлой установки, а база — потеряться
    if existing := await find_by_title(client, title):
        db.set(DB_OWNER, key, existing.id)
        logger.info("Нашёл существующий канал %s, использую его", title)
        return existing

    await flood_pause()

    try:
        result = await client(CreateChannelRequest(title=title, about=about, megagroup=False))
    except ChannelsTooMuchError:
        logger.error("Слишком много каналов в аккаунте — %s не создать", title)
        return None
    except Exception:
        logger.exception("Не удалось создать канал %s", title)
        return None

    channel = result.chats[0]
    db.set(DB_OWNER, key, channel.id)

    await set_avatar(client, channel, AVATAR_URL)

    if archive:
        await _archive(client, channel)

    if mute:
        await _mute(client, channel)

    logger.info("Создан служебный канал %s", title)
    return channel


async def find_by_title(client: typing.Any, title: str) -> typing.Any:
    """Поиск канала среди диалогов по названию — так делает и Hikka."""
    with contextlib.suppress(Exception):
        async for dialog in client.iter_dialogs():
            if dialog.title == title:
                return dialog.entity

    return None


async def channel_link(client: typing.Any, channel: typing.Any) -> str:
    """Ссылка на канал — её показываем пользователю."""
    if getattr(channel, "username", None):
        return f"https://t.me/{channel.username}"

    return f"https://t.me/c/{channel.id}"


async def set_avatar(client: typing.Any, channel: typing.Any, url: str) -> None:
    """Поставить каналу аватарку, чтобы он узнавался в списке чатов."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session, session.get(url) as response:
            response.raise_for_status()
            payload = await response.read()

        uploaded = await client.upload_file(io.BytesIO(payload), file_name="avatar.png")
        await flood_pause()
        await client(
            EditPhotoRequest(channel=channel, photo=InputChatUploadedPhoto(uploaded))
        )
    except Exception:
        logger.debug("Аватарку каналу поставить не удалось", exc_info=True)


async def show_in_list(client: typing.Any, channel: typing.Any) -> None:
    """Вернуть канал из архива и включить уведомления.

    Нужно для канала бэкапов: копии базы должны быть на виду, иначе легко
    решить, что бэкапов вообще нет.
    """
    with contextlib.suppress(Exception):
        await client(
            EditPeerFoldersRequest(
                [InputFolderPeer(await client.get_input_entity(channel), folder_id=0)]
            )
        )

    with contextlib.suppress(Exception):
        await client(
            UpdateNotifySettingsRequest(
                peer=InputNotifyPeer(await client.get_input_entity(channel)),
                settings=InputPeerNotifySettings(show_previews=True, silent=False, mute_until=0),
            )
        )


async def _archive(client: typing.Any, channel: typing.Any) -> None:
    with contextlib.suppress(Exception):
        await client(
            EditPeerFoldersRequest(
                [InputFolderPeer(await client.get_input_entity(channel), folder_id=1)]
            )
        )


async def _mute(client: typing.Any, channel: typing.Any) -> None:
    with contextlib.suppress(Exception):
        await client(
            UpdateNotifySettingsRequest(
                peer=InputNotifyPeer(await client.get_input_entity(channel)),
                settings=InputPeerNotifySettings(
                    show_previews=False,
                    silent=True,
                    mute_until=MUTE_FOREVER,
                ),
            )
        )
