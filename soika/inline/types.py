"""Типы инлайн-подсистемы: кнопки, «юниты» и объекты, которые видят модули."""

from __future__ import annotations

import asyncio
import logging
import time
import typing
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Сколько живёт инлайн-сообщение, если модуль не сказал иначе
DEFAULT_TTL = 15 * 60

ButtonSpec = dict | list


class InlineError(Exception):
    """Что-то пошло не так в инлайн-подсистеме."""


class BotCreationError(InlineError):
    """Не удалось создать бота через BotFather."""


def normalize_buttons(reply_markup: typing.Any) -> list[list[dict]]:
    """Привести разметку к списку рядов кнопок.

    Понимает и одиночную кнопку, и плоский список, и готовый список рядов —
    ровно как это делает Hikka, чтобы чужие модули не переписывать.
    """
    if not reply_markup:
        return []

    if isinstance(reply_markup, dict):
        return [[reply_markup]]

    if isinstance(reply_markup, list):
        if all(isinstance(item, dict) for item in reply_markup):
            return [reply_markup]

        rows: list[list[dict]] = []

        for row in reply_markup:
            if isinstance(row, dict):
                rows.append([row])
            elif isinstance(row, list):
                rows.append([button for button in row if isinstance(button, dict)])

        return [row for row in rows if row]

    raise InlineError(f"Не понимаю разметку кнопок: {type(reply_markup)}")


def validate_button(button: dict) -> None:
    if "text" not in button:
        raise InlineError(f"У кнопки нет текста: {button}")

    if not {"url", "callback", "input", "data", "action"} & set(button):
        raise InlineError(f"Кнопка {button['text']!r} ничего не делает")


@dataclass
class InlineUnit:
    """Одно инлайн-сообщение: форма, галерея или список."""

    id: str
    kind: str
    owner: int

    text: str = ""
    photo: str | None = None
    buttons: list[list[dict]] = field(default_factory=list)

    # галерея / список
    items: list[typing.Any] = field(default_factory=list)
    index: int = 0
    next_handler: typing.Callable | None = None
    caption: str | typing.Callable = ""

    # доступ
    force_me: bool = False
    always_allow: list[int] = field(default_factory=list)
    disable_security: bool = False

    # состояние
    chat: int | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    created: float = field(default_factory=time.time)
    ttl: float = DEFAULT_TTL
    on_unload: typing.Callable | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def expired(self) -> bool:
        return time.time() - self.created > self.ttl

    def can_press(self, user_id: int) -> bool:
        if self.disable_security:
            return True

        if user_id == self.owner or user_id in self.always_allow:
            return True

        return not self.force_me and False

    def current_caption(self) -> str:
        if callable(self.caption):
            try:
                return self.caption()
            except Exception:
                logger.exception("Подпись галереи %s не собралась", self.id)
                return ""

        return str(self.caption or "")


class InlineMessage:
    """То, что модуль получает в ответ на ``inline.form()`` — умеет редактировать себя."""

    def __init__(self, manager: typing.Any, unit: InlineUnit) -> None:
        self._manager = manager
        self._unit = unit

    @property
    def unit_id(self) -> str:
        return self._unit.id

    @property
    def form(self) -> InlineUnit:
        return self._unit

    @property
    def inline_message_id(self) -> str | None:
        return self._unit.inline_message_id

    async def edit(
        self,
        text: str | None = None,
        reply_markup: typing.Any = None,
        *,
        photo: str | None = None,
        **kwargs: typing.Any,
    ) -> typing.Any:
        return await self._manager.edit_unit(
            self._unit,
            text=text,
            reply_markup=reply_markup,
            photo=photo,
            **kwargs,
        )

    async def delete(self) -> None:
        await self._manager.close_unit(self._unit)

    async def unload(self) -> None:
        await self._manager.close_unit(self._unit, delete_message=False)


class InlineCall(InlineMessage):
    """Нажатие на кнопку. Приходит в обработчики модулей вместо message."""

    def __init__(self, manager: typing.Any, unit: InlineUnit, call: typing.Any) -> None:
        super().__init__(manager, unit)
        self._call = call

    @property
    def from_user(self) -> typing.Any:
        return self._call.from_user

    @property
    def data(self) -> str:
        return self._call.data or ""

    @property
    def query(self) -> typing.Any:
        return self._call

    async def answer(
        self,
        text: str = "",
        show_alert: bool = False,
        **kwargs: typing.Any,
    ) -> None:
        await self._manager.answer_callback(self._call, text, show_alert=show_alert, **kwargs)
