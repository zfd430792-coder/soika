"""Конфигурация установки: каталог данных, ``config.json``, api_id/api_hash.

Приоритет источников: переменные окружения → ``config.json`` → интерактивный ввод
(консоль или веб-установщик).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import socket
import typing
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_NAME = "config.json"
SESSION_TEMPLATE = "soika-{}.session"
SESSION_GLOB = "soika-*.session"

_API_HASH_RE = re.compile(r"^[a-fA-F0-9]{32}$")

_ROOT = Path(__file__).resolve().parent.parent
_data_root: Path = _ROOT


def set_data_root(path: str | os.PathLike | None) -> Path:
    """Задать каталог, где лежат сессии, база и конфиг (``--data-root``)."""
    global _data_root

    if path:
        _data_root = Path(path).expanduser().resolve()
        _data_root.mkdir(parents=True, exist_ok=True)

    return _data_root


def data_root() -> Path:
    return _data_root


def repo_root() -> Path:
    """Каталог с исходниками — нужен обновлятору и загрузке ассетов."""
    return _ROOT


def config_path() -> Path:
    return _data_root / CONFIG_NAME


def session_path(tg_id: int | str) -> Path:
    return _data_root / SESSION_TEMPLATE.format(tg_id)


def discover_sessions() -> list[Path]:
    """Все сохранённые сессии — по одной на аккаунт."""
    return sorted(_data_root.glob(SESSION_GLOB))


def read_config() -> dict[str, typing.Any]:
    path = config_path()

    if not path.is_file():
        return {}

    try:
        with path.open(encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Не читается %s (%s) — начинаю с пустого конфига", path, e)
        return {}

    return config if isinstance(config, dict) else {}


def write_config(config: dict[str, typing.Any]) -> None:
    path = config_path()
    tmp = path.with_suffix(".json.tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    tmp.replace(path)


def get_config_key(key: str, default: typing.Any = None) -> typing.Any:
    return read_config().get(key, default)


def save_config_key(key: str, value: typing.Any) -> typing.Any:
    config = read_config()
    config[key] = value
    write_config(config)
    return value


def _env(key: str) -> str | None:
    """``SOIKA_API_ID`` или ``api_id`` — поддерживаем оба написания."""
    return os.environ.get(f"SOIKA_{key.upper()}") or os.environ.get(key)


@dataclass(frozen=True, slots=True)
class ApiCredentials:
    api_id: int
    api_hash: str


class InvalidCredentials(ValueError):
    """api_id/api_hash не прошли проверку формата."""


def validate_credentials(api_id: typing.Any, api_hash: typing.Any) -> ApiCredentials:
    try:
        api_id = int(str(api_id).strip())
    except (TypeError, ValueError):
        raise InvalidCredentials("api_id должен быть числом") from None

    api_hash = str(api_hash).strip()

    if api_id <= 0:
        raise InvalidCredentials("api_id должен быть положительным числом")

    if not _API_HASH_RE.match(api_hash):
        raise InvalidCredentials("api_hash — это 32 символа из цифр и букв a-f")

    return ApiCredentials(api_id, api_hash)


def stored_credentials() -> ApiCredentials | None:
    """Достать api_id/api_hash из окружения или конфига."""
    env_id, env_hash = _env("api_id"), _env("api_hash")

    if env_id and env_hash:
        try:
            return validate_credentials(env_id, env_hash)
        except InvalidCredentials as e:
            logger.error("Кривые api_id/api_hash в переменных окружения: %s", e)

    config = read_config()

    if config.get("api_id") and config.get("api_hash"):
        try:
            return validate_credentials(config["api_id"], config["api_hash"])
        except InvalidCredentials as e:
            logger.error("Кривые api_id/api_hash в config.json: %s", e)

    return None


def store_credentials(api_id: int, api_hash: str) -> ApiCredentials:
    credentials = validate_credentials(api_id, api_hash)
    config = read_config()
    config["api_id"] = credentials.api_id
    config["api_hash"] = credentials.api_hash
    write_config(config)
    return credentials


def gen_port(preferred: int | None = None) -> int:
    """Свободный порт для веб-интерфейса: сначала желаемый, потом 8080, потом случайный."""
    for port in filter(None, (preferred, 8080)):
        if port_is_free(port):
            return port

    while True:
        port = random.randint(1024, 65535)

        if port_is_free(port):
            return port


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False

    return True
