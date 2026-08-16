"""Загрузчик модулей — сердце Сойки.

Отсюда модули регистрируются, получают доступ к клиенту и базе, ставят себе
зависимости и корректно выгружаются. Публичный API (декораторы, ``ModuleConfig``,
``validators``) намеренно совпадает с Hikka.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import logging
import os
import re
import sys
import typing
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from . import configuration, utils, validators  # noqa: F401 — validators нужен модулям
from .security import (  # noqa: F401 — реэкспорт декораторов прав для модулей
    everyone,
    group_admin,
    group_member,
    group_owner,
    inline_everyone,
    owner,
    pm,
    sudo,
    support,
    unrestricted,
)
from .translations import Strings
from .types import (  # noqa: F401 — модули импортируют это из loader
    ConfigValue,
    Library,
    LibraryConfig,
    LoadError,
    Module,
    ModuleConfig,
    SelfSuspend,
    SelfUnload,
    StopLoop,
)

logger = logging.getLogger(__name__)

MODULES_PACKAGE = "soika.modules"
EXTERNAL_DIR = "loaded_modules"

VALID_URL = re.compile(r"^https?://\S+$")
REQUIREMENTS_RE = re.compile(r"^\s*#\s*requires:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
META_RE = re.compile(r"^\s*#\s*meta\s+([a-zA-Z_]+):\s*(.+)$", re.MULTILINE)
SCOPE_RE = re.compile(r"^\s*#\s*scope:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]+")


# --------------------------------------------------------------------------- #
#  Декораторы
# --------------------------------------------------------------------------- #
def _decorator(attribute: str) -> typing.Callable:
    """Собрать декоратор, который работает и как ``@dec``, и как ``@dec(...)``."""

    def outer(*args: typing.Any, **kwargs: typing.Any) -> typing.Callable:
        def apply(func: typing.Callable) -> typing.Callable:
            setattr(func, attribute, True)

            for key, value in kwargs.items():
                setattr(func, key, value)

            return func

        if len(args) == 1 and not kwargs and callable(args[0]):
            return apply(args[0])

        return apply

    outer.__name__ = attribute
    return outer


command = _decorator("is_command")
watcher = _decorator("is_watcher")
inline_handler = _decorator("is_inline_handler")
callback_handler = _decorator("is_callback_handler")


def raw_handler(*updates: typing.Any) -> typing.Callable:
    """Подписка на сырые апдейты Telegram."""

    def decorator(func: typing.Callable) -> typing.Callable:
        func.is_raw_handler = True
        func.updates = updates
        func.id = utils.rand(16)
        return func

    return decorator


def tag(*tags: str, **kwargs: typing.Any) -> typing.Callable:
    """Фильтры для команд и вотчеров: ``only_pm``, ``no_commands``, ``out`` и т. д."""

    def decorator(func: typing.Callable) -> typing.Callable:
        existing = list(getattr(func, "tags", []))
        func.tags = existing + list(tags)

        for key, value in kwargs.items():
            setattr(func, key, value)

        return func

    return decorator


def tds(cls: type) -> type:
    """Совместимость с Hikka: перевод докстрингов берётся из ``strings``.

    У нас документация команд и так ищется в переводах (см.
    :meth:`soika.types.Module.get_command_doc`), поэтому декоратор — просто метка.
    """
    cls._translatable_docstrings = True
    return cls


translatable_docstring = tds


class InfiniteLoop:
    """Фоновая задача модуля: ``@loader.loop(interval=60, autostart=True)``."""

    def __init__(
        self,
        func: typing.Callable,
        interval: float,
        autostart: bool,
        wait_before: bool,
        stop_clause: str | None,
    ) -> None:
        self.func = func
        self.interval = interval
        self.autostart = autostart
        self.wait_before = wait_before
        self.stop_clause = stop_clause

        self.module_instance: typing.Any = None
        self.task: asyncio.Task | None = None
        self.status = False

    def __repr__(self) -> str:
        return f"<InfiniteLoop {self.func.__name__} каждые {self.interval}с, запущен={self.status}>"

    def start(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        if self.task and not self.task.done():
            return

        self.task = asyncio.ensure_future(self._run(*args, **kwargs))

    def stop(self) -> None:
        self.status = False

        if self.task and not self.task.done():
            self.task.cancel()

    def _should_stop(self) -> bool:
        if not self.stop_clause or self.module_instance is None:
            return False

        return bool(self.module_instance.db.get(type(self.module_instance).__name__, self.stop_clause))

    async def _run(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        self.status = True

        while self.status:
            if self.wait_before:
                await asyncio.sleep(self.interval)

            if self._should_stop():
                break

            try:
                await self.func(self.module_instance, *args, **kwargs)
            except StopLoop:
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Фоновая задача %s упала", self.func.__name__)

            if not self.wait_before:
                await asyncio.sleep(self.interval)

        self.status = False


def loop(
    interval: float = 5,
    autostart: bool = False,
    wait_before: bool = False,
    stop_clause: str | None = None,
) -> typing.Callable:
    def decorator(func: typing.Callable) -> InfiniteLoop:
        return InfiniteLoop(func, interval, autostart, wait_before, stop_clause)

    return decorator


# --------------------------------------------------------------------------- #
#  Загрузка исходников
# --------------------------------------------------------------------------- #
class StringLoader(importlib.abc.SourceLoader):
    """Позволяет импортировать модуль прямо из строки с исходником."""

    def __init__(self, source: str, origin: str) -> None:
        self.data = source.encode() if isinstance(source, str) else source
        self.origin = origin

    def get_source(self, fullname: str) -> str:
        return self.data.decode()

    def get_code(self, fullname: str) -> typing.Any:
        return compile(self.data, self.origin, "exec", dont_inherit=True)

    def get_filename(self, fullname: str) -> str:
        return self.origin

    def get_data(self, path: str | bytes) -> bytes:
        return self.data

    def create_module(self, spec: typing.Any) -> None:
        return None


def parse_meta(source: str) -> dict[str, str]:
    """``# meta developer: @user`` → ``{"developer": "@user"}``."""
    return {key.lower(): value.strip() for key, value in META_RE.findall(source)}


def parse_requirements(source: str) -> list[str]:
    packages: list[str] = []

    for line in REQUIREMENTS_RE.findall(source):
        for raw in re.split(r"[\s,]+", line.strip()):
            if match := PACKAGE_NAME_RE.match(raw.strip()):
                packages.append(match.group(0))

    return list(dict.fromkeys(packages))


def is_installed(package: str) -> bool:
    try:
        distribution(package)
    except (PackageNotFoundError, ValueError):
        return importlib.util.find_spec(package.replace("-", "_")) is not None

    return True


def in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix) or "VIRTUAL_ENV" in os.environ


# --------------------------------------------------------------------------- #
#  Реестр модулей
# --------------------------------------------------------------------------- #
class Modules:
    """Хранит все загруженные модули и раздаёт команды диспетчеру."""

    def __init__(
        self,
        client: typing.Any,
        db: typing.Any,
        translator: typing.Any,
        inline: typing.Any = None,
    ) -> None:
        self.client = client
        self.db = db
        self.translator = translator
        self.inline = inline

        self.modules: list[Module] = []
        self.libraries: list[Library] = []

        self.commands: dict[str, typing.Callable] = {}
        self.aliases: dict[str, str] = {}
        self.watchers: list[typing.Callable] = []
        self.inline_handlers: dict[str, typing.Callable] = {}
        self.callback_handlers: dict[str, typing.Callable] = {}
        self.raw_handlers: list[typing.Callable] = []

    # ------------------------------------------------------------------ #
    #  Пути
    # ------------------------------------------------------------------ #
    @property
    def builtin_dir(self) -> Path:
        return Path(__file__).parent / "modules"

    @property
    def external_dir(self) -> Path:
        path = configuration.data_root() / EXTERNAL_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------ #
    #  Массовая регистрация
    # ------------------------------------------------------------------ #
    async def register_all(self) -> None:
        """Загрузить встроенные модули, затем ранее установленные пользователем."""
        for path in sorted(self.builtin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue

            self._safe_register_file(path, external=False)

        for path in sorted(self.external_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue

            self._safe_register_file(path, external=True)

        logger.info(
            "Загружено модулей: %s (команд: %s)",
            len(self.modules),
            len(self.commands),
        )

    def _safe_register_file(self, path: Path, *, external: bool) -> Module | None:
        try:
            source = path.read_text(encoding="utf-8")
            return self.register_source(source, origin=str(path), save_fs=False)
        except Exception as e:
            logger.exception("Модуль %s не загрузился: %s", path.name, e)

            if external:
                logger.warning("Удали %s, если он больше не нужен", path)

            return None

    # ------------------------------------------------------------------ #
    #  Регистрация одного модуля
    # ------------------------------------------------------------------ #
    def register_source(
        self,
        source: str,
        *,
        origin: str = "<string>",
        save_fs: bool = False,
    ) -> Module:
        """Выполнить исходник и зарегистрировать найденный в нём модуль."""
        for scope in SCOPE_RE.findall(source):
            logger.debug("Модуль %s объявил scope: %s", origin, scope.strip())

        module_name = f"{MODULES_PACKAGE}.{utils.rand(12)}"
        spec = importlib.machinery.ModuleSpec(
            module_name,
            StringLoader(source, origin),
            origin=origin,
        )

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        instance = self._instantiate(module, module_name)
        instance.__origin__ = origin
        instance.__meta__ = parse_meta(source)
        instance.__source__ = source
        instance.__module_name__ = module_name

        self.complete_registration(instance)

        if save_fs:
            self._save_to_disk(instance, source)

        return instance

    def _instantiate(self, module: typing.Any, module_name: str) -> Module:
        candidates = [
            value
            for value in vars(module).values()
            if inspect.isclass(value) and issubclass(value, Module) and value is not Module
        ]

        if candidates:
            return candidates[0]()

        # Старый формат FTG: def register(cb): cb(MyModule())
        if hasattr(module, "register"):
            captured: list[Module] = []
            module.register(captured.append)

            if captured:
                return captured[0]

        sys.modules.pop(module_name, None)
        raise LoadError("В файле нет класса, унаследованного от loader.Module")

    def _save_to_disk(self, instance: Module, source: str) -> None:
        path = self.external_dir / f"{type(instance).__name__}.py"
        path.write_text(source, encoding="utf-8")
        instance.__origin__ = str(path)

    # ------------------------------------------------------------------ #
    #  Установка модуля пользователем
    # ------------------------------------------------------------------ #
    async def load_module(
        self,
        source: str,
        *,
        origin: str = "<string>",
        did_requirements: bool = False,
        save_fs: bool = True,
    ) -> Module:
        """Установить модуль: доставить зависимости, зарегистрировать, сохранить."""
        if not did_requirements and (packages := parse_requirements(source)):
            missing = [package for package in packages if not is_installed(package)]

            if missing and await self.install_requirements(missing):
                return await self.load_module(
                    source,
                    origin=origin,
                    did_requirements=True,
                    save_fs=save_fs,
                )

        instance = self.register_source(source, origin=origin, save_fs=save_fs)

        if VALID_URL.match(origin):
            installed = self.db.pointer("soika.loader", "installed", {}, item_type=dict)
            installed[type(instance).__name__] = origin

        await self.send_ready_one(instance, from_dlmod=True)
        return instance

    async def install_requirements(self, packages: list[str]) -> bool:
        """Поставить недостающие пакеты через pip. Возвращает True, если что-то встало."""
        logger.info("Ставлю зависимости модуля: %s", ", ".join(packages))

        command_line = [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check"]

        if not in_virtualenv():
            command_line.append("--user")

        process = await asyncio.create_subprocess_exec(
            *command_line,
            *packages,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()

        if process.returncode != 0:
            logger.error(
                "pip не смог поставить %s:\n%s",
                ", ".join(packages),
                output.decode(errors="replace")[-2000:],
            )
            raise LoadError(f"Не удалось установить зависимости: {', '.join(packages)}")

        importlib.invalidate_caches()
        return True

    # ------------------------------------------------------------------ #
    #  Регистрация внутренностей модуля
    # ------------------------------------------------------------------ #
    def complete_registration(self, instance: Module) -> None:
        instance.allmodules = self
        instance.client = self.client
        instance.db = self.db
        instance.inline = self.inline
        instance.tg_id = self.client.tg_id
        instance.lookup = self.lookup
        instance.strings = Strings(instance, self.translator)

        instance.commands = {}
        instance.watchers = {}
        instance.inline_handlers = {}
        instance.callback_handlers = {}

        for existing in list(self.modules):
            if type(existing).__name__ == type(instance).__name__:
                logger.debug("Заменяю ранее загруженный %s", type(instance).__name__)
                utils.spawn(self.unload_module(type(existing).__name__, delete_file=False))

        self._collect_handlers(instance)
        self.send_config_one(instance)

        self.modules.append(instance)
        self._rebuild_registry()

    #: Метки, которые ставят декораторы — по ним обработчик регистрируется явно
    MARKERS = (
        "is_command",
        "is_watcher",
        "is_inline_handler",
        "is_callback_handler",
        "is_raw_handler",
    )

    def _collect_handlers(self, instance: Module) -> None:
        for name, func in inspect.getmembers(instance, inspect.ismethod):
            explicit = any(getattr(func, marker, False) for marker in self.MARKERS)

            # Служебные методы модуля обработчиками не становятся —
            # только если модуль сам пометил их декоратором
            if name.startswith("_") and not explicit:
                continue

            if getattr(func, "is_command", False) or (name.endswith("cmd") and len(name) > 3):
                command_name = getattr(func, "command_name", None) or name.removesuffix("cmd")
                instance.commands[command_name.lower()] = func

            if getattr(func, "is_watcher", False) or name == "watcher":
                instance.watchers[name] = func

            if getattr(func, "is_inline_handler", False) or name.endswith("_inline_handler"):
                handler = name.removesuffix("_inline_handler")
                instance.inline_handlers[handler.lower()] = func

            if getattr(func, "is_callback_handler", False) or name.endswith("_callback_handler"):
                handler = name.removesuffix("_callback_handler")
                instance.callback_handlers[handler.lower()] = func

            if getattr(func, "is_raw_handler", False):
                self.raw_handlers.append(func)

    def _rebuild_registry(self) -> None:
        """Пересобрать плоские реестры команд/вотчеров из живых модулей."""
        self.commands.clear()
        self.aliases.clear()
        self.watchers.clear()
        self.inline_handlers.clear()
        self.callback_handlers.clear()

        for instance in self.modules:
            for name, func in instance.commands.items():
                if name in self.commands:
                    logger.warning(
                        "Команда .%s уже занята модулем %s — %s её перебивает",
                        name,
                        type(self.commands[name].__self__).__name__,
                        type(instance).__name__,
                    )

                self.commands[name] = func

                for alias in self._aliases_of(func):
                    self.aliases[alias.lower()] = name

            self.watchers.extend(instance.watchers.values())
            self.inline_handlers.update(instance.inline_handlers)
            self.callback_handlers.update(instance.callback_handlers)

        for alias, target in self.db.get("soika.settings", "aliases", {}).items():
            if target in self.commands:
                self.aliases[alias.lower()] = target

    @staticmethod
    def _aliases_of(func: typing.Callable) -> list[str]:
        aliases = list(getattr(func, "aliases", []) or [])

        if single := getattr(func, "alias", None):
            aliases.append(single)

        return aliases

    # ------------------------------------------------------------------ #
    #  Конфиги
    # ------------------------------------------------------------------ #
    def send_config(self) -> None:
        for instance in self.modules:
            self.send_config_one(instance)

    def send_config_one(self, instance: Module) -> None:
        if not getattr(instance, "config", None):
            return

        module_name = type(instance).__name__
        saved = self.db.get(module_name, "__config__", {}) or {}

        for option in instance.config.options:
            if (env_value := os.environ.get(f"{module_name}.{option}")) is not None:
                instance.config.set_no_raise(option, env_value)
            elif option in saved:
                instance.config.set_no_raise(option, saved[option])

        with contextlib.suppress(Exception):
            utils.spawn(utils.maybe_await(instance.config_complete()))

    def save_config(self, instance: Module) -> None:
        if getattr(instance, "config", None):
            self.db.set(type(instance).__name__, "__config__", instance.config.as_dict())

    # ------------------------------------------------------------------ #
    #  Готовность
    # ------------------------------------------------------------------ #
    async def send_ready(self) -> None:
        await asyncio.gather(*[self.send_ready_one(instance) for instance in list(self.modules)])

    async def send_ready_one(
        self,
        instance: Module,
        *,
        from_dlmod: bool = False,
    ) -> None:
        for _, value in inspect.getmembers(type(instance)):
            if isinstance(value, InfiniteLoop):
                value.module_instance = instance

                if value.autostart:
                    value.start()

        try:
            if from_dlmod:
                await instance.on_dlmod()

            await instance.client_ready(self.client, self.db)
        except SelfUnload as e:
            logger.info("Модуль %s выгрузил себя сам: %s", type(instance).__name__, e.error_message)
            await self.unload_module(type(instance).__name__, delete_file=False)
        except SelfSuspend as e:
            logger.info("Модуль %s приостановлен: %s", type(instance).__name__, e.error_message)
            self.modules.remove(instance)
            self._rebuild_registry()
        except Exception:
            logger.exception("client_ready модуля %s упал", type(instance).__name__)

    # ------------------------------------------------------------------ #
    #  Выгрузка
    # ------------------------------------------------------------------ #
    async def unload_module(self, name: str, *, delete_file: bool = True) -> list[str]:
        """Выгрузить модуль по имени класса или по названию из strings."""
        instance = self.lookup(name)

        if instance is None:
            return []

        for _, value in inspect.getmembers(type(instance)):
            if isinstance(value, InfiniteLoop):
                value.stop()

        with contextlib.suppress(Exception):
            await instance.on_unload()

        self.raw_handlers = [
            handler
            for handler in self.raw_handlers
            if type(getattr(handler, "__self__", None)).__name__ != type(instance).__name__
        ]

        with contextlib.suppress(ValueError):
            self.modules.remove(instance)

        sys.modules.pop(getattr(instance, "__module_name__", ""), None)
        self._rebuild_registry()

        module_name = type(instance).__name__
        installed = self.db.pointer("soika.loader", "installed", {}, item_type=dict)
        installed.pop(module_name, None)

        if delete_file:
            path = self.external_dir / f"{module_name}.py"

            with contextlib.suppress(OSError):
                path.unlink()

        logger.info("Модуль %s выгружен", module_name)
        return [module_name]

    # ------------------------------------------------------------------ #
    #  Поиск и вызов
    # ------------------------------------------------------------------ #
    def lookup(self, name: str, include_libraries: bool = False) -> typing.Any:
        needle = name.lower().strip()

        for instance in self.modules:
            names = {type(instance).__name__.lower(), str(instance.name).lower()}

            if needle in names:
                return instance

        if include_libraries:
            for library in self.libraries:
                if needle == type(library).__name__.lower():
                    return library

        return None

    def dispatch(self, command: str) -> tuple[str | None, typing.Callable | None]:
        command = command.lower()

        if command in self.commands:
            return command, self.commands[command]

        if (target := self.aliases.get(command)) and target in self.commands:
            return target, self.commands[target]

        return None, None

    async def invoke(
        self,
        command: str,
        args: str = "",
        peer: typing.Any = None,
        message: typing.Any = None,
        module: typing.Any = None,
    ) -> typing.Any:
        """Программно выполнить команду — удобно для модулей-обёрток."""
        name, func = self.dispatch(command)

        if func is None:
            raise LoadError(f"Команда {command} не найдена")

        if message is None:
            prefix = self.db.get("soika.settings", "prefixes", ["."])[0]
            message = await self.client.send_message(
                peer or "me",
                f"{prefix}{name} {args}".strip(),
            )

        return await func(message)

    # ------------------------------------------------------------------ #
    #  Библиотеки
    # ------------------------------------------------------------------ #
    async def import_lib(self, url: str, *, suspend_on_error: bool = False) -> typing.Any:
        """Скачать и подключить библиотеку (общий код для нескольких модулей)."""
        if not VALID_URL.match(url) or not url.endswith(".py"):
            raise LoadError(f"«{url}» не похоже на ссылку на библиотеку")

        for library in self.libraries:
            if getattr(library, "__origin__", None) == url:
                return library

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session, session.get(url) as response:
                response.raise_for_status()
                source = await response.text()
        except Exception as e:
            if suspend_on_error:
                raise SelfSuspend("Библиотека недоступна") from e

            raise LoadError(f"Не скачать библиотеку: {e}") from e

        module_name = f"soika.libraries.{utils.rand(12)}"
        spec = importlib.machinery.ModuleSpec(module_name, StringLoader(source, url), origin=url)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        candidates = [
            value
            for value in vars(module).values()
            if inspect.isclass(value) and issubclass(value, Library) and value is not Library
        ]

        if not candidates:
            raise LoadError("В файле нет класса, унаследованного от loader.Library")

        library = candidates[0]()
        library.__origin__ = url
        library.client = self.client
        library.db = self.db
        library.lookup = self.lookup
        library.allmodules = self
        library.tg_id = self.client.tg_id
        library.strings = Strings(library, self.translator)

        await utils.maybe_await(library.init())
        self.libraries.append(library)
        return library

    # ------------------------------------------------------------------ #
    #  Завершение работы
    # ------------------------------------------------------------------ #
    async def shutdown(self) -> None:
        for instance in list(self.modules):
            for _, value in inspect.getmembers(type(instance)):
                if isinstance(value, InfiniteLoop):
                    value.stop()

            with contextlib.suppress(Exception):
                await instance.on_unload()
