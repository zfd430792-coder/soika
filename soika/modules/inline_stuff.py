"""Управление собственным инлайн-ботом."""

import asyncio
import contextlib
import logging
import os
import tempfile

from .. import loader, utils

logger = logging.getLogger(__name__)

BOTFATHER = "@BotFather"


@loader.tds
class InlineStuffMod(loader.Module):
    """Инлайн-бот: карточка, приветствие, аватарка"""

    strings = {
        "name": "Инлайн-бот",
        "no_bot": "🚫 <b>Инлайн-бот не поднялся. Смотри</b> <code>{}logs error</code>",
        "info": (
            "🤖 <b>Инлайн-бот:</b> @{username}\n"
            "<b>ID:</b> <code>{id}</code>\n\n"
            "Через него работают кнопки, галереи, инлайн-режим и вывод ошибок.\n"
            "Удалять и блокировать его не надо."
        ),
        "greeted": "✅ <b>Отправил боту</b> <code>/start</code><b> — проверь личку с</b> @{}",
        "greet_failed": "🚫 <b>Не получилось написать боту — возможно, он заблокирован</b>",
        "no_photo": "🚫 <b>Ответь на фото, которое поставить боту на аватарку</b>",
        "pic_updating": "🪶 <b>Меняю аватарку через BotFather...</b>",
        "pic_done": "✅ <b>Аватарка бота обновлена</b>",
        "pic_failed": "🚫 <b>BotFather не принял картинку</b>",
    }

    strings_en = {
        "no_bot": "🚫 <b>Inline bot is down. Check</b> <code>{}logs error</code>",
        "info": (
            "🤖 <b>Inline bot:</b> @{username}\n"
            "<b>ID:</b> <code>{id}</code>\n\n"
            "Buttons, galleries, inline mode and tracebacks work through it."
        ),
        "greeted": "✅ <b>Sent</b> <code>/start</code> <b>to</b> @{}",
        "greet_failed": "🚫 <b>Could not message the bot — it may be blocked</b>",
        "no_photo": "🚫 <b>Reply to a photo to set it as the bot avatar</b>",
        "pic_updating": "🪶 <b>Updating avatar via BotFather...</b>",
        "pic_done": "✅ <b>Bot avatar updated</b>",
        "pic_failed": "🚫 <b>BotFather rejected the picture</b>",
    }

    def _alive(self) -> bool:
        return self.inline is not None and self.inline.init_complete

    @loader.command(alias="inlinebot")
    async def botinfocmd(self, message):
        """— карточка инлайн-бота"""
        prefix = self.client.dispatcher.prefixes[0]

        if not self._alive():
            await utils.answer(message, self.strings["no_bot"].format(prefix))
            return

        text = self.strings["info"].format(
            username=self.inline.bot_username,
            id=self.inline.bot_id,
        )
        buttons = [
            [{"text": "💬 Открыть бота", "url": f"https://t.me/{self.inline.bot_username}"}],
            [{"text": "👋 Прислать приветствие", "callback": self._greet}],
        ]

        if not await self.inline.form(text, message=message, reply_markup=buttons):
            await utils.answer(message, text)

    async def _greet(self, call):
        await self.inline.greet_owner(force=True)
        await call.answer("Приветствие отправлено в личку боту", show_alert=True)

    @loader.command()
    async def startbotcmd(self, message):
        """— заново получить приветствие от своего бота"""
        prefix = self.client.dispatcher.prefixes[0]

        if not self._alive():
            await utils.answer(message, self.strings["no_bot"].format(prefix))
            return

        if await self.inline.greet_owner(force=True):
            await utils.answer(
                message,
                self.strings["greeted"].format(self.inline.bot_username),
            )
            return

        await utils.answer(message, self.strings["greet_failed"])

    @loader.owner
    @loader.command()
    async def setbotpiccmd(self, message):
        """— сменить аватарку бота (ответом на фото)"""
        prefix = self.client.dispatcher.prefixes[0]

        if not self._alive():
            await utils.answer(message, self.strings["no_bot"].format(prefix))
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
