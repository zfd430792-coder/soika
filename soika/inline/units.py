"""Инлайн-сообщения: формы с кнопками, галереи и списки.

Работает это так: юзербот отправляет собственному боту инлайн-запрос с id юнита,
бот отвечает готовым сообщением, юзербот «нажимает» на результат — и в чате
появляется сообщение от имени бота, которое потом можно редактировать.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import typing

from .. import utils
from .types import (
    DEFAULT_TTL,
    InlineError,
    InlineMessage,
    InlineUnit,
    normalize_buttons,
    validate_button,
)

logger = logging.getLogger(__name__)

NAV_CLOSE = "@close"
NAV_NEXT = "@next"
NAV_PREV = "@prev"
NAV_NOOP = "@noop"


class UnitsMixin:
    """Публичный API инлайна для модулей: ``form``, ``gallery``, ``list``."""

    # Эти атрибуты приходят из InlineManager
    bot: typing.Any
    bot_username: str
    init_complete: bool
    _client: typing.Any
    _units: dict[str, InlineUnit]

    # ------------------------------------------------------------------ #
    #  Формы
    # ------------------------------------------------------------------ #
    async def form(
        self,
        text: str,
        message: typing.Any = None,
        reply_markup: typing.Any = None,
        *,
        photo: str | None = None,
        ttl: float = DEFAULT_TTL,
        force_me: bool = False,
        always_allow: list[int] | None = None,
        disable_security: bool = False,
        silent: bool = False,
        on_unload: typing.Callable | None = None,
        **kwargs: typing.Any,
    ) -> InlineMessage | bool:
        """Отправить сообщение от имени бота с кнопками."""
        if not self.init_complete:
            return False

        buttons = normalize_buttons(reply_markup)

        for row in buttons:
            for button in row:
                validate_button(button)

        unit = InlineUnit(
            id=utils.rand(10),
            kind="form",
            owner=self._client.tg_id,
            text=text,
            photo=photo,
            buttons=buttons,
            ttl=ttl,
            force_me=force_me,
            always_allow=list(always_allow or []),
            disable_security=disable_security,
            on_unload=on_unload,
        )

        return await self._send_unit(unit, message, silent=silent)

    # ------------------------------------------------------------------ #
    #  Галереи
    # ------------------------------------------------------------------ #
    async def gallery(
        self,
        message: typing.Any = None,
        next_handler: typing.Any = None,
        caption: str | typing.Callable = "",
        *,
        custom_buttons: typing.Any = None,
        ttl: float = DEFAULT_TTL,
        force_me: bool = False,
        always_allow: list[int] | None = None,
        silent: bool = False,
        on_unload: typing.Callable | None = None,
        **kwargs: typing.Any,
    ) -> InlineMessage | bool:
        """Листаемая галерея фотографий.

        ``next_handler`` — либо готовый список ссылок, либо функция, которая
        отдаёт следующую ссылку (можно async).
        """
        if not self.init_complete:
            return False

        items: list[str] = []
        handler: typing.Callable | None = None

        if isinstance(next_handler, (list, tuple)):
            items = list(next_handler)
        elif callable(next_handler):
            handler = next_handler
        else:
            raise InlineError("Галерее нужен список ссылок или функция-поставщик")

        unit = InlineUnit(
            id=utils.rand(10),
            kind="gallery",
            owner=self._client.tg_id,
            items=items,
            next_handler=handler,
            caption=caption,
            buttons=normalize_buttons(custom_buttons),
            ttl=ttl,
            force_me=force_me,
            always_allow=list(always_allow or []),
            on_unload=on_unload,
        )

        if not unit.items and handler is not None:
            await self._load_more(unit)

        if not unit.items:
            raise InlineError("Галерея пустая — нечего показывать")

        return await self._send_unit(unit, message, silent=silent)

    async def _load_more(self, unit: InlineUnit) -> bool:
        if unit.next_handler is None:
            return False

        try:
            result = await utils.maybe_await(unit.next_handler())
        except Exception:
            logger.exception("Поставщик галереи %s упал", unit.id)
            return False

        if not result:
            return False

        new_items = list(result) if isinstance(result, (list, tuple)) else [result]
        unit.items.extend(new_items)
        return bool(new_items)

    # ------------------------------------------------------------------ #
    #  Списки
    # ------------------------------------------------------------------ #
    async def list(
        self,
        message: typing.Any = None,
        strings: list[str] | None = None,
        *,
        ttl: float = DEFAULT_TTL,
        force_me: bool = False,
        always_allow: list[int] | None = None,
        custom_buttons: typing.Any = None,
        silent: bool = False,
        **kwargs: typing.Any,
    ) -> InlineMessage | bool:
        """Постраничный текст: удобно для длинных выводов вроде ``.help``."""
        if not self.init_complete:
            return False

        if not strings:
            raise InlineError("Списку нужны страницы")

        unit = InlineUnit(
            id=utils.rand(10),
            kind="list",
            owner=self._client.tg_id,
            items=list(strings),
            buttons=normalize_buttons(custom_buttons),
            ttl=ttl,
            force_me=force_me,
            always_allow=list(always_allow or []),
        )

        return await self._send_unit(unit, message, silent=silent)

    # ------------------------------------------------------------------ #
    #  Отправка и редактирование
    # ------------------------------------------------------------------ #
    def unit_text(self, unit: InlineUnit) -> str:
        if unit.kind == "list":
            return str(unit.items[unit.index])

        if unit.kind == "gallery":
            return unit.current_caption()

        return unit.text

    def unit_photo(self, unit: InlineUnit) -> str | None:
        if unit.kind == "gallery" and unit.items:
            return str(unit.items[unit.index])

        return unit.photo

    def build_markup(self, unit: InlineUnit) -> typing.Any:
        """Собрать клавиатуру: сначала кнопки модуля, потом навигация."""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        rows: list[list[typing.Any]] = []

        for row_index, row in enumerate(unit.buttons):
            line = []

            for column, button in enumerate(row):
                if url := button.get("url"):
                    line.append(InlineKeyboardButton(text=button["text"], url=url))
                elif (query := button.get("input")) is not None:
                    line.append(
                        InlineKeyboardButton(
                            text=button["text"],
                            switch_inline_query_current_chat=str(query),
                        )
                    )
                elif data := button.get("data"):
                    line.append(
                        InlineKeyboardButton(text=button["text"], callback_data=str(data)[:64])
                    )
                else:
                    line.append(
                        InlineKeyboardButton(
                            text=button["text"],
                            callback_data=f"{unit.id}:{row_index}:{column}",
                        )
                    )

            if line:
                rows.append(line)

        if unit.kind in {"gallery", "list"}:
            total = len(unit.items)
            rows.append(
                [
                    InlineKeyboardButton(text="⬅️", callback_data=f"{unit.id}:{NAV_PREV}"),
                    InlineKeyboardButton(
                        text=f"{unit.index + 1}/{total}",
                        callback_data=f"{unit.id}:{NAV_NOOP}",
                    ),
                    InlineKeyboardButton(text="➡️", callback_data=f"{unit.id}:{NAV_NEXT}"),
                ]
            )
            rows.append(
                [InlineKeyboardButton(text="🗑", callback_data=f"{unit.id}:{NAV_CLOSE}")]
            )

        if not rows:
            return None

        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _send_unit(
        self,
        unit: InlineUnit,
        message: typing.Any,
        *,
        silent: bool = False,
    ) -> InlineMessage | bool:
        self._units[unit.id] = unit

        try:
            results = await self._client.inline_query(self.bot_username, unit.id)
        except Exception as e:  # noqa: BLE001
            logger.error("Инлайн-запрос к собственному боту не прошёл: %s", e)
            self._units.pop(unit.id, None)
            return False

        if not results:
            self._units.pop(unit.id, None)
            return False

        peer = getattr(message, "peer_id", None) or "me"
        reply_to = getattr(message, "reply_to_msg_id", None)

        try:
            sent = await results[0].click(
                peer,
                reply_to=reply_to,
                silent=silent,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Не удалось отправить инлайн-сообщение: %s", e)
            self._units.pop(unit.id, None)
            return False

        unit.chat = getattr(sent, "chat_id", None)
        unit.message_id = getattr(sent, "id", None)

        if message is not None and getattr(message, "out", False):
            with contextlib.suppress(Exception):
                await message.delete()

        # Ждём chosen_inline_result — без него нельзя редактировать сообщение
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(unit.ready.wait(), timeout=5)

        return InlineMessage(self, unit)

    async def edit_unit(
        self,
        unit: InlineUnit,
        *,
        text: str | None = None,
        reply_markup: typing.Any = None,
        photo: str | None = None,
        **kwargs: typing.Any,
    ) -> bool:
        """Перерисовать инлайн-сообщение."""
        if text is not None:
            unit.text = text

        if photo is not None:
            unit.photo = photo

        if reply_markup is not None:
            unit.buttons = normalize_buttons(reply_markup)

        return await self.refresh_unit(unit)

    async def send_pm_unit(
        self,
        chat_id: int,
        text: str,
        reply_markup: typing.Any = None,
        *,
        ttl: float = DEFAULT_TTL,
        on_unload: typing.Callable | None = None,
    ) -> InlineMessage | bool:
        """Сообщение с кнопками прямо в личку бота (без инлайн-запроса)."""
        if not self.init_complete:
            return False

        unit = InlineUnit(
            id=utils.rand(10),
            kind="form",
            owner=self._client.tg_id,
            text=text,
            buttons=normalize_buttons(reply_markup),
            ttl=ttl,
            on_unload=on_unload,
        )
        self._units[unit.id] = unit

        try:
            sent = await self.bot.send_message(
                chat_id,
                text,
                parse_mode="HTML",
                reply_markup=self.build_markup(unit),
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Не смог написать в личку бота: %s", e)
            self._units.pop(unit.id, None)
            return False

        unit.bot_chat = sent.chat.id
        unit.bot_message = sent.message_id
        return InlineMessage(self, unit)

    async def refresh_unit(self, unit: InlineUnit) -> bool:
        from aiogram.types import InputMediaPhoto

        markup = self.build_markup(unit)
        body = self.unit_text(unit)
        picture = self.unit_photo(unit)

        # Сообщение живёт либо как инлайн-результат, либо как обычное
        # сообщение бота в личке — редактируются они по-разному
        address = (
            {"inline_message_id": unit.inline_message_id}
            if unit.inline_message_id
            else {"chat_id": unit.bot_chat, "message_id": unit.bot_message}
        )

        if not any(address.values()):
            return False

        try:
            if picture:
                await self.bot.edit_message_media(
                    media=InputMediaPhoto(media=picture, caption=body[:1024], parse_mode="HTML"),
                    reply_markup=markup,
                    **address,
                )
            else:
                await self.bot.edit_message_text(
                    text=body,
                    parse_mode="HTML",
                    reply_markup=markup,
                    **address,
                )
        except Exception as e:  # noqa: BLE001 — «message is not modified» и т. п.
            logger.debug("Не смог обновить инлайн-сообщение %s: %s", unit.id, e)
            return False

        return True

    async def close_unit(self, unit: InlineUnit, *, delete_message: bool = True) -> None:
        """Убрать юнит: снять обработчики и (по желанию) удалить сообщение."""
        if unit.on_unload is not None:
            with contextlib.suppress(Exception):
                await utils.maybe_await(unit.on_unload())

        self._units.pop(unit.id, None)

        if not delete_message:
            return

        if unit.bot_chat and unit.bot_message:
            with contextlib.suppress(Exception):
                await self.bot.delete_message(unit.bot_chat, unit.bot_message)
                return

        if unit.chat and unit.message_id:
            with contextlib.suppress(Exception):
                await self._client.delete_messages(unit.chat, [unit.message_id])
                return

        with contextlib.suppress(Exception):
            await self.bot.edit_message_text(
                inline_message_id=unit.inline_message_id,
                text="🗑 <i>Закрыто</i>",
                parse_mode="HTML",
            )

    # ------------------------------------------------------------------ #
    #  Навигация
    # ------------------------------------------------------------------ #
    async def navigate(self, unit: InlineUnit, step: int) -> None:
        if not unit.items:
            return

        target = unit.index + step

        if target >= len(unit.items):
            if unit.kind == "gallery" and await self._load_more(unit):
                target = min(target, len(unit.items) - 1)
            else:
                target = 0
        elif target < 0:
            target = len(unit.items) - 1

        unit.index = target
        await self.refresh_unit(unit)
