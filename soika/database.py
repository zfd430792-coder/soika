"""База данных Сойки.

Одна база на аккаунт: ``db-<tg_id>.json`` рядом с сессией. Пишется атомарно и с
задержкой (дебаунс), чтобы частые ``set`` не долбили диск. Дополнительно можно
включить Redis, а файлы модулей хранятся в служебном канале-«хранилище».
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import os
import time
import typing
from pathlib import Path

from telethon.tl.types import Message

from . import channels, configuration, utils

logger = logging.getLogger(__name__)

SAVE_DELAY = 0.7
REVISION_INTERVAL = 60
REVISIONS = 3


# --------------------------------------------------------------------------- #
#  Указатели — изменяемые ссылки на кусок базы
# --------------------------------------------------------------------------- #
class _PointerBase:
    _db: Database
    _owner: str
    _key: str

    def _bind(self, db: Database, owner: str, key: str) -> None:
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_key", key)

    def _raw(self) -> typing.Any:  # pragma: no cover — переопределяется
        raise NotImplementedError

    def _sync(self) -> None:
        self._db.set(self._owner, self._key, self._raw())


def _saving(method_name: str) -> typing.Callable:
    """Обёртка: выполнить метод контейнера и сразу записать результат в базу."""

    def wrapper(self: _PointerBase, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        base = list if isinstance(self, list) else dict
        result = getattr(base, method_name)(self, *args, **kwargs)
        self._sync()
        return result

    wrapper.__name__ = method_name
    return wrapper


class PointerList(list, _PointerBase):
    """Список, который сам сохраняется в базу при любом изменении."""

    def _raw(self) -> list:
        return list(self)


class PointerDict(dict, _PointerBase):
    """Словарь, который сам сохраняется в базу при любом изменении."""

    def _raw(self) -> dict:
        return dict(self)


for _method in (
    "append",
    "extend",
    "insert",
    "remove",
    "pop",
    "clear",
    "sort",
    "reverse",
    "__setitem__",
    "__delitem__",
    "__iadd__",
):
    setattr(PointerList, _method, _saving(_method))

for _method in (
    "__setitem__",
    "__delitem__",
    "pop",
    "popitem",
    "update",
    "clear",
    "setdefault",
):
    setattr(PointerDict, _method, _saving(_method))

del _method


# --------------------------------------------------------------------------- #
#  Сама база
# --------------------------------------------------------------------------- #
class Database(dict):
    """``dict`` вида ``{владелец: {ключ: значение}}`` с сохранением на диск."""

    def __init__(self, client: typing.Any) -> None:
        super().__init__()

        self._client = client
        self._path: Path = configuration.data_root() / f"db-{client.tg_id}.json"
        self._redis: typing.Any = None
        self._redis_key = f"soika-db-{client.tg_id}"
        self._save_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._last_revision = 0.0
        self._assets_channel: typing.Any = None

    # ------------------------------------------------------------------ #
    #  Запуск
    # ------------------------------------------------------------------ #
    async def init(self) -> None:
        await self._connect_redis()
        await self.read()
        self._sanitize()

    async def _connect_redis(self) -> None:
        uri = os.environ.get("REDIS_URL") or configuration.get_config_key("redis_uri")

        if not uri:
            return

        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(uri, decode_responses=True)
            await self._redis.ping()
            logger.info("База работает через Redis")
        except ImportError:
            logger.error("Redis указан, но пакет не стоит: pip install redis")
            self._redis = None
        except Exception as e:  # noqa: BLE001
            logger.error("Redis недоступен (%s) — падаю обратно на файл", e)
            self._redis = None

    async def read(self) -> None:
        if self._redis is not None:
            raw = await self._redis.get(self._redis_key)

            if raw:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    self.update(json.loads(raw))
                    return

        for candidate in (self._path, *self._revision_paths()):
            if not candidate.is_file():
                continue

            try:
                with candidate.open(encoding="utf-8") as f:
                    self.update(json.load(f))
            except (json.JSONDecodeError, OSError) as e:
                logger.error("База %s битая (%s) — пробую предыдущую ревизию", candidate.name, e)
                continue

            if candidate != self._path:
                logger.warning("База восстановлена из ревизии %s", candidate.name)

            return

    def _sanitize(self) -> None:
        """Верхний уровень базы — только словари, ключи — только строки."""
        for owner in list(self.keys()):
            if not isinstance(owner, str) or not isinstance(self[owner], dict):
                logger.warning("Выбрасываю мусор из базы: %r", owner)
                del self[owner]

    # ------------------------------------------------------------------ #
    #  Доступ
    # ------------------------------------------------------------------ #
    def get(self, owner: str, key: str | None = None, default: typing.Any = None) -> typing.Any:
        if key is None:
            return super().get(owner, default)

        try:
            return self[owner][key]
        except (KeyError, TypeError):
            return default

    def set(self, owner: str, key: str, value: typing.Any) -> bool:
        if not utils.is_serializable(owner) or not utils.is_serializable(key):
            raise RuntimeError("Имя владельца и ключ должны быть сериализуемыми")

        if not utils.is_serializable(value):
            raise RuntimeError(f"Значение {value!r} нельзя сохранить в JSON")

        super().setdefault(owner, {})[key] = value
        self.save()
        return True

    def remove(self, owner: str, key: str) -> bool:
        try:
            del self[owner][key]
        except (KeyError, TypeError):
            return False

        self.save()
        return True

    def pointer(
        self,
        owner: str,
        key: str,
        default: typing.Any = None,
        item_type: typing.Any = None,
    ) -> typing.Any:
        """Изменяемая ссылка на значение — правишь объект, база сохраняется сама."""
        value = self.get(owner, key, default)

        if item_type is not None and value is None:
            value = item_type()

        if isinstance(value, list):
            pointer: _PointerBase = PointerList(value)
        elif isinstance(value, dict):
            pointer = PointerDict(value)
        else:
            return value

        pointer._bind(self, owner, key)

        if self.get(owner, key) is None:
            self.set(owner, key, pointer._raw())

        return pointer

    # ------------------------------------------------------------------ #
    #  Сохранение
    # ------------------------------------------------------------------ #
    def save(self) -> None:
        """Запланировать запись — реальный сброс на диск случится чуть позже."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._write_sync(copy.deepcopy(dict(self)))
            return

        if self._save_task and not self._save_task.done():
            return

        self._save_task = loop.create_task(self._delayed_save())

    async def _delayed_save(self) -> None:
        await asyncio.sleep(SAVE_DELAY)

        async with self._lock:
            snapshot = copy.deepcopy(dict(self))

            if self._redis is not None:
                try:
                    await self._redis.set(self._redis_key, json.dumps(snapshot, ensure_ascii=False))
                except Exception as e:  # noqa: BLE001
                    logger.error("Не смог записать базу в Redis: %s", e)

            await utils.run_sync(self._write_sync, snapshot)

    def _write_sync(self, snapshot: dict) -> None:
        try:
            self._rotate_revisions()
            tmp = self._path.with_suffix(".json.tmp")

            with tmp.open("w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)

            tmp.replace(self._path)
        except OSError as e:
            logger.error("Не удалось сохранить базу: %s", e)

    def _revision_paths(self) -> list[Path]:
        return [self._path.with_suffix(f".json.rev{i}") for i in range(1, REVISIONS + 1)]

    def _rotate_revisions(self) -> None:
        """Раз в минуту откладываем копию базы — страховка от порчи файла."""
        if not self._path.is_file() or time.time() - self._last_revision < REVISION_INTERVAL:
            return

        revisions = self._revision_paths()

        for older, newer in zip(
            reversed(revisions[1:]),
            reversed(revisions[:-1]),
            strict=False,
        ):
            if newer.is_file():
                newer.replace(older)

        try:
            revisions[0].write_bytes(self._path.read_bytes())
            self._last_revision = time.time()
        except OSError as e:
            logger.error("Не получилось создать ревизию базы: %s", e)

    def keep_revision(self) -> None:
        """Немедленно отложить копию текущего файла — перед опасной операцией.

        Обычные ревизии делаются не чаще раза в минуту; перед восстановлением
        базы ждать нельзя: перезаписываем — значит, старое надо сохранить сейчас.
        """
        self._last_revision = 0.0
        self._rotate_revisions()

    async def flush(self) -> None:
        """Дописать всё немедленно — вызывается перед перезапуском."""
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()

        async with self._lock:
            snapshot = copy.deepcopy(dict(self))

            if self._redis is not None:
                with contextlib.suppress(Exception):
                    await self._redis.set(self._redis_key, json.dumps(snapshot, ensure_ascii=False))

            await utils.run_sync(self._write_sync, snapshot)

    # ------------------------------------------------------------------ #
    #  Хранилище файлов
    # ------------------------------------------------------------------ #
    async def assets_channel(self) -> typing.Any:
        """Приватный канал, куда складываются файлы модулей."""
        if self._assets_channel is None:
            self._assets_channel = await channels.ensure_channel(self._client, self, "assets")

        return self._assets_channel

    async def store_asset(self, message: Message) -> int | None:
        channel = await self.assets_channel()

        if channel is None:
            return None

        copied = await self._client.send_message(channel, message)
        return copied.id

    async def fetch_asset(self, asset_id: int) -> Message | None:
        channel = await self.assets_channel()

        if channel is None:
            return None

        messages = await self._client.get_messages(channel, ids=[asset_id])
        return messages[0] if messages else None
