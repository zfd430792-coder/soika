"""Веб-установщик и панель управления.

Поднимается на первом запуске: через браузер вводятся api_id/api_hash и
происходит вход в аккаунт (QR-код или номер телефона). Дальше та же страница
работает как небольшая панель — статус, модули, логи, перезапуск.

Доступ закрыт одноразовым токеном, который печатается в консоль.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import secrets
import socket
import typing
from pathlib import Path

from aiohttp import web
from telethon.sessions import StringSession

from .. import auth, configuration, log
from ..version import BRAND, BRAND_EMOJI, __version_str__

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE = Path(__file__).parent / "templates" / "index.html"
COOKIE = "soika_token"


class WebAuthSession:
    """Состояние входа в аккаунт: QR-код и формы кода/пароля."""

    def __init__(self, credentials: typing.Any, proxy: tuple | None) -> None:
        self.client = auth.build_client(StringSession(), credentials, proxy)
        self.qr_png: str = ""
        self.error: str = ""
        self.stage: str = "qr"

        self.done: asyncio.Future = asyncio.get_event_loop().create_future()
        self._code: asyncio.Future | None = None
        self._password: asyncio.Future | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.client.connect()
        self._task = asyncio.ensure_future(self._qr_flow())

    # -- сценарии --------------------------------------------------------- #
    async def _qr_flow(self) -> None:
        try:
            await auth.qr_login(
                self.client,
                on_url=self._set_qr,
                ask_password=self._ask_password,
            )
            self._finish()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — покажем ошибку в браузере
            self.error = str(e)

    async def start_phone(self, phone: str) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

        self.stage = "code"
        self.error = ""
        self._task = asyncio.ensure_future(self._phone_flow(phone))

    async def _phone_flow(self, phone: str) -> None:
        try:
            await auth.phone_login(
                self.client,
                ask_phone=lambda: self._resolved(phone),
                ask_code=self._ask_code,
                ask_password=self._ask_password,
                phone=phone,
            )
            self._finish()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self.stage = "phone"

    def _finish(self) -> None:
        auth.persist_session(self.client)
        self.stage = "done"

        if not self.done.done():
            self.done.set_result(self.client)

    # -- мост между формами и корутинами входа ---------------------------- #
    async def _set_qr(self, url: str) -> None:
        self.qr_png = base64.b64encode(auth.render_qr_png(url)).decode()

    @staticmethod
    async def _resolved(value: str) -> str:
        return value

    async def _ask_code(self) -> str:
        self.stage = "code"
        self._code = asyncio.get_event_loop().create_future()
        return await self._code

    async def _ask_password(self) -> str:
        self.stage = "password"
        self._password = asyncio.get_event_loop().create_future()
        return await self._password

    def submit_code(self, code: str) -> bool:
        if self._code and not self._code.done():
            self._code.set_result(code)
            return True

        return False

    def submit_password(self, password: str) -> bool:
        if self._password and not self._password.done():
            self._password.set_result(password)
            return True

        return False


class Web:
    """aiohttp-приложение: установка, вход и панель."""

    def __init__(self, soika: typing.Any, port: int = 8080) -> None:
        self.soika = soika
        self.port = port
        self.token = secrets.token_urlsafe(16)

        self.app = web.Application()
        self.runner: web.AppRunner | None = None

        self._credentials: asyncio.Future | None = None
        self.auth_session: WebAuthSession | None = None

        self._setup_routes()

    def _setup_routes(self) -> None:
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/api/status", self._status)
        self.app.router.add_post("/api/credentials", self._set_credentials)
        self.app.router.add_post("/api/phone", self._submit_phone)
        self.app.router.add_post("/api/code", self._submit_code)
        self.app.router.add_post("/api/password", self._submit_password)
        self.app.router.add_post("/api/restart", self._restart)
        self.app.router.add_get("/api/logs", self._logs)

        if STATIC_DIR.is_dir():
            self.app.router.add_static("/static", STATIC_DIR)

    # ------------------------------------------------------------------ #
    #  Запуск
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()

        url = f"http://{self._host()}:{self.port}/?token={self.token}"

        # Через логгер, а не print: под systemd stdout буферизуется,
        # и ссылку пришлось бы ждать в journalctl неизвестно сколько
        logger.info(
            "%s Открой в браузере, чтобы закончить установку:\n   %s\n"
            "   (ссылка одноразовая, порт лучше держать за фаерволом)",
            BRAND_EMOJI,
            url,
        )

    async def stop(self) -> None:
        if self.runner is not None:
            with contextlib.suppress(Exception):
                await self.runner.cleanup()

    @staticmethod
    def _host() -> str:
        with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]

        return "127.0.0.1"

    # ------------------------------------------------------------------ #
    #  Ожидание данных от пользователя
    # ------------------------------------------------------------------ #
    async def wait_for_credentials(self) -> typing.Any:
        self._credentials = asyncio.get_event_loop().create_future()
        return await self._credentials

    async def wait_for_login(self, credentials: typing.Any, proxy: tuple | None) -> typing.Any:
        self.auth_session = WebAuthSession(credentials, proxy)
        await self.auth_session.start()
        return await self.auth_session.done

    # ------------------------------------------------------------------ #
    #  Хендлеры
    # ------------------------------------------------------------------ #
    def _authorized(self, request: web.Request) -> bool:
        return request.cookies.get(COOKIE) == self.token or request.query.get("token") == self.token

    async def _index(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(text="403 — нужен токен из консоли", status=403)

        body = TEMPLATE.read_text(encoding="utf-8").replace("{{version}}", __version_str__)
        response = web.Response(text=body, content_type="text/html")
        response.set_cookie(COOKIE, self.token, httponly=True, samesite="Strict")
        return response

    async def _status(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.json_response({"error": "forbidden"}, status=403)

        if configuration.stored_credentials() is None:
            return web.json_response({"state": "credentials"})

        session = self.auth_session

        if session is not None and session.stage != "done":
            return web.json_response(
                {
                    "state": "login",
                    "stage": session.stage,
                    "qr": session.qr_png,
                    "error": session.error,
                }
            )

        return web.json_response({"state": "ready", **self._dashboard()})

    def _dashboard(self) -> dict:
        accounts = []

        for client in self.soika.clients:
            loader = client.loader
            accounts.append(
                {
                    "name": getattr(client.soika_me, "first_name", "?"),
                    "id": client.tg_id,
                    "modules": len(loader.modules) if loader else 0,
                    "commands": len(loader.commands) if loader else 0,
                    "prefix": client.dispatcher.prefixes[0] if client.dispatcher else ".",
                    "bot": getattr(client.inline, "bot_username", ""),
                    "module_names": sorted(str(module.name) for module in loader.modules)
                    if loader
                    else [],
                }
            )

        return {"brand": BRAND, "version": __version_str__, "accounts": accounts}

    async def _set_credentials(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.json_response({"error": "forbidden"}, status=403)

        payload = await request.json()

        try:
            credentials = configuration.store_credentials(
                payload.get("api_id"),
                payload.get("api_hash"),
            )
        except configuration.InvalidCredentials as e:
            return web.json_response({"error": str(e)}, status=400)

        if self._credentials is not None and not self._credentials.done():
            self._credentials.set_result(credentials)

        return web.json_response({"ok": True})

    async def _submit_phone(self, request: web.Request) -> web.Response:
        if not self._authorized(request) or self.auth_session is None:
            return web.json_response({"error": "forbidden"}, status=403)

        payload = await request.json()
        await self.auth_session.start_phone(str(payload.get("phone", "")).strip())
        return web.json_response({"ok": True})

    async def _submit_code(self, request: web.Request) -> web.Response:
        if not self._authorized(request) or self.auth_session is None:
            return web.json_response({"error": "forbidden"}, status=403)

        payload = await request.json()
        ok = self.auth_session.submit_code(str(payload.get("code", "")).strip())
        return web.json_response({"ok": ok})

    async def _submit_password(self, request: web.Request) -> web.Response:
        if not self._authorized(request) or self.auth_session is None:
            return web.json_response({"error": "forbidden"}, status=403)

        payload = await request.json()
        ok = self.auth_session.submit_password(str(payload.get("password", "")))
        return web.json_response({"ok": ok})

    async def _logs(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.json_response({"error": "forbidden"}, status=403)

        entries = log.memory_handler().dumps(logging.INFO)
        return web.json_response({"lines": entries[-200:]})

    async def _restart(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.json_response({"error": "forbidden"}, status=403)

        import os
        import sys

        logger.info("Перезапуск из веб-интерфейса")
        asyncio.get_event_loop().call_later(
            0.5,
            lambda: os.execl(sys.executable, sys.executable, "-m", "soika", *sys.argv[1:]),
        )
        return web.json_response({"ok": True})
