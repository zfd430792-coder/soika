"""Базовые типы модулей Сойки: ``Module``, ``Library`` и конфиг модуля.

Имена и поведение повторяют Hikka — модули, написанные под неё, чувствуют себя
здесь как дома.
"""

from __future__ import annotations

import inspect
import logging
import typing
from dataclasses import dataclass, field

from . import utils
from .validators import ValidationError, Validator

logger = logging.getLogger(__name__)


class SelfUnload(Exception):
    """Модуль сам просит себя выгрузить (например, не выполнены условия работы)."""

    def __init__(self, error_message: str = "") -> None:
        super().__init__(error_message)
        self.error_message = error_message


class SelfSuspend(Exception):
    """Модуль просит приостановить себя до перезапуска."""

    def __init__(self, error_message: str = "") -> None:
        super().__init__(error_message)
        self.error_message = error_message


class LoadError(Exception):
    """Модуль не может быть загружен — причина уйдёт пользователю."""

    def __init__(self, error_message: str = "") -> None:
        super().__init__(error_message)
        self.error_message = error_message


class StopLoop(Exception):
    """Выход из ``@loader.loop``."""


# --------------------------------------------------------------------------- #
#  Конфиг модуля
# --------------------------------------------------------------------------- #
@dataclass
class ConfigValue:
    """Одна настройка модуля."""

    option: str
    default: typing.Any = None
    doc: str | typing.Callable[[], str] = ""
    value: typing.Any = field(default=None)
    validator: Validator | None = None
    on_change: typing.Callable[[], typing.Any] | None = None

    def __post_init__(self) -> None:
        if self.value is None:
            self.value = self.default

    def set_value(self, value: typing.Any, *, validate: bool = True) -> typing.Any:
        if validate and self.validator is not None and value is not None:
            value = self.validator.validate(value)

        self.value = value

        if self.on_change is not None:
            try:
                result = self.on_change()

                if inspect.isawaitable(result):
                    utils.spawn(result)
            except Exception:
                logger.exception("Обработчик изменения настройки %s упал", self.option)

        return value

    def get_doc(self) -> str:
        return self.doc() if callable(self.doc) else str(self.doc)


class ModuleConfig(dict):
    """Конфиг модуля: ``self.config["ключ"]`` с валидацией и документацией.

    Принимает как новые ``ConfigValue``, так и старый формат Hikka —
    тройки ``("ключ", значение_по_умолчанию, "описание")`` подряд.
    """

    def __init__(self, *entries: typing.Any) -> None:
        if entries and isinstance(entries[0], ConfigValue):
            values = list(entries)
        else:
            values = [
                ConfigValue(
                    option=entries[i],
                    default=entries[i + 1],
                    doc=entries[i + 2] if i + 2 < len(entries) else "",
                )
                for i in range(0, len(entries), 3)
            ]

        self._config: dict[str, ConfigValue] = {value.option: value for value in values}
        super().__init__({name: value.value for name, value in self._config.items()})

    # -- доступ ---------------------------------------------------------- #
    def __getitem__(self, key: str) -> typing.Any:
        return self._config[key].value

    def __setitem__(self, key: str, value: typing.Any) -> None:
        self._config[key].set_value(value)
        super().__setitem__(key, self._config[key].value)

    def set_no_raise(self, key: str, value: typing.Any) -> bool:
        """Записать значение, не роняя загрузку из-за кривых данных в базе."""
        try:
            self[key] = value
        except (ValidationError, KeyError) as e:
            logger.warning("Настройка %s: %s — беру значение по умолчанию", key, e)

            if key in self._config:
                self._config[key].set_value(self._config[key].default, validate=False)
                super().__setitem__(key, self._config[key].default)

            return False

        return True

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        return self._config[key].value if key in self._config else default

    def getdoc(self, key: str) -> str:
        return self._config[key].get_doc()

    def getdef(self, key: str) -> typing.Any:
        return self._config[key].default

    def getvalidator(self, key: str) -> Validator | None:
        return self._config[key].validator

    def reload(self) -> None:
        for name, value in self._config.items():
            super().__setitem__(name, value.value)

    def as_dict(self) -> dict[str, typing.Any]:
        return {name: value.value for name, value in self._config.items()}

    @property
    def options(self) -> list[str]:
        return list(self._config)


# --------------------------------------------------------------------------- #
#  Модуль
# --------------------------------------------------------------------------- #
class Module:
    """Базовый класс модуля.

    Загрузчик подставляет сюда ``client``, ``db``, ``inline``, ``allmodules``
    и заменяет ``strings`` на объект с переводами.
    """

    strings: typing.Any = {"name": "Module"}
    config: ModuleConfig | None = None

    # Подставляется загрузчиком
    client: typing.Any = None
    db: typing.Any = None
    inline: typing.Any = None
    allmodules: typing.Any = None
    tg_id: int = 0
    lookup: typing.Callable[[str], typing.Any] = None  # type: ignore[assignment]

    commands: dict[str, typing.Callable]
    watchers: dict[str, typing.Callable]
    inline_handlers: dict[str, typing.Callable]
    callback_handlers: dict[str, typing.Callable]

    @property
    def name(self) -> str:
        return self.strings["name"] if self.strings else type(self).__name__

    @property
    def commands_doc(self) -> dict[str, str]:
        return {command: self.get_command_doc(command) for command in self.commands}

    def get_command_doc(self, command: str) -> str:
        """Описание команды: сперва перевод, потом докстринг."""
        if self.strings and (translated := self.strings.get(f"_cmd_doc_{command}")):
            return translated

        func = self.commands.get(command)
        return inspect.getdoc(func) or "" if func else ""

    def get_module_doc(self) -> str:
        if self.strings and (translated := self.strings.get("_cls_doc")):
            return translated

        return inspect.getdoc(self) or ""

    # -- быстрый доступ к базе ------------------------------------------- #
    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        return self.db.get(type(self).__name__, key, default)

    def set(self, key: str, value: typing.Any) -> bool:
        return self.db.set(type(self).__name__, key, value)

    def pointer(self, key: str, default: typing.Any = None, item_type: typing.Any = None):
        return self.db.pointer(type(self).__name__, key, default, item_type)

    # -- взаимодействие с другими модулями -------------------------------- #
    async def import_lib(self, url: str, *, suspend_on_error: bool = False) -> typing.Any:
        return await self.allmodules.import_lib(url, suspend_on_error=suspend_on_error)

    async def invoke(
        self,
        command: str,
        args: str = "",
        peer: typing.Any = None,
        message: typing.Any = None,
    ) -> typing.Any:
        """Вызвать чужую команду программно."""
        return await self.allmodules.invoke(command, args, peer=peer, message=message, module=self)

    # -- жизненный цикл --------------------------------------------------- #
    async def client_ready(self, client: typing.Any = None, db: typing.Any = None) -> None:
        """Клиент подключён, база готова — здесь модуль доинициализируется."""

    async def on_dlmod(self) -> None:
        """Вызывается один раз сразу после установки модуля через .dlmod/.loadmod."""

    async def on_unload(self) -> None:
        """Модуль выгружают — самое время погасить задачи и соединения."""

    async def config_complete(self) -> None:
        """Конфиг применён (в том числе после правки через .cfg)."""


class Library:
    """Библиотека — общий код для модулей, без своих команд."""

    strings: typing.Any = {"name": "Library"}

    client: typing.Any = None
    db: typing.Any = None
    lookup: typing.Callable[[str], typing.Any] = None  # type: ignore[assignment]
    allmodules: typing.Any = None
    tg_id: int = 0

    async def init(self) -> None:
        """Инициализация библиотеки после загрузки."""

    async def on_lib_update(self, new_instance: Library) -> None:
        """Библиотеку переустановили более новой версией."""


class LibraryConfig(ModuleConfig):
    """Конфиг библиотеки — отличается только владельцем ключа в базе."""


__all__ = [
    "ConfigValue",
    "Library",
    "LibraryConfig",
    "LoadError",
    "Module",
    "ModuleConfig",
    "SelfSuspend",
    "SelfUnload",
    "StopLoop",
]
