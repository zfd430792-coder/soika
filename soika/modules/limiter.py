"""Защита от FLOOD_WAIT: считает запросы к Telegram и тормозит сам.

Диспетчер ловит ``FloodWaitError`` уже постфактум — когда Telegram выдал
запрет и осталось только ждать. Этот модуль работает до: считает запросы
в скользящем окне и, если пошёл вразнос, замирает на полминуты сам.
Свой маленький простой вместо чужого большого.
"""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/limiter_banner.png

import contextlib
import io
import json
import logging
import time

from .. import loader, utils

logger = logging.getLogger(__name__)

#: Считаем только то, чем можно нашуметь на бан. Служебные запросы вроде
#: получения апдейтов сюда не входят — иначе счётчик врал бы постоянно
WATCHED = {"messages", "account", "channels"}


@loader.tds
class LimiterMod(loader.Module):
    """Не даёт юзерботу нашуметь и словить FLOOD_WAIT"""

    strings = {
        "name": "Лимитер",
        "tripped": (
            "🛑 <b>Слишком много запросов к Telegram</b>\n\n"
            "<b>За последние {sample} с:</b> {count} <i>(порог {threshold})</i>\n"
            "<b>Замер на:</b> {freeze} с\n\n"
            "<i>Скорее всего виноват модуль с циклом. В файле — что именно "
            "вызывалось, по нему видно кто.</i>"
        ),
        "status_on": (
            "🛡 <b>Защита включена</b>\n\n"
            "<b>Окно:</b> {sample} с\n"
            "<b>Порог:</b> {threshold} запросов\n"
            "<b>Простой:</b> {freeze} с\n\n"
            "<i>Пороги — в</i> <code>{prefix}cfg</code> <i>→ Лимитер</i>"
        ),
        "status_off": (
            "🔓 <b>Защита выключена</b>\n\n"
            "<i>Юзербот шумит без оглядки. Включить —</i> <code>{prefix}apilimit</code>"
        ),
        "suspended": "⏸ <b>Защита спит {} с</b>",
        "bad_time": "🚫 <b>Сколько секунд не считать? Например</b> <code>{}apilimitoff 300</code>",
    }

    strings_en = {
        "suspended": "⏸ <b>Protection paused for {} s</b>",
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "enabled",
            False,
            "Тормозить юзербот, когда запросов слишком много",
            validator=loader.validators.Boolean(),
        ),
        loader.ConfigValue(
            "sample",
            15,
            "Окно замера, секунд",
            validator=loader.validators.Integer(minimum=1, maximum=600),
        ),
        loader.ConfigValue(
            "threshold",
            100,
            "Сколько запросов в окне считать перебором",
            validator=loader.validators.Integer(minimum=10, maximum=10000),
        ),
        loader.ConfigValue(
            "freeze",
            30,
            "На сколько секунд замереть, секунд",
            validator=loader.validators.Integer(minimum=5, maximum=3600),
        ),
        loader.ConfigValue(
            "report",
            True,
            "Присылать в бота файл с тем, что именно вызывалось",
            validator=loader.validators.Boolean(),
        ),
    )

    def __init__(self) -> None:
        #: (имя запроса, когда) за последнее окно
        self._calls: list[tuple[str, float]] = []
        #: До какой метки времени не считаем — ручная пауза
        self._asleep_until = 0.0
        #: Оригинальный метод клиента, чтобы вернуть его при выгрузке
        self._original = None
        self._patched_instance = False
        self._frozen = False

    async def client_ready(self, client, db) -> None:
        self._install()

    async def on_unload(self) -> None:
        self._restore()

    # ------------------------------------------------------------------ #
    #  Команды
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command(alias="apilimiter")
    async def apilimitcmd(self, message):
        """— включить или выключить защиту от FLOOD_WAIT"""
        self.config["enabled"] = not self.config["enabled"]
        self.allmodules.save_config(self)
        self._calls.clear()

        await utils.answer(message, self._status())

    @loader.owner
    @loader.command()
    async def apilimitoffcmd(self, message):
        """<секунды> — не считать запросы указанное время"""
        args = utils.get_args_raw(message).strip()

        if not args.isdigit():
            await utils.answer(message, self.strings["bad_time"].format(self.prefix))
            return

        self._asleep_until = time.time() + int(args)
        await utils.answer(message, self.strings["suspended"].format(args))

    @property
    def prefix(self) -> str:
        return self.client.dispatcher.prefixes[0]

    def _status(self) -> str:
        if not self.config["enabled"]:
            return self.strings["status_off"].format(prefix=self.prefix)

        return self.strings["status_on"].format(
            sample=self.config["sample"],
            threshold=self.config["threshold"],
            freeze=self.config["freeze"],
            prefix=self.prefix,
        )

    # ------------------------------------------------------------------ #
    #  Перехват запросов
    # ------------------------------------------------------------------ #
    def _install(self) -> None:
        """Подменить у клиента отправку запросов на свою обёртку."""
        if self._original is not None:
            return

        self._original = self.client._call
        #: Был ли ``_call`` собственным атрибутом объекта до нас — от этого
        #: зависит, как снимать патч, чтобы не оставить лишнего
        self._patched_instance = "_call" in vars(self.client)

        async def counted(sender, request, *args, **kwargs):
            await self._count(request)
            return await self._original(sender, request, *args, **kwargs)

        self.client._call = counted

    def _restore(self) -> None:
        if self._original is None:
            return

        if self._patched_instance:
            self.client._call = self._original
        else:
            # Метод пришёл от класса — свой атрибут надо убрать целиком,
            # иначе на объекте навсегда останется наша копия
            with contextlib.suppress(AttributeError):
                del self.client._call

        self._original = None

    async def _count(self, request) -> None:
        """Записать запрос и, если пошёл вразнос, притормозить."""
        if not self.config["enabled"] or self._frozen or time.time() < self._asleep_until:
            return

        now = time.time()
        sample = int(self.config["sample"])
        self._calls = [call for call in self._calls if now - call[1] < sample]

        for item in request if isinstance(request, (list, tuple)) else (request,):
            if getattr(item, "__module__", "").rsplit(".", 1)[-1] in WATCHED:
                self._calls.append((type(item).__name__, now))

        if len(self._calls) > int(self.config["threshold"]):
            await self._freeze()

    async def _freeze(self) -> None:
        count, freeze = len(self._calls), int(self.config["freeze"])
        logger.warning("Слишком много запросов к Telegram (%s), замираю на %s c.", count, freeze)

        calls = list(self._calls)
        self._calls.clear()
        self._frozen = True

        # Сообщаем до простоя, а не после: иначе владелец узнал бы о
        # заморозке через полминуты после того, как она кончилась
        with contextlib.suppress(Exception):
            await self._tell(count, freeze, calls)

        # Именно блокирующий sleep: asyncio.sleep отпустил бы остальные
        # задачи, и они продолжили бы шуметь ровно тогда, когда не надо
        time.sleep(freeze)
        self._frozen = False

    async def _tell(self, count: int, freeze: int, calls: list) -> None:
        """Рассказать владельцу, что произошло, и приложить список вызовов."""
        text = self.strings["tripped"].format(
            sample=self.config["sample"],
            count=count,
            threshold=self.config["threshold"],
            freeze=freeze,
        )

        if not self.config["report"]:
            await self._notify(text)
            return

        report = io.BytesIO(json.dumps(calls, indent=2, ensure_ascii=False).encode())
        report.name = "flood_report.json"

        if self.inline is not None and self.inline.init_complete:
            try:
                await self.inline.bot.send_document(self.client.tg_id, report, caption=text)
                return
            except Exception:  # noqa: BLE001 — бот мог не подняться
                report.seek(0)

        await self.client.send_file("me", report, caption=text)

    async def _notify(self, text: str) -> None:
        if self.inline is not None and self.inline.init_complete:
            with contextlib.suppress(Exception):
                await self.inline.send_pm_unit(self.client.tg_id, text)
                return

        await self.client.send_message("me", text)
