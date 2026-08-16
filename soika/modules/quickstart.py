"""Приветствие после первой установки."""

import asyncio
import logging

from .. import loader, utils
from ..inline.types import InlineCall
from ..version import BRAND, BRAND_EMOJI, __version_str__

logger = logging.getLogger(__name__)


@loader.tds
class QuickstartMod(loader.Module):
    """Здоровается один раз после установки и помогает начать"""

    strings = {
        "name": "Первый запуск",
        "welcome": (
            "{emoji} <b>{brand} {version} установлена!</b>\n\n"
            "Я — модульный юзербот: команды пишутся прямо в чатах Telegram "
            "с префиксом <code>{prefix}</code>.\n\n"
            "<b>С чего начать:</b>\n"
            "▫️ <code>{prefix}help</code> — что я умею\n"
            "▫️ <code>{prefix}dlmod ссылка</code> — поставить чужой модуль\n"
            "▫️ <code>{prefix}cfg</code> — настройки модулей\n"
            "▫️ <code>{prefix}prefix !</code> — сменить префикс\n\n"
            "Инлайн-бот {bot} создан автоматически — через него работают кнопки.\n\n"
            "<b>Важно:</b> юзербот — это твой аккаунт. Не давай доступ "
            "<code>{prefix}sudo</code> кому попало."
        ),
        "lang_changed": "✅ <b>Язык переключён на английский</b>",
        "closed": "🪶 <b>Хорошей работы!</b>",
    }

    strings_en = {
        "welcome": (
            "{emoji} <b>{brand} {version} is installed!</b>\n\n"
            "I'm a modular userbot: type commands in any Telegram chat "
            "with the <code>{prefix}</code> prefix.\n\n"
            "<b>Where to start:</b>\n"
            "▫️ <code>{prefix}help</code> — what I can do\n"
            "▫️ <code>{prefix}dlmod link</code> — install a third-party module\n"
            "▫️ <code>{prefix}cfg</code> — module settings\n"
            "▫️ <code>{prefix}prefix !</code> — change the prefix\n\n"
            "The inline bot {bot} was created automatically — buttons work through it.\n\n"
            "<b>Important:</b> a userbot runs on your own account. Don't hand out "
            "<code>{prefix}sudo</code> to strangers."
        ),
        "lang_changed": "✅ <b>Язык переключён на русский</b>",
        "closed": "🪶 <b>Have a good one!</b>",
    }

    async def client_ready(self, client, db):
        if self.get("greeted"):
            return

        self.set("greeted", True)
        utils.spawn(self._greet())

    async def _greet(self) -> None:
        await asyncio.sleep(4)

        prefix = self.client.dispatcher.prefixes[0]
        bot = f"@{self.inline.bot_username}" if self.inline and self.inline.bot_username else "—"

        text = self.strings["welcome"].format(
            emoji=BRAND_EMOJI,
            brand=BRAND,
            version=__version_str__,
            prefix=prefix,
            bot=bot,
        )

        buttons = [
            [{"text": "📚 Помощь", "callback": self._help}],
            [
                {"text": "🇬🇧 English", "callback": self._switch_lang, "args": ("en",)},
                {"text": "🇷🇺 Русский", "callback": self._switch_lang, "args": ("ru",)},
            ],
            [{"text": "🗑 Закрыть", "callback": self._close}],
        ]

        try:
            if self.inline is not None and self.inline.init_complete:
                await self.inline.form(text, message=None, reply_markup=buttons)
                return

            await self.client.send_message("me", text)
        except Exception:
            logger.exception("Приветствие не отправилось")

    async def _help(self, call: InlineCall) -> None:
        module = self.lookup("Справка")

        if module is None:
            await call.answer("Модуль справки не найден")
            return

        prefix = self.client.dispatcher.prefixes[0]
        await call.edit(
            f"🪶 <b>Пиши</b> <code>{prefix}help</code> <b>в любом чате</b>",
            reply_markup=[{"text": "🗑 Закрыть", "callback": self._close}],
        )

    async def _switch_lang(self, call: InlineCall, lang: str) -> None:
        self.client.translator.set_lang(lang)
        await call.edit(
            self.strings["lang_changed"],
            reply_markup=[{"text": "🗑 Закрыть", "callback": self._close}],
        )

    async def _close(self, call: InlineCall) -> None:
        await call.delete()
