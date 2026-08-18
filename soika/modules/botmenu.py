"""Меню бота: разделы «Логи», «Модули» и «Настройки» кнопками в личке."""

from .. import channels, loader, utils
from ..inline.core import LOGS_CALLBACK, MENU_CALLBACK, MODULES_CALLBACK, SETTINGS_CALLBACK

SETTINGS = "soika.settings"
CORE = "soika.core"


@loader.tds
class BotMenuMod(loader.Module):
    """Разделы меню внутри бота"""

    strings = {
        "name": "Меню бота",
        "logs": (
            "📜 <b>Логи</b>\n\n"
            "<b>Канал:</b> {channel}\n"
            "<b>Уровень:</b> <code>{level}</code>\n"
            "<b>Отправка:</b> раз в {interval} с\n\n"
            "<i>Файлом в чат:</i> <code>{prefix}logs error</code>"
        ),
        "logs_on": "включён",
        "logs_off": "выключен",
        "modules": "🧩 <b>Модулей: {count}</b> · <b>команд: {commands}</b>\n\n{listing}",
        "settings": (
            "⚙️ <b>Настройки</b>\n\n"
            "<b>Префикс:</b> <code>{prefix}</code>\n"
            "<b>Язык:</b> <code>{lang}</code>\n"
            "<b>Сообщение при запуске:</b> {startup}\n\n"
            "<i>Настройки модулей:</i> <code>{prefix}cfg</code>"
        ),
        "on": "включено",
        "off": "выключено",
        "back": "⬅️ Назад",
        "no_module": "🚫 Модуль {} не загружен",
    }

    strings_en = {
        "logs": (
            "📜 <b>Logs</b>\n\n"
            "<b>Channel:</b> {channel}\n"
            "<b>Level:</b> <code>{level}</code>\n"
            "<b>Flush:</b> every {interval} s\n\n"
            "<i>As a file:</i> <code>{prefix}logs error</code>"
        ),
        "logs_on": "on",
        "logs_off": "off",
        "modules": "🧩 <b>Modules: {count}</b> · <b>commands: {commands}</b>\n\n{listing}",
        "settings": (
            "⚙️ <b>Settings</b>\n\n"
            "<b>Prefix:</b> <code>{prefix}</code>\n"
            "<b>Language:</b> <code>{lang}</code>\n"
            "<b>Startup message:</b> {startup}\n\n"
            "<i>Module settings:</i> <code>{prefix}cfg</code>"
        ),
        "on": "on",
        "off": "off",
        "back": "⬅️ Back",
        "no_module": "🚫 Module {} is not loaded",
    }

    @property
    def prefix(self) -> str:
        return self.client.dispatcher.prefixes[0]

    def _back_row(self) -> list[dict]:
        return [{"text": self.strings["back"], "callback": self._menu}]

    # ------------------------------------------------------------------ #
    #  Точки входа из меню
    # ------------------------------------------------------------------ #
    @loader.callback_handler()
    async def menu_callback_handler(self, call):
        """Разделы меню бота"""
        routes = {
            MENU_CALLBACK: self._menu,
            LOGS_CALLBACK: self._logs,
            MODULES_CALLBACK: self._modules,
            SETTINGS_CALLBACK: self._settings,
        }

        if handler := routes.get(call.data):
            await call.answer()
            await handler(call)

    async def _menu(self, call) -> None:
        await call.edit(self.inline.menu_text(), reply_markup=self.inline.menu_markup())

    # ------------------------------------------------------------------ #
    #  Логи
    # ------------------------------------------------------------------ #
    async def _logs(self, call) -> None:
        logs = self.lookup("Логи")

        if logs is None:
            await call.answer(self.strings["no_module"].format("Логи"), show_alert=True)
            return

        enabled = logs.config["channel"]
        channel_text = self.strings["logs_on"] if enabled else self.strings["logs_off"]
        buttons = [
            [
                {
                    "text": "🔕 Выключить канал" if enabled else "🔔 Включить канал",
                    "callback": self._toggle_logs,
                }
            ]
        ]

        if enabled:
            channel = await logs._ensure_channel()

            if channel is not None:
                link = await channels.channel_link(self.client, channel)
                channel_text = f'<a href="{link}">soika-logs</a>'
                buttons.append([{"text": "📜 Открыть канал", "url": link}])

        buttons.append(self._back_row())

        await call.edit(
            self.strings["logs"].format(
                channel=channel_text,
                level=logs.config["level"],
                interval=logs.config["interval"],
                prefix=self.prefix,
            ),
            reply_markup=buttons,
        )

    async def _toggle_logs(self, call) -> None:
        logs = self.lookup("Логи")

        if logs is None:
            return

        logs.config["channel"] = not logs.config["channel"]
        self.allmodules.save_config(logs)
        await self._logs(call)

    # ------------------------------------------------------------------ #
    #  Модули
    # ------------------------------------------------------------------ #
    async def _modules(self, call) -> None:
        modules = sorted(self.allmodules.modules, key=lambda module: str(module.name).lower())
        listing = ""

        for module in modules:
            line = f"▫️ <b>{utils.escape_html(str(module.name))}</b>: " + (
                ", ".join(sorted(module.commands)) or "—"
            )

            if len(listing) + len(line) > 3000:
                listing += "…"
                break

            listing += line + "\n"

        await call.edit(
            self.strings["modules"].format(
                count=len(modules),
                commands=len(self.allmodules.commands),
                listing=listing,
            ),
            reply_markup=[self._back_row()],
        )

    # ------------------------------------------------------------------ #
    #  Настройки
    # ------------------------------------------------------------------ #
    async def _settings(self, call) -> None:
        startup_off = bool(self.db.get(CORE, "no_startup_message"))
        lang = self.client.translator.lang

        await call.edit(
            self.strings["settings"].format(
                prefix=self.prefix,
                lang=lang,
                startup=self.strings["off"] if startup_off else self.strings["on"],
            ),
            reply_markup=[
                [
                    {
                        "text": "🇬🇧 English" if lang == "ru" else "🇷🇺 Русский",
                        "callback": self._toggle_lang,
                    },
                    {
                        "text": "🔕 Не писать при запуске"
                        if not startup_off
                        else "🔔 Писать при запуске",
                        "callback": self._toggle_startup,
                    },
                ],
                self._back_row(),
            ],
        )

    async def _toggle_lang(self, call) -> None:
        self.client.translator.set_lang("en" if self.client.translator.lang == "ru" else "ru")
        await self._settings(call)

    async def _toggle_startup(self, call) -> None:
        self.db.set(CORE, "no_startup_message", not self.db.get(CORE, "no_startup_message"))
        await self._settings(call)

    # ------------------------------------------------------------------ #
    #  Команда для вызова меню из чата
    # ------------------------------------------------------------------ #
    @loader.command(alias="menu")
    async def botmenucmd(self, message):
        """— открыть меню бота в его личке"""
        if self.inline is None or not self.inline.init_complete:
            await utils.answer(message, self.strings["no_module"].format("Инлайн-бот"))
            return

        await self.inline.send_pm_unit(
            self.client.tg_id,
            self.inline.menu_text(),
            self.inline.menu_markup(),
        )
        await utils.answer(
            message,
            f"🪶 <b>Меню открыто в личке</b> @{self.inline.bot_username}",
        )
