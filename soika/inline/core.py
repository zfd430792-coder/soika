"""Инлайн-менеджер: свой бот, его обработчики и мост между ним и модулями."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import typing

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InputTextMessageContent,
    LinkPreviewOptions,
)
from aiogram.types import Message as BotMessage
from telethon.tl.functions.contacts import UnblockRequest

from .. import configuration, utils
from ..version import BRAND, BRAND_EMOJI, DEFAULT_REPO, __version_str__
from . import token as token_tools
from .types import BotCreationError, InlineCall, InlineUnit, normalize_buttons
from .units import NAV_CLOSE, NAV_NEXT, NAV_NOOP, NAV_PREV, UnitsMixin

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL = 120
AVATAR = configuration.repo_root() / "assets" / "bot_pfp.png"

#: Разделы меню бота. Обработчики живут в модулях, ядро только рисует кнопки
MENU_CALLBACK = "soika:menu"
BACKUP_CALLBACK = "soika:backup"
LOGS_CALLBACK = "soika:logs"
MODULES_CALLBACK = "soika:modules"
SETTINGS_CALLBACK = "soika:settings"

#: Сколько раз пробуем перебить чужой getUpdates после перезапуска
POLLING_ATTEMPTS = 24
POLLING_RETRY = 5


class OwnerOnlyMiddleware(BaseMiddleware):
    """Пускает к боту только владельца аккаунта, остальных молча игнорирует.

    Бот служебный: он умеет менять настройки юзербота и показывать логи,
    поэтому посторонним тут делать нечего.
    """

    def __init__(self, owner_id: int) -> None:
        self.owner_id = owner_id

    async def __call__(
        self,
        handler: typing.Callable,
        event: typing.Any,
        data: dict,
    ) -> typing.Any:
        user = data.get("event_from_user")

        if user is None or user.id != self.owner_id:
            logger.debug("Бота потрогал посторонний: %s", getattr(user, "id", "?"))
            return None

        return await handler(event, data)


class InlineQueryWrapper:
    """Инлайн-запрос в виде, который ожидают модули Hikka."""

    def __init__(self, query: InlineQuery, manager: InlineManager) -> None:
        self._query = query
        self._manager = manager
        self.args = query.query.split(maxsplit=1)[1] if " " in query.query else ""

    def __getattr__(self, item: str) -> typing.Any:
        return getattr(self._query, item)

    @property
    def query(self) -> str:
        return self._query.query

    async def answer(self, results: typing.Any, **kwargs: typing.Any) -> None:
        await self._manager.answer_inline(self._query, results, **kwargs)

    #: Совместимость: в Hikka так отдают одну «ошибочную» карточку
    async def e400(self, text: str = "Неверный запрос") -> None:
        await self.answer([{"title": text, "message": f"🚫 <b>{utils.escape_html(text)}</b>"}])


class InlineManager(UnitsMixin):
    """Держит инлайн-бота, крутит его polling и раздаёт события модулям."""

    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self._client = client
        self._db = db
        self.modules: typing.Any = None

        self.bot: Bot | None = None
        self.dp: Dispatcher | None = None
        self.bot_id: int = 0
        self.bot_username: str = ""
        self.init_complete = False

        self._units: dict[str, InlineUnit] = {}
        self._fsm: dict[int, dict] = {}
        self._polling: asyncio.Task | None = None
        self._cleaner: asyncio.Task | None = None

    # ------------------------------------------------------------------ #
    #  Жизненный цикл
    # ------------------------------------------------------------------ #
    async def start(self) -> bool:
        try:
            token, username = await token_tools.get_token(self._client, self._db, avatar=AVATAR)
        except BotCreationError as e:
            logger.error("Инлайн-бот не создан: %s", e)
            return False
        except Exception:
            logger.exception("Не удалось получить токен инлайн-бота")
            return False

        self.bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))

        try:
            me = await self.bot.get_me()
        except TelegramUnauthorizedError:
            logger.error("Токен бота отозван — пересоздам при следующем запуске")
            self._db.remove("soika.inline", "bot_token")
            return False

        self.bot_id = me.id
        self.bot_username = me.username or username

        self.dp = Dispatcher()
        self._register_handlers()

        self._polling = asyncio.ensure_future(self._run_polling())
        self._cleaner = asyncio.ensure_future(self._cleanup_loop())
        self.init_complete = True

        logger.info("Инлайн-бот @%s на связи", self.bot_username)
        utils.spawn(self.greet_owner())
        utils.spawn(self.announce_restart())
        return True

    async def greet_owner(self, *, force: bool = False) -> bool:
        """Написать боту /start за пользователя, чтобы тот прислал приветствие.

        Иначе бот молчит, пока его не найдут в поиске и не нажмут «Start» —
        а так диалог с ботом появляется сам сразу после установки.
        """
        if not force and self._db.get("soika.inline", "greeted"):
            return False

        await asyncio.sleep(2)

        try:
            with contextlib.suppress(Exception):
                await self._client(UnblockRequest(self.bot_username))

            sent = await self._client.send_message(self.bot_username, "/start")
            self._db.set("soika.inline", "greeted", True)

            # Команду убираем — в диалоге остаётся только ответ бота
            await asyncio.sleep(2)

            with contextlib.suppress(Exception):
                await sent.delete()
        except Exception:
            logger.exception("Не смог поздороваться с собственным ботом")
            return False

        return True

    async def _run_polling(self) -> None:
        """Опрос бота с переживанием перезапусков.

        После ``os.execl`` предыдущий процесс не успевает закрыть свой
        ``getUpdates``, и Telegram отдаёт 409 ещё до минуты. Это не повод
        отзывать токен — просто ждём и пробуем снова.
        """
        for attempt in range(1, POLLING_ATTEMPTS + 1):
            try:
                await self.dp.start_polling(self.bot, handle_signals=False)
                return
            except TelegramConflictError:
                logger.warning(
                    "Бота опрашивает кто-то ещё (попытка %s/%s) — жду %s с",
                    attempt,
                    POLLING_ATTEMPTS,
                    POLLING_RETRY,
                )
                await asyncio.sleep(POLLING_RETRY)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Polling инлайн-бота упал, повтор через %s с", POLLING_RETRY)
                await asyncio.sleep(POLLING_RETRY)

        logger.error(
            "Бот так и не смог начать опрос. Если он запущен где-то ещё — "
            "останови тот процесс, иначе перевыпусти токен: .revokebot"
        )

    async def stop(self) -> None:
        self.init_complete = False

        for task in (self._polling, self._cleaner):
            if task and not task.done():
                task.cancel()

        if self.dp is not None:
            with contextlib.suppress(Exception):
                await self.dp.stop_polling()

        if self.bot is not None:
            with contextlib.suppress(Exception):
                await self.bot.session.close()

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)

            for unit in [unit for unit in self._units.values() if unit.expired]:
                await self.close_unit(unit, delete_message=False)

    # ------------------------------------------------------------------ #
    #  Обработчики бота
    # ------------------------------------------------------------------ #
    def _register_handlers(self) -> None:
        self.dp.update.outer_middleware(OwnerOnlyMiddleware(self._client.tg_id))
        self.dp.inline_query.register(self._on_inline_query)
        self.dp.chosen_inline_result.register(self._on_chosen_result)
        self.dp.callback_query.register(self._on_callback)
        self.dp.message.register(self._on_start, CommandStart())
        self.dp.message.register(self._on_message)

    async def _on_inline_query(self, query: InlineQuery) -> None:
        text = (query.query or "").strip()

        if unit := self._units.get(text):
            if query.from_user.id != unit.owner:
                await query.answer([], cache_time=0, is_personal=True)
                return

            await query.answer(
                [self._render_unit(unit)],
                cache_time=0,
                is_personal=True,
            )
            return

        if await self._route_inline_handler(query, text):
            return

        await query.answer([self._about_card()], cache_time=0, is_personal=True)

    async def _route_inline_handler(self, query: InlineQuery, text: str) -> bool:
        if self.modules is None or not text:
            return False

        name = text.split(maxsplit=1)[0].lower()
        handler = self.modules.inline_handlers.get(name)

        if handler is None:
            return False

        if query.from_user.id != self._client.tg_id and not getattr(
            handler, "inline_everyone", False
        ):
            await query.answer([], cache_time=0, is_personal=True)
            return True

        try:
            await handler(InlineQueryWrapper(query, self))
        except Exception:
            logger.exception("Инлайн-обработчик %s упал", name)

        return True

    async def _on_chosen_result(self, chosen: ChosenInlineResult) -> None:
        unit = self._units.get(chosen.result_id) or self._units.get((chosen.query or "").strip())

        if unit is None:
            return

        unit.inline_message_id = chosen.inline_message_id
        unit.ready.set()

    async def _on_callback(self, call: CallbackQuery) -> None:
        data = call.data or ""
        unit_id, _, rest = data.partition(":")
        unit = self._units.get(unit_id)

        if unit is None:
            await self._route_raw_callback(call)
            return

        if not unit.can_press(call.from_user.id):
            await call.answer("🚫 Это не твоя кнопка", show_alert=True)
            return

        if rest == NAV_NOOP:
            await call.answer()
            return

        if rest == NAV_CLOSE:
            await call.answer()
            await self.close_unit(unit)
            return

        if rest in (NAV_NEXT, NAV_PREV):
            await call.answer()
            await self.navigate(unit, 1 if rest == NAV_NEXT else -1)
            return

        await self._invoke_button(call, unit, rest)

    async def _invoke_button(self, call: CallbackQuery, unit: InlineUnit, rest: str) -> None:
        try:
            row, column = (int(part) for part in rest.split(":"))
            button = unit.buttons[row][column]
        except (ValueError, IndexError):
            await call.answer("Кнопка устарела", show_alert=True)
            return

        callback = button.get("callback")

        if callback is None:
            await call.answer()
            return

        args = button.get("args", ())
        kwargs = button.get("kwargs", {})
        inline_call = InlineCall(self, unit, call)

        try:
            await callback(inline_call, *args, **kwargs)
        except Exception:
            logger.exception("Обработчик кнопки «%s» упал", button.get("text"))
        finally:
            # Если модуль ничего не ответил — гасим «часики» на кнопке сами
            if not inline_call.answered:
                with contextlib.suppress(Exception):
                    await call.answer()

    async def _route_raw_callback(self, call: CallbackQuery) -> None:
        """Кнопки с произвольным ``data`` уходят во все callback-обработчики модулей."""
        if self.modules is None:
            return

        unit = InlineUnit(id=utils.rand(10), kind="raw", owner=self._client.tg_id)
        unit.inline_message_id = call.inline_message_id

        # Кнопка нажата под обычным сообщением бота — запомним адрес,
        # иначе call.edit() не будет знать, что редактировать
        if call.message is not None:
            unit.bot_chat = call.message.chat.id
            unit.bot_message = call.message.message_id

        # Регистрируем юнит: если обработчик перерисует сообщение своими
        # кнопками-колбэками, они должны продолжать работать
        self._units[unit.id] = unit

        inline_call = InlineCall(self, unit, call)

        for handler in list(self.modules.callback_handlers.values()):
            with contextlib.suppress(Exception):
                await handler(inline_call)

        if not inline_call.answered:
            with contextlib.suppress(Exception):
                await call.answer()

    # ------------------------------------------------------------------ #
    #  Личка бота
    # ------------------------------------------------------------------ #
    async def _on_start(self, message: BotMessage) -> None:
        await self.send_pm_unit(message.chat.id, self.menu_text(), self.menu_markup())

    async def announce_restart(self) -> None:
        """Отмечаемся в личке при каждом запуске — видно, что бот поднялся."""
        await asyncio.sleep(6)

        # На самом первом запуске приветствие пришлёт greet_owner
        if not self._db.get("soika.inline", "greeted"):
            return

        with contextlib.suppress(Exception):
            await self.send_pm_unit(
                self._client.tg_id,
                f"{BRAND_EMOJI} <b>{BRAND} перезапущена и на связи</b>\n\n"
                f"{self.menu_text(header=False)}",
                self.menu_markup(),
            )

    def menu_text(self, *, header: bool = True) -> str:
        """Тело меню бота: кто, сколько модулей, как звать."""
        prefix = self._db.get("soika.settings", "prefixes", ["."])[0]
        owner = utils.get_display_name(self._client.soika_me)

        modules = len(self.modules.modules) if self.modules else 0
        commands = len(self.modules.commands) if self.modules else 0

        title = (
            f"{BRAND_EMOJI} <b>{BRAND} {__version_str__}</b>\n"
            "<i>твой личный бот юзербота — кнопки, галереи, инлайн, логи</i>\n\n"
            if header
            else ""
        )

        return (
            f"{title}"
            f"<b>Аккаунт:</b> {utils.escape_html(owner)}\n"
            f"<b>Модулей:</b> {modules} · <b>команд:</b> {commands}\n"
            f"<b>Префикс:</b> <code>{prefix}</code> · <b>аптайм:</b> "
            f"<code>{utils.formatted_uptime()}</code>\n"
            f"<b>Инлайн:</b> <code>@{self.bot_username}</code> в любом чате\n\n"
            "<i>Выбирай раздел кнопками ниже.</i>"
        )

    def menu_markup(self) -> list[list[dict]]:
        """Главное меню. Разделы обрабатывают модули по callback_data."""
        return [
            [
                {"text": "📚 Команды", "input": ""},
                {"text": "🗄 Бэкап", "data": BACKUP_CALLBACK},
            ],
            [
                {"text": "📜 Логи", "data": LOGS_CALLBACK},
                {"text": "🧩 Модули", "data": MODULES_CALLBACK},
            ],
            [{"text": "⚙️ Настройки", "data": SETTINGS_CALLBACK}],
            [{"text": "🌐 Исходники", "url": DEFAULT_REPO}],
        ]

    async def _on_message(self, message: BotMessage) -> None:
        """Ввод текста в ЛС бота — используется редактором конфигов."""
        state = self._fsm.get(message.from_user.id)

        if not state:
            return

        callback = state.get("callback")
        self._fsm.pop(message.from_user.id, None)

        if callback is None:
            return

        with contextlib.suppress(Exception):
            await callback(message)

    def set_fsm_state(self, user_id: int, state: dict | None) -> None:
        if state:
            self._fsm[user_id] = state
        else:
            self._fsm.pop(user_id, None)

    def get_fsm_state(self, user_id: int) -> dict | None:
        return self._fsm.get(user_id)

    # ------------------------------------------------------------------ #
    #  Отрисовка инлайн-результатов
    # ------------------------------------------------------------------ #
    def _render_unit(self, unit: InlineUnit) -> typing.Any:
        markup = self.build_markup(unit)
        text = self.unit_text(unit)
        photo = self.unit_photo(unit)

        if photo:
            return InlineQueryResultPhoto(
                id=unit.id,
                photo_url=photo,
                thumbnail_url=photo,
                caption=text[:1024],
                parse_mode="HTML",
                reply_markup=markup,
            )

        return InlineQueryResultArticle(
            id=unit.id,
            title=BRAND,
            description=utils.remove_html(text)[:100],
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            ),
            reply_markup=markup,
        )

    def _about_card(self) -> InlineQueryResultArticle:
        return InlineQueryResultArticle(
            id=utils.rand(10),
            title=f"{BRAND_EMOJI} {BRAND}",
            description="Инлайн-бот юзербота. Напиши название инлайн-команды.",
            input_message_content=InputTextMessageContent(
                message_text=f"{BRAND_EMOJI} <b>{BRAND}</b> — модульный юзербот",
                parse_mode="HTML",
            ),
        )

    async def answer_inline(
        self,
        query: InlineQuery,
        results: typing.Any,
        **kwargs: typing.Any,
    ) -> None:
        """Ответ на инлайн-запрос: принимает и объекты aiogram, и словари Hikka."""
        prepared = []

        for item in results if isinstance(results, (list, tuple)) else [results]:
            prepared.append(self._to_result(item) if isinstance(item, dict) else item)

        kwargs.setdefault("cache_time", 0)
        kwargs.setdefault("is_personal", True)

        with contextlib.suppress(Exception):
            await query.answer(prepared, **kwargs)

    def _to_result(self, item: dict) -> typing.Any:
        markup = self.build_markup(
            InlineUnit(
                id=utils.rand(10),
                kind="raw",
                owner=self._client.tg_id,
                buttons=normalize_buttons(item.get("reply_markup")),
            )
        )

        if photo := item.get("photo"):
            return InlineQueryResultPhoto(
                id=utils.rand(10),
                photo_url=photo,
                thumbnail_url=item.get("thumb", photo),
                caption=item.get("caption", item.get("message", ""))[:1024],
                parse_mode="HTML",
                reply_markup=markup,
            )

        return InlineQueryResultArticle(
            id=utils.rand(10),
            title=item.get("title", BRAND),
            description=item.get("description", ""),
            thumbnail_url=item.get("thumb"),
            input_message_content=InputTextMessageContent(
                message_text=item.get("message", item.get("title", "")),
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            ),
            reply_markup=markup,
        )

    async def answer_callback(
        self,
        call: CallbackQuery,
        text: str = "",
        *,
        show_alert: bool = False,
        **kwargs: typing.Any,
    ) -> None:
        with contextlib.suppress(Exception):
            await call.answer(text, show_alert=show_alert, **kwargs)

    # ------------------------------------------------------------------ #
    #  Показ ошибок
    # ------------------------------------------------------------------ #
    async def send_traceback(
        self,
        message: typing.Any,
        command: str,
        short: str,
        full: str,
    ) -> None:
        """Инлайн-лог: короткая ошибка + кнопка с полным трейсбеком."""
        if not getattr(message, "out", False):
            return

        async def show_full(call: InlineCall) -> None:
            await call.edit(
                f"🚫 <b>Команда</b> <code>{utils.escape_html(command)}</code>\n\n"
                f"<pre><code>{utils.escape_html(full[-3500:])}</code></pre>",
                reply_markup=[{"text": "🗑 Закрыть", "callback": close}],
            )

        async def close(call: InlineCall) -> None:
            await call.delete()

        await self.form(
            f"🚫 <b>Команда</b> <code>{utils.escape_html(command)}</code> <b>упала</b>\n"
            f"<code>{utils.escape_html(short)}</code>",
            message=message,
            reply_markup=[
                {"text": "📋 Трейсбек", "callback": show_full},
                {"text": "🗑 Закрыть", "callback": close},
            ],
        )
