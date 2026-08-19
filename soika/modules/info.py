"""Карточка юзербота: версия, аптайм, нагрузка — и баннер над ней."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/info_banner.png

import time

from .. import loader, utils
from ..version import BRAND, BRAND_EMOJI, DEFAULT_REPO, __version_str__

#: Баннер над .info по умолчанию. Годится любая ссылка на картинку, гифку или
#: mp4 — Telegram сам решит, показать это фото или анимацию.
DEFAULT_BANNER = (
    "https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/info_banner.png"
)


@loader.tds
class InfoMod(loader.Module):
    """Состояние Сойки: версия, аптайм, нагрузка"""

    strings = {
        "name": "Инфо",
        "info": (
            "{emoji} <b>{brand} {version}</b>\n\n"
            "🌟 <b>Владелец:</b> {owner}\n"
            "✍️ <b>Префикс:</b> «<code>{prefix}</code>»\n"
            "⏰ <b>Аптайм:</b> {uptime}\n"
            "🧩 <b>Модулей:</b> {modules} · <b>команд:</b> {commands}\n\n"
            "🔄 <b>Нагрузка CPU:</b> {cpu} %\n"
            "👾 <b>Нагрузка RAM:</b> {ram} МБ\n\n"
            "💾 <b>Установлен:</b> {platform}\n"
            '🕸 <b>Сборка:</b> <code>{build}</code> · <a href="{repo}">исходники</a>'
        ),
        "ping": ("🏓 <b>Задержка:</b> <code>{latency} мс</code>\n⏰ <b>Аптайм:</b> {uptime}"),
    }

    strings_en = {
        "info": (
            "{emoji} <b>{brand} {version}</b>\n\n"
            "🌟 <b>Owner:</b> {owner}\n"
            "✍️ <b>Prefix:</b> «<code>{prefix}</code>»\n"
            "⏰ <b>Uptime:</b> {uptime}\n"
            "🧩 <b>Modules:</b> {modules} · <b>commands:</b> {commands}\n\n"
            "🔄 <b>CPU usage:</b> {cpu} %\n"
            "👾 <b>RAM usage:</b> {ram} MB\n\n"
            "💾 <b>Running on:</b> {platform}\n"
            '🕸 <b>Build:</b> <code>{build}</code> · <a href="{repo}">sources</a>'
        ),
        "ping": ("🏓 <b>Ping:</b> <code>{latency} ms</code>\n⏰ <b>Uptime:</b> {uptime}"),
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "banner_url",
            DEFAULT_BANNER,
            "Баннер над .info: ссылка на картинку, гифку или mp4. Пусто — только текст",
            validator=loader.validators.Union(
                loader.validators.NoneType(),
                loader.validators.Link(),
            ),
        ),
        loader.ConfigValue(
            "custom_message",
            None,
            "Свой текст вместо стандартного. Подстановки: {owner} {version} {build}"
            " {prefix} {uptime} {cpu} {ram} {platform} {modules} {commands} {brand}"
            " {emoji} {repo}",
            validator=loader.validators.Union(
                loader.validators.NoneType(),
                loader.validators.String(),
            ),
        ),
    )

    # ------------------------------------------------------------------ #
    #  Команды
    # ------------------------------------------------------------------ #
    @loader.command(alias="soika")
    async def infocmd(self, message):
        """— карточка юзербота: версия, аптайм, нагрузка"""
        await utils.answer_with_banner(
            message,
            await self._render(),
            self.config["banner_url"],
        )

    @loader.command(alias="p")
    async def pingcmd(self, message):
        """— проверить задержку до Telegram"""
        start = time.perf_counter_ns()
        await self.client.get_me()
        latency = round((time.perf_counter_ns() - start) / 10**6, 2)

        await utils.answer(
            message,
            self.strings["ping"].format(latency=latency, uptime=utils.formatted_uptime()),
        )

    # ------------------------------------------------------------------ #
    #  Отрисовка
    # ------------------------------------------------------------------ #
    async def _render(self) -> str:
        """Собрать текст карточки — из своего шаблона, если он задан."""
        values = await self._values()
        template = self.config["custom_message"] or self.strings["info"]

        try:
            return template.format(**values)
        except (AttributeError, IndexError, KeyError, ValueError):
            # Свой шаблон с опечаткой не должен ломать .info
            return self.strings["info"].format(**values)

    async def _values(self) -> dict:
        commit, url = await utils.run_sync(utils.get_git_info)
        me = self.client.soika_me

        return {
            "emoji": BRAND_EMOJI,
            "brand": BRAND,
            "version": __version_str__,
            "owner": (
                f'<a href="{utils.get_link(me)}">'
                f"{utils.escape_html(utils.get_display_name(me))}</a>"
            ),
            "prefix": utils.escape_html(self.client.dispatcher.prefixes[0]),
            "uptime": utils.formatted_uptime(),
            "modules": len(self.allmodules.modules),
            "commands": len(self.allmodules.commands),
            "cpu": await utils.run_sync(utils.get_cpu_usage),
            "ram": utils.get_ram_usage(),
            "platform": utils.get_named_platform(),
            "build": commit[:8] if commit else "—",
            "repo": url or DEFAULT_REPO,
        }
