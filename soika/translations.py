"""Переводы: языковые паки ядра и строки модулей.

Поиск строки идёт по цепочке: внешний языковой пак → ``strings_<язык>`` модуля →
``strings`` модуля. Так одинаково хорошо живут и наши модули (базовый язык —
русский), и модули Hikka (базовый — английский, русский в ``strings_ru``).
"""

from __future__ import annotations

import json
import logging
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LANG = "ru"
LANGPACKS_DIR = Path(__file__).parent / "langpacks"
DB_OWNER = "soika.translations"


class Translator:
    """Язык интерфейса и строки ядра."""

    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self._client = client
        self._db = db
        self._core: dict[str, dict[str, str]] = {}
        self._external: dict[str, dict[str, str]] = {}

    @property
    def lang(self) -> str:
        return self._db.get(DB_OWNER, "lang", DEFAULT_LANG)

    @property
    def available(self) -> list[str]:
        return sorted(self._core)

    async def init(self) -> bool:
        self._load_core()
        await self._load_external()
        return bool(self._core)

    def _load_core(self) -> None:
        for path in LANGPACKS_DIR.glob("*.json"):
            try:
                with path.open(encoding="utf-8") as f:
                    self._core[path.stem] = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Языковой пак %s не читается: %s", path.name, e)

    async def _load_external(self) -> None:
        """Пользовательский языковой пак по ссылке (команда ``.dlpack``)."""
        url = self._db.get(DB_OWNER, "pack")

        if not url:
            self._external = self._db.get(DB_OWNER, "custom_strings", {}) or {}
            return

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session, session.get(url) as response:
                response.raise_for_status()
                self._external = json.loads(await response.text())
        except Exception as e:  # noqa: BLE001 — интернета может не быть, это не повод падать
            logger.error("Не удалось скачать языковой пак %s: %s", url, e)
            self._external = self._db.get(DB_OWNER, "custom_strings", {}) or {}

    def set_lang(self, lang: str) -> None:
        self._db.set(DB_OWNER, "lang", lang)

    def gettext(self, key: str, default: str | None = None) -> str:
        """Строка ядра на текущем языке."""
        for lang in (self.lang, DEFAULT_LANG, "en"):
            if key in self._core.get(lang, {}):
                return self._core[lang][key]

        return default if default is not None else key

    def module_string(self, module_name: str, key: str) -> str | None:
        return self._external.get(module_name, {}).get(key)


class Strings:
    """Объект ``self.strings`` внутри модуля.

    Поддерживает и вызов, и индексацию: ``self.strings("name")`` == ``self.strings["name"]``.
    """

    def __init__(self, module: typing.Any, translator: Translator | None = None) -> None:
        self._module = module
        self._translator = translator
        self._base: dict[str, str] = dict(getattr(module, "strings", {}) or {})

    @property
    def lang(self) -> str:
        return self._translator.lang if self._translator else DEFAULT_LANG

    @property
    def name(self) -> str:
        return self._base.get("name", type(self._module).__name__)

    def _lookup(self, key: str) -> str | None:
        module_name = self._base.get("name", type(self._module).__name__)

        if self._translator and (
            (external := self._translator.module_string(module_name, key)) is not None
        ):
            return external

        localized = getattr(self._module, f"strings_{self.lang}", None)

        if isinstance(localized, dict) and key in localized:
            return localized[key]

        return self._base.get(key)

    def __call__(self, key: str, default: str | None = None) -> str:
        value = self._lookup(key)

        if value is not None:
            return value

        if default is not None:
            return default

        logger.debug("Нет строки «%s» в модуле %s", key, self.name)
        return f"Нет строки «{key}»"

    def __getitem__(self, key: str) -> str:
        return self(key)

    def get(self, key: str, default: str | None = None) -> str | None:
        value = self._lookup(key)
        return value if value is not None else default

    def __contains__(self, key: str) -> bool:
        return self._lookup(key) is not None

    def __iter__(self) -> typing.Iterator[str]:
        return iter(self.keys())

    def keys(self) -> list[str]:
        localized = getattr(self._module, f"strings_{self.lang}", None) or {}
        return sorted({*self._base, *localized})

    def to_dict(self) -> dict[str, str]:
        return {key: self(key) for key in self.keys()}
