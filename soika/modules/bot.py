"""Собственный бот Сойки: меню в личке и управление ботом."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/bot_banner.png

import asyncio
import contextlib
import logging
import os
import tempfile

from .. import loader, utils
from ..inline.core import LANG_CALLBACK, MENU_CALLBACK, SETTINGS_CALLBACK

logger = logging.getLogger(__name__)

BOTFATHER = "@BotFather"


@loader.tds
class BotMod(loader.Module):
    """Меню бота и управление им: аватарка, приветствие, токен"""

    strings = {
        "name": "Бот",
        "no_bot": "🚫 <b>Инлайн-бот не поднялся. Смотри</b> <code>{}logs error</code>",
        "menu_opened": "🪶 <b>Меню открыто в личке</b> @{}",
        "info": (
            "🤖 <b>Инлайн-бот:</b> @{username}\n"
            "<b>ID:</b> <code>{id}</code>\n\n"
            "Через него работают кнопки, галереи, инлайн-режим и вывод ошибок.\n"
            "Отвечает только тебе — посторонние для него не существуют."
        ),
        "greeted": "✅ <b>Приветствие отправлено в личку</b> @{}",
        "greet_failed": "🚫 <b>Не получилось написать боту — возможно, он заблокирован</b>",
        "no_photo": "🚫 <b>Ответь на фото, которое поставить боту на аватарку</b>",
        "pic_updating": "🪶 <b>Меняю аватарку через BotFather...</b>",
        "pic_done": "✅ <b>Аватарка бота обновлена</b>",
        "pic_failed": "🚫 <b>BotFather не принял картинку</b>",
        "revoking": "🪶 <b>Перевыпускаю токен через BotFather...</b>",
        "revoked": "✅ <b>Токен перевыпущен, бот перезапущен</b>",
        "revoke_failed": "🚫 <b>BotFather не отдал новый токен</b>",
        "settings": (
            "⚙️ <b>Настройки</b>\n\n"
            "<b>Префикс:</b> <code>{prefix}</code>\n"
            "<b>Язык:</b> <code>{lang}</code>\n"
            "<b>Автообновление:</b> {auto}\n\n"
            "<i>Настройки модулей:</i> <code>{prefix}cfg</code>"
        ),
        "on": "включено",
        "off": "выключено",
        "back": "⬅️ Назад",
        "missing": "🚫 Модуль {} не загружен",
        "web_off": "🚫 <b>Веб-панель не поднята</b>\n<i>Запусти Сойку с</i> <code>--web</code>",
        "web_url": "🌐 <b>Веб-панель:</b> {}\n<i>Ссылка одноразовая, никому её не показывай.</i>",
    }

    strings_en = {
        "no_bot": "🚫 <b>Inline bot is down. Check</b> <code>{}logs error</code>",
        "menu_opened": "🪶 <b>Menu opened in</b> @{}",
        "info": (
            "🤖 <b>Inline bot:</b> @{username}\n"
            "<b>ID:</b> <code>{id}</code>\n\n"
            "Buttons, galleries, inline mode and tracebacks work through it.\n"
            "It answers you only — strangers do not exist for it."
        ),
        "greeted": "✅ <b>Welcome sent to</b> @{}",
        "greet_failed": "🚫 <b>Could not message the bot — it may be blocked</b>",
        "no_photo": "🚫 <b>Reply to a photo to set it as the bot avatar</b>",
        "pic_updating": "🪶 <b>Updating avatar via BotFather...</b>",
        "pic_done": "✅ <b>Bot avatar updated</b>",
        "pic_failed": "🚫 <b>BotFather rejected the picture</b>",
        "revoking": "🪶 <b>Revoking the token via BotFather...</b>",
        "revoked": "✅ <b>Token revoked, bot restarted</b>",
        "revoke_failed": "🚫 <b>BotFather did not return a new token</b>",
        "settings": (
            "⚙️ <b>Settings</b>\n\n"
            "<b>Prefix:</b> <code>{prefix}</code>\n"
            "<b>Language:</b> <code>{lang}</code>\n"
            "<b>Auto update:</b> {auto}\n\n"
            "<i>Module settings:</i> <code>{prefix}cfg</code>"
        ),
        "on": "on",
        "off": "off",
        "back": "⬅️ Back",
        "missing": "🚫 Module {} is not loaded",
        "web_off": "🚫 <b>Web panel is not running</b>\n<i>Start Soika with</i> <code>--web</code>",
        "web_url": "🌐 <b>Web panel:</b> {}\n<i>The link is single-use, do not share it.</i>",
    }

    @property
    def prefix(self) -> str:
        return self.client.dispatcher.prefixes[0]

    def _alive(self) -> bool:
        return self.inline is not None and self.inline.init_complete

    def _back_row(self) -> list[dict]:
        return [{"text": self.strings["back"], "callback": self._menu}]

    # ------------------------------------------------------------------ #
    #  Разделы меню
    # ------------------------------------------------------------------ #
    @loader.callback_handler()
    async def menu_callback_handler(self, call):
        """Разделы меню бота"""
        if call.data.startswith(LANG_CALLBACK):
            await self._switch_lang(call, call.data[len(LANG_CALLBACK) :])
            return

        routes = {
            MENU_CALLBACK: self._menu,
            SETTINGS_CALLBACK: self._settings,
        }

        if handler := routes.get(call.data):
            await call.answer()
            await handler(call)

    async def _menu(self, call) -> None:
        await call.edit(self.inline.menu_text(), reply_markup=self.inline.menu_markup())

    async def _switch_lang(self, call, lang: str) -> None:
        translator = self.client.translator

        if lang not in translator.available:
            await call.answer(self.strings["missing"].format(lang), show_alert=True)
            return

        translator.set_lang(lang)
        await call.answer(translator.gettext("lang_switched"))
        await call.edit(
            self.inline.welcome_text(),
            reply_markup=self.inline.welcome_markup(),
        )

    async def _settings(self, call) -> None:
        updater = self.lookup("Обновление")
        auto = bool(updater and updater.config["auto_update"])

        await call.edit(
            self.strings["settings"].format(
                prefix=self.prefix,
                lang=self.client.translator.lang,
                auto=self.strings["on"] if auto else self.strings["off"],
            ),
            reply_markup=[
                [
                    {
                        "text": "🇬🇧 English" if self.client.translator.lang == "ru" else "🇷🇺 Русский",
                        "callback": self._toggle_lang,
                    },
                    {
                        "text": "✋ Обновлять вручную" if auto else "🤖 Обновлять само",
                        "callback": self._toggle_autoupdate,
                    },
                ],
                self._back_row(),
            ],
        )

    async def _toggle_lang(self, call) -> None:
        translator = self.client.translator
        translator.set_lang("en" if translator.lang == "ru" else "ru")
        await self._settings(call)

    async def _toggle_autoupdate(self, call) -> None:
        updater = self.lookup("Обновление")

        if updater is None:
            await call.answer(self.strings["missing"].format("Обновление"), show_alert=True)
            return

        updater.config["auto_update"] = not updater.config["auto_update"]
        self.allmodules.save_config(updater)
        await self._settings(call)

    # ------------------------------------------------------------------ #
    #  Команды
    # ------------------------------------------------------------------ #
    @loader.command(alias="menu")
    async def botmenucmd(self, message):
        """— открыть меню бота в его личке"""
        if not self._alive():
            await utils.answer(message, self.strings["no_bot"].format(self.prefix))
            return

        await self.inline.send_pm_unit(
            self.client.tg_id,
            self.inline.menu_text(),
            self.inline.menu_markup(),
        )
        await utils.answer(
            message,
            self.strings["menu_opened"].format(self.inline.bot_username),
        )

    @loader.owner
    @loader.command()
    async def weburlcmd(self, message):
        """— ссылка на веб-панель, если она поднята"""
        app = getattr(self.client, "soika", None)

        if app is None:
            await utils.answer(message, self.strings["web_off"])
            return

        # Панель обычно не поднята — поднимаем на время, как это делает Hikka
        web = await app.open_web()
        url = getattr(web, "url", "")

        if not url:
            await utils.answer(message, self.strings["web_off"])
            return

        await utils.answer(message, self.strings["web_url"].format(url))

    @loader.command(alias="inlinebot")
    async def botinfocmd(self, message):
        """— карточка инлайн-бота"""
        if not self._alive():
            await utils.answer(message, self.strings["no_bot"].format(self.prefix))
            return

        text = self.strings["info"].format(
            username=self.inline.bot_username,
            id=self.inline.bot_id,
        )
        buttons = [
            [{"text": "💬 Открыть бота", "url": f"https://t.me/{self.inline.bot_username}"}],
            [{"text": "👋 Прислать приветствие", "callback": self._resend_welcome}],
        ]

        if not await self.inline.form(text, message=message, reply_markup=buttons):
            await utils.answer(message, text)

    async def _resend_welcome(self, call) -> None:
        await self.inline.send_welcome(self.client.tg_id)
        await call.answer(self.strings["greeted"].format(self.inline.bot_username))

    @loader.command()
    async def startbotcmd(self, message):
        """— заново получить приветствие от своего бота"""
        if not self._alive():
            await utils.answer(message, self.strings["no_bot"].format(self.prefix))
            return

        try:
            await self.inline.send_welcome(self.client.tg_id)
        except Exception:
            logger.exception("Приветствие не отправилось")
            await utils.answer(message, self.strings["greet_failed"])
            return

        await utils.answer(
            message,
            self.strings["greeted"].format(self.inline.bot_username),
        )

    @loader.owner
    @loader.command()
    async def setbotpiccmd(self, message):
        """— сменить аватарку бота (ответом на фото)"""
        if not self._alive():
            await utils.answer(message, self.strings["no_bot"].format(self.prefix))
            return

        reply = await message.get_reply_message()

        if not reply or not reply.photo:
            await utils.answer(message, self.strings["no_photo"])
            return

        message = await utils.answer(message, self.strings["pic_updating"])
        path = os.path.join(tempfile.gettempdir(), f"soika-pic-{utils.rand(6)}.jpg")

        try:
            await reply.download_media(path)
            await self._push_avatar(path)
        except Exception:
            logger.exception("Смена аватарки бота не удалась")
            await utils.answer(message, self.strings["pic_failed"])
            return
        finally:
            with contextlib.suppress(OSError):
                os.remove(path)

        await utils.answer(message, self.strings["pic_done"])

    @loader.owner
    @loader.command()
    async def revokebotcmd(self, message):
        """— перевыпустить токен бота (если он застрял или утёк)"""
        from ..inline import token as token_tools

        message = await utils.answer(message, self.strings["revoking"])
        new_token = await token_tools.revoke_token(self.client, self.db)

        if not new_token:
            await utils.answer(message, self.strings["revoke_failed"])
            return

        # Живой Bot держит старый токен — поднимаем подсистему заново
        await self.inline.stop()
        await self.inline.start()

        await utils.answer(message, self.strings["revoked"])

    async def _push_avatar(self, path: str) -> None:
        async with self.client.conversation(BOTFATHER, timeout=40, exclusive=False) as conv:
            for step in ("/setuserpic", f"@{self.inline.bot_username}"):
                await conv.send_message(step)

                with contextlib.suppress(asyncio.TimeoutError):
                    await conv.get_response()

            await conv.send_file(path)

            with contextlib.suppress(asyncio.TimeoutError):
                await conv.get_response()

        with contextlib.suppress(Exception):
            await self.client.send_read_acknowledge(BOTFATHER)
