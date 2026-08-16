"""Служебные каналы Сойки: логи, бэкапы и хранилище файлов.

Каналы создаются автоматически, сразу уезжают в архив и глушатся, чтобы не
мозолили глаза в списке чатов. Их id хранится в базе — если канал удалили,
он будет создан заново.
"""

from __future__ import annotations

import contextlib
import logging
import typing

from telethon.errors import ChannelsTooMuchError
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.folders import EditPeerFoldersRequest
from telethon.tl.types import InputFolderPeer, InputNotifyPeer, InputPeerNotifySettings

logger = logging.getLogger(__name__)

DB_OWNER = "soika.channels"
MUTE_FOREVER = 2**31 - 1

#: Ключ в базе → (название канала, описание)
CHANNELS = {
    "assets": ("soika-assets", "Хранилище файлов Сойки. Не удаляй этот канал."),
    "logs": ("soika-logs", "Логи Сойки. Сюда падают ошибки и предупреждения."),
    "backups": ("soika-backups", "Резервные копии базы Сойки."),
}


async def ensure_channel(
    client: typing.Any,
    db: typing.Any,
    key: str,
    *,
    archive: bool = True,
    mute: bool = True,
) -> typing.Any:
    """Найти служебный канал по ключу или создать его."""
    title, about = CHANNELS[key]

    if stored := db.get(DB_OWNER, key):
        try:
            return await client.get_entity(int(stored))
        except Exception:  # noqa: BLE001 — канал могли удалить, создадим новый
            logger.warning("Канал %s пропал из аккаунта, создаю заново", title)

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

    if archive:
        await _archive(client, channel)

    if mute:
        await _mute(client, channel)

    logger.info("Создан служебный канал %s", title)
    return channel


async def channel_link(client: typing.Any, channel: typing.Any) -> str:
    """Ссылка на канал — её показываем пользователю."""
    if getattr(channel, "username", None):
        return f"https://t.me/{channel.username}"

    return f"https://t.me/c/{channel.id}"


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
