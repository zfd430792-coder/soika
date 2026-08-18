"""Оркестратор: поднимает аккаунты, подсистемы и держит Сойку в воздухе."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
import time
import typing

from . import auth, compat, configuration, log
from .client import SoikaClient
from .configuration import ApiCredentials
from .database import Database
from .dispatcher import CommandDispatcher
from .loader import Modules
from .translations import Translator
from .version import BRAND, BRAND_EMOJI, __version__, __version_str__

logger = logging.getLogger(__name__)

#: Совместимость с модулями Hikka, которые лезут в ``main.BASE_DIR``
BASE_DIR = str(configuration.repo_root())

CORE = "soika.core"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="soika",
        description=f"{BRAND_EMOJI} {BRAND} — модульный Telegram-юзербот",
    )
    parser.add_argument("--port", type=int, help="порт веб-интерфейса (по умолчанию 8080)")
    parser.add_argument("--phone", help="номер телефона для входа без QR-кода")
    parser.add_argument("--qr-login", action="store_true", help="сразу показать QR-код")
    parser.add_argument("--no-web", action="store_true", help="не поднимать веб-интерфейс")
    parser.add_argument(
        "--web",
        action="store_true",
        help="держать веб-панель поднятой постоянно, а не только на время установки",
    )
    parser.add_argument("--data-root", help="каталог для сессий, базы и модулей")
    parser.add_argument("--proxy", help="socks5://user:pass@host:port")
    parser.add_argument("--debug", action="store_true", help="подробные логи")
    parser.add_argument("--root", action="store_true", help="не ругаться на запуск от root")
    return parser.parse_args(argv)


class Soika:
    """Точка сборки: аргументы → аккаунты → подсистемы → бесконечный цикл."""

    def __init__(self, argv: list[str] | None = None) -> None:
        self.arguments = parse_arguments(argv)
        self.clients: list[SoikaClient] = []
        self.web: typing.Any = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ #
    #  Запуск
    # ------------------------------------------------------------------ #
    def main(self) -> None:
        configuration.set_data_root(self.arguments.data_root)
        log.setup_logging(logging.DEBUG if self.arguments.debug else logging.INFO)
        compat.install()
        self._warn_about_root()

        print(f"\n{BRAND_EMOJI} {BRAND} {__version_str__}\n", flush=True)

        try:
            asyncio.run(self.amain())
        except KeyboardInterrupt:
            logger.info("Останавливаюсь по Ctrl+C")
        except auth.AuthError as e:
            logger.error("%s", e)
            sys.exit(1)

    def _warn_about_root(self) -> None:
        if os.name == "nt" or self.arguments.root:
            return

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            logger.warning("Сойка запущена от root — так делать не стоит, но продолжаю")

    async def amain(self) -> None:
        self._install_signal_handlers()

        proxy = auth.parse_proxy(self.arguments.proxy or configuration.get_config_key("proxy"))
        credentials = await self._obtain_credentials()

        if self.arguments.web and not self.arguments.no_web:
            await self._ensure_web()

        self.clients = await auth.restore_clients(credentials, proxy)

        if not self.clients:
            self.clients = [await self._first_login(credentials, proxy)]

        for client in self.clients:
            await self._init_client(client)

        logger.info("Сойка готова. Аккаунтов в работе: %s", len(self.clients))
        await self._run_forever()

    # ------------------------------------------------------------------ #
    #  Учётные данные
    # ------------------------------------------------------------------ #
    async def _obtain_credentials(self) -> ApiCredentials:
        if credentials := configuration.stored_credentials():
            return credentials

        if not self.arguments.no_web:
            with contextlib.suppress(ImportError):
                return await self._credentials_via_web()

        return await self._credentials_via_console()

    async def _ensure_web(self) -> typing.Any:
        if self.web is None:
            from .web import Web

            self.web = Web(self, port=configuration.gen_port(self.arguments.port))
            await self.web.start()

        return self.web

    async def _credentials_via_web(self) -> ApiCredentials:
        web = await self._ensure_web()
        return await web.wait_for_credentials()

    async def _credentials_via_console(self) -> ApiCredentials:
        if not auth.console_available():
            raise auth.AuthError(
                "Нет ни веб-интерфейса, ни терминала — укажи api_id/api_hash в config.json"
            )

        print("Нужны api_id и api_hash — возьми их на https://my.telegram.org/apps\n")

        while True:
            api_id = await asyncio.to_thread(input, "api_id: ")
            api_hash = await asyncio.to_thread(input, "api_hash: ")

            try:
                return configuration.store_credentials(api_id.strip(), api_hash.strip())
            except configuration.InvalidCredentials as e:
                print(f"  ↳ {e}\n")

    async def _first_login(self, credentials: ApiCredentials, proxy: tuple | None) -> SoikaClient:
        if self.web is not None:
            return await self.web.wait_for_login(credentials, proxy)

        return await auth.console_login(
            credentials,
            prefer_qr=not self.arguments.phone,
            phone=self.arguments.phone,
            proxy=proxy,
        )

    # ------------------------------------------------------------------ #
    #  Подсистемы аккаунта
    # ------------------------------------------------------------------ #
    async def _init_client(self, client: SoikaClient) -> None:
        database = Database(client)
        await database.init()
        client.db = database

        translator = Translator(client, database)
        await translator.init()
        client.translator = translator

        inline = await self._create_inline(client, database)

        modules = Modules(client, database, translator, inline)
        client.loader = modules

        if inline is not None:
            inline.modules = modules

        dispatcher = CommandDispatcher(modules, client, database, translator)
        client.dispatcher = dispatcher
        dispatcher.register(client)

        await modules.register_all()

        if inline is not None:
            await inline.start()

        await modules.send_ready()
        await self._finish_restart(client)

    async def _create_inline(self, client: SoikaClient, database: Database) -> typing.Any:
        try:
            from .inline import InlineManager
        except ImportError as e:
            logger.error("Инлайн-бот недоступен: %s", e)
            return None

        inline = InlineManager(client, database)
        client.inline = inline
        return inline

    # ------------------------------------------------------------------ #
    #  Досказать про перезапуск
    # ------------------------------------------------------------------ #
    async def _finish_restart(self, client: SoikaClient) -> None:
        """После .restart и .update дописать в то же сообщение, сколько заняло."""
        database = client.db
        restart_info = database.get(CORE, "restart_info")

        if not restart_info:
            return

        database.remove(CORE, "restart_info")
        took = round(time.time() - restart_info.get("started", time.time()), 1)

        with contextlib.suppress(Exception):
            await client.edit_message(
                restart_info["chat"],
                restart_info["message"],
                client.translator.gettext("restart_finished").format(took),
            )

    # ------------------------------------------------------------------ #
    #  Основной цикл и остановка
    # ------------------------------------------------------------------ #
    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        for name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, name, None)

            if sig is None:
                continue

            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self._stop.set)

        loop.set_exception_handler(log.asyncio_exception_handler)

    async def _run_forever(self) -> None:
        disconnects = [
            asyncio.ensure_future(client.run_until_disconnected()) for client in self.clients
        ]
        stopper = asyncio.ensure_future(self._stop.wait())

        await asyncio.wait([*disconnects, stopper], return_when=asyncio.FIRST_COMPLETED)

        for task in (*disconnects, stopper):
            task.cancel()

        await self.shutdown()

    async def shutdown(self) -> None:
        logger.info("Завершаю работу...")

        for client in self.clients:
            if client.loader is not None:
                with contextlib.suppress(Exception):
                    await client.loader.shutdown()

            if client.inline is not None:
                with contextlib.suppress(Exception):
                    await client.inline.stop()

            if client.db is not None:
                with contextlib.suppress(Exception):
                    await client.db.flush()

            with contextlib.suppress(Exception):
                await client.disconnect()

        if self.web is not None:
            with contextlib.suppress(Exception):
                await self.web.stop()

        logger.info("Сойка остановлена")


__all__ = ["BASE_DIR", "Soika", "__version__", "parse_arguments"]
