"""Совместимость с модулями Hikka / Heroku / FTG.

Готовых модулей под Hikka написаны тысячи, и ломать их из-за смены названия
пакета глупо. Здесь мы подменяем имена: ``hikkatl`` → ``telethon``,
``hikka`` → ``soika`` и так далее — импорты внутри чужих модулей просто работают.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import logging
import sys
import typing

logger = logging.getLogger(__name__)

#: Алиас → настоящий пакет
ALIASES = {
    "hikkatl": "telethon",
    "herokutl": "telethon",
    "hikka": "soika",
    "heroku": "soika",
}


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, module: typing.Any) -> None:
        self.module = module

    def create_module(self, spec: typing.Any) -> typing.Any:
        return self.module

    def exec_module(self, module: typing.Any) -> None:
        """Модуль уже выполнен под настоящим именем — делать нечего."""


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Отдаёт настоящий пакет, когда просят его псевдоним."""

    def find_spec(
        self,
        fullname: str,
        path: typing.Any = None,
        target: typing.Any = None,
    ) -> typing.Any:
        for alias, real in ALIASES.items():
            if fullname != alias and not fullname.startswith(f"{alias}."):
                continue

            real_name = real + fullname[len(alias) :]

            try:
                module = importlib.import_module(real_name)
            except ImportError:
                logger.debug("Псевдоним %s → %s не разрешился", fullname, real_name)
                return None

            sys.modules[fullname] = module
            return importlib.util.spec_from_loader(fullname, _AliasLoader(module))

        return None


_installed = False


def install() -> None:
    """Включить слой совместимости (вызывается один раз при старте)."""
    global _installed

    if _installed:
        return

    sys.meta_path.insert(0, _AliasFinder())
    _installed = True
    logger.debug("Слой совместимости с модулями Hikka включён")
