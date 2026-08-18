"""Информация о юзерботе и скорость отклика."""

import time

from .. import loader, utils
from ..version import BRAND, BRAND_EMOJI, __version_str__


@loader.tds
class InfoMod(loader.Module):
    """Состояние Сойки: версия, аптайм, ресурсы"""

    strings = {
        "name": "Инфо",
        "info": (
            "{emoji} <b>{brand} {version}</b>\n\n"
            "<b>Аккаунт:</b> {account}\n"
            "<b>Аптайм:</b> <code>{uptime}</code>\n"
            "<b>Модулей:</b> {modules} · <b>команд:</b> {commands}\n"
            "<b>Префикс:</b> <code>{prefix}</code>\n"
            "<b>Платформа:</b> {platform}\n"
            "<b>Память:</b> {ram} МБ\n"
            "{build}"
        ),
        "build": "<b>Сборка:</b> <code>{}</code>\n",
        "ping": "🏓 <b>Задержка:</b> <code>{} мс</code>\n<b>Аптайм:</b> <code>{}</code>",
    }

    strings_en = {
        "info": (
            "{emoji} <b>{brand} {version}</b>\n\n"
            "<b>Account:</b> {account}\n"
            "<b>Uptime:</b> <code>{uptime}</code>\n"
            "<b>Modules:</b> {modules} · <b>commands:</b> {commands}\n"
            "<b>Prefix:</b> <code>{prefix}</code>\n"
            "<b>Platform:</b> {platform}\n"
            "<b>RAM:</b> {ram} MB\n"
            "{build}"
        ),
        "build": "<b>Build:</b> <code>{}</code>\n",
        "ping": "🏓 <b>Ping:</b> <code>{} ms</code>\n<b>Uptime:</b> <code>{}</code>",
    }

    @loader.command(alias="soika")
    async def infocmd(self, message):
        """— информация о юзерботе"""
        commit, _ = utils.get_git_info()

        text = self.strings["info"].format(
            emoji=BRAND_EMOJI,
            brand=BRAND,
            version=__version_str__,
            account=utils.escape_html(utils.get_display_name(self.client.soika_me)),
            uptime=utils.formatted_uptime(),
            modules=len(self.allmodules.modules),
            commands=len(self.allmodules.commands),
            prefix=self.client.dispatcher.prefixes[0],
            platform=utils.get_named_platform(),
            ram=utils.get_ram_usage(),
            build=self.strings["build"].format(commit[:8]) if commit else "",
        )

        await utils.answer(message, text)

    @loader.command(alias="p")
    async def pingcmd(self, message):
        """— проверить задержку до Telegram"""
        start = time.perf_counter_ns()
        await self.client.get_me()
        latency = round((time.perf_counter_ns() - start) / 10**6, 2)

        await utils.answer(
            message,
            self.strings["ping"].format(latency, utils.formatted_uptime()),
        )
