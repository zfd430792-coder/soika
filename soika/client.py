"""Клиент Telegram с довесками Сойки: кэш сущностей и ссылки на подсистемы."""

from __future__ import annotations

import logging
import time
import typing

from telethon import TelegramClient
from telethon.hints import EntityLike
from telethon.tl.types import User

logger = logging.getLogger(__name__)

#: Сколько держим сущность в кэше — защищает от FLOOD_WAIT на resolve
ENTITY_CACHE_TTL = 300


class SoikaClient(TelegramClient):
    """``TelegramClient`` + всё, что модули ожидают увидеть на клиенте.

    Модули обращаются к ``client.db``, ``client.loader``, ``client.inline`` —
    подсистемы подставляются сюда при старте (см. :mod:`soika.main`).
    """

    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        super().__init__(*args, **kwargs)

        self.soika_me: User | None = None
        self.db: typing.Any = None
        self.loader: typing.Any = None
        self.dispatcher: typing.Any = None
        self.inline: typing.Any = None
        self.web: typing.Any = None
        self.raw_updates_processor: typing.Any = None

        self._entity_cache: dict[str, tuple[float, typing.Any]] = {}

        self.parse_mode = "html"

    # ------------------------------------------------------------------ #
    #  Идентичность
    # ------------------------------------------------------------------ #
    @property
    def tg_id(self) -> int:
        return self.soika_me.id if self.soika_me else 0

    @property
    def hikka_me(self) -> User | None:
        """Совместимость с модулями Hikka."""
        return self.soika_me

    async def refresh_me(self) -> User:
        self.soika_me = await self.get_me()
        return self.soika_me

    # ------------------------------------------------------------------ #
    #  Кэш сущностей
    # ------------------------------------------------------------------ #
    @staticmethod
    def _cache_key(entity: EntityLike) -> str | None:
        if isinstance(entity, (int, str)):
            return str(entity).lower().strip()

        entity_id = getattr(entity, "user_id", None) or getattr(entity, "channel_id", None)
        entity_id = entity_id or getattr(entity, "chat_id", None) or getattr(entity, "id", None)

        return str(entity_id) if entity_id else None

    async def get_entity(  # type: ignore[override]
        self,
        entity: EntityLike,
        exp: int = ENTITY_CACHE_TTL,
        force: bool = False,
    ) -> typing.Any:
        """То же, что у Telethon, но с кэшем — иначе легко словить FLOOD_WAIT."""
        if isinstance(entity, (list, tuple)) or not exp:
            return await super().get_entity(entity)

        key = self._cache_key(entity)

        if key is None:
            return await super().get_entity(entity)

        if not force and (cached := self._entity_cache.get(key)) and cached[0] > time.time():
            return cached[1]

        resolved = await super().get_entity(entity)
        self._entity_cache[key] = (time.time() + exp, resolved)

        if (resolved_key := self._cache_key(resolved)) and resolved_key != key:
            self._entity_cache[resolved_key] = (time.time() + exp, resolved)

        return resolved

    async def force_get_entity(self, entity: EntityLike) -> typing.Any:
        """Сходить в Telegram мимо кэша."""
        return await self.get_entity(entity, force=True)

    def drop_entity_cache(self) -> None:
        self._entity_cache.clear()
