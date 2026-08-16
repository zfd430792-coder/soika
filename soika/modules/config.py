"""Редактор настроек модулей — с кнопками, прямо в чате."""

from .. import loader, utils
from ..inline.types import InlineCall
from ..validators import ValidationError


@loader.tds
class ConfigMod(loader.Module):
    """Просмотр и правка конфигов модулей"""

    strings = {
        "name": "Конфиг",
        "no_configs": "🪶 <b>Ни у одного модуля нет настроек</b>",
        "choose_module": "🪶 <b>Выбери модуль</b>",
        "module_header": "🪶 <b>{}</b>\n<i>Выбери настройку</i>",
        "option": (
            "🪶 <b>{}</b> → <code>{}</code>\n\n"
            "{}\n\n"
            "<b>Сейчас:</b> <code>{}</code>\n"
            "<b>По умолчанию:</b> <code>{}</code>\n"
            "<b>Формат:</b> <i>{}</i>"
        ),
        "waiting": (
            "✏️ <b>Пришли новое значение для</b> <code>{}</code> "
            "<b>в личку боту</b> @{}"
        ),
        "saved": "✅ <b>{} → {}</b> = <code>{}</code>",
        "invalid": "🚫 <b>{}</b>",
        "reset": "♻️ <b>{} → {}</b> сброшено к значению по умолчанию",
        "not_found": "🔎 <b>Модуль</b> <code>{}</code> <b>не найден или без настроек</b>",
        "usage": "🚫 <b>Как надо:</b> <code>{}setcfg модуль ключ значение</code>",
        "no_inline": "🚫 <b>Инлайн-бот недоступен, пользуйся</b> <code>{}setcfg</code>",
    }

    strings_en = {
        "no_configs": "🪶 <b>No module has settings</b>",
        "choose_module": "🪶 <b>Choose a module</b>",
        "module_header": "🪶 <b>{}</b>\n<i>Choose an option</i>",
        "option": (
            "🪶 <b>{}</b> → <code>{}</code>\n\n"
            "{}\n\n"
            "<b>Current:</b> <code>{}</code>\n"
            "<b>Default:</b> <code>{}</code>\n"
            "<b>Format:</b> <i>{}</i>"
        ),
        "waiting": "✏️ <b>Send the new value for</b> <code>{}</code> <b>to</b> @{}",
        "saved": "✅ <b>{} → {}</b> = <code>{}</code>",
        "invalid": "🚫 <b>{}</b>",
        "reset": "♻️ <b>{} → {}</b> reset to default",
        "not_found": "🔎 <b>Module</b> <code>{}</code> <b>not found or has no settings</b>",
        "usage": "🚫 <b>Usage:</b> <code>{}setcfg module key value</code>",
        "no_inline": "🚫 <b>Inline bot is unavailable, use</b> <code>{}setcfg</code>",
    }

    def _configurable(self) -> list:
        return [module for module in self.allmodules.modules if getattr(module, "config", None)]

    @loader.command(alias="cfg")
    async def configcmd(self, message):
        """[модуль] — открыть настройки модуля"""
        modules = self._configurable()

        if not modules:
            await utils.answer(message, self.strings["no_configs"])
            return

        prefix = self.client.dispatcher.prefixes[0]

        if self.inline is None or not self.inline.init_complete:
            await utils.answer(message, self.strings["no_inline"].format(prefix))
            return

        if query := utils.get_args_raw(message):
            module = self.lookup(query)

            if module is None or not getattr(module, "config", None):
                await utils.answer(message, self.strings["not_found"].format(query))
                return

            await self.inline.form(
                self.strings["module_header"].format(utils.escape_html(str(module.name))),
                message=message,
                reply_markup=self._option_buttons(module),
            )
            return

        await self.inline.form(
            self.strings["choose_module"],
            message=message,
            reply_markup=self._module_buttons(modules),
        )

    def _module_buttons(self, modules: list) -> list[list[dict]]:
        buttons = [
            {
                "text": str(module.name),
                "callback": self._open_module,
                "args": (type(module).__name__,),
            }
            for module in sorted(modules, key=lambda m: str(m.name).lower())
        ]
        rows = utils.chunks(buttons, 2)
        rows.append([{"text": "🗑 Закрыть", "callback": self._close}])
        return rows

    def _option_buttons(self, module) -> list[list[dict]]:
        buttons = [
            {
                "text": option,
                "callback": self._open_option,
                "args": (type(module).__name__, option),
            }
            for option in module.config.options
        ]
        rows = utils.chunks(buttons, 2)
        rows.append(
            [
                {"text": "⬅️ Модули", "callback": self._open_root},
                {"text": "🗑 Закрыть", "callback": self._close},
            ]
        )
        return rows

    # ------------------------------------------------------------------ #
    #  Кнопки
    # ------------------------------------------------------------------ #
    async def _open_root(self, call: InlineCall) -> None:
        await call.edit(
            self.strings["choose_module"],
            reply_markup=self._module_buttons(self._configurable()),
        )

    async def _open_module(self, call: InlineCall, module_name: str) -> None:
        module = self.lookup(module_name)

        if module is None:
            await call.answer("Модуль пропал")
            return

        await call.edit(
            self.strings["module_header"].format(utils.escape_html(str(module.name))),
            reply_markup=self._option_buttons(module),
        )

    async def _open_option(self, call: InlineCall, module_name: str, option: str) -> None:
        module = self.lookup(module_name)

        if module is None:
            await call.answer("Модуль пропал")
            return

        config = module.config
        validator = config.getvalidator(option)

        await call.edit(
            self.strings["option"].format(
                utils.escape_html(str(module.name)),
                utils.escape_html(option),
                utils.escape_html(config.getdoc(option)),
                utils.escape_html(str(config[option])),
                utils.escape_html(str(config.getdef(option))),
                utils.escape_html(validator.doc["ru"] if validator else "любое значение"),
            ),
            reply_markup=[
                [
                    {
                        "text": "✏️ Изменить",
                        "callback": self._request_value,
                        "args": (module_name, option),
                    },
                    {
                        "text": "♻️ Сбросить",
                        "callback": self._reset_value,
                        "args": (module_name, option),
                    },
                ],
                [
                    {
                        "text": "⬅️ Назад",
                        "callback": self._open_module,
                        "args": (module_name,),
                    },
                    {"text": "🗑 Закрыть", "callback": self._close},
                ],
            ],
        )

    async def _request_value(self, call: InlineCall, module_name: str, option: str) -> None:
        async def receive(bot_message) -> None:
            await self._apply(call, module_name, option, bot_message.text)

        self.inline.set_fsm_state(self.client.tg_id, {"callback": receive})

        await call.edit(
            self.strings["waiting"].format(option, self.inline.bot_username),
            reply_markup=[
                {"text": "⬅️ Отмена", "callback": self._open_option, "args": (module_name, option)}
            ],
        )

    async def _apply(self, call: InlineCall, module_name: str, option: str, value: str) -> None:
        module = self.lookup(module_name)

        if module is None:
            return

        try:
            module.config[option] = value
        except ValidationError as e:
            await call.edit(
                self.strings["invalid"].format(utils.escape_html(str(e))),
                reply_markup=[
                    {
                        "text": "⬅️ Назад",
                        "callback": self._open_option,
                        "args": (module_name, option),
                    }
                ],
            )
            return

        self.allmodules.save_config(module)

        await call.edit(
            self.strings["saved"].format(
                utils.escape_html(str(module.name)),
                utils.escape_html(option),
                utils.escape_html(str(module.config[option])),
            ),
            reply_markup=[
                {"text": "⬅️ Назад", "callback": self._open_module, "args": (module_name,)},
                {"text": "🗑 Закрыть", "callback": self._close},
            ],
        )

    async def _reset_value(self, call: InlineCall, module_name: str, option: str) -> None:
        module = self.lookup(module_name)

        if module is None:
            return

        module.config[option] = module.config.getdef(option)
        self.allmodules.save_config(module)

        await call.edit(
            self.strings["reset"].format(utils.escape_html(str(module.name)), option),
            reply_markup=[
                {"text": "⬅️ Назад", "callback": self._open_module, "args": (module_name,)},
            ],
        )

    async def _close(self, call: InlineCall) -> None:
        await call.delete()

    # ------------------------------------------------------------------ #
    #  Текстовый вариант — работает и без инлайн-бота
    # ------------------------------------------------------------------ #
    @loader.command()
    async def setcfgcmd(self, message):
        """<модуль> <ключ> <значение> — задать настройку без кнопок"""
        args = utils.get_args_raw(message).split(maxsplit=2)
        prefix = self.client.dispatcher.prefixes[0]

        if len(args) < 3:
            await utils.answer(message, self.strings["usage"].format(prefix))
            return

        module_name, option, value = args
        module = self.lookup(module_name)

        if module is None or not getattr(module, "config", None):
            await utils.answer(message, self.strings["not_found"].format(module_name))
            return

        try:
            module.config[option] = value
        except (ValidationError, KeyError) as e:
            await utils.answer(message, self.strings["invalid"].format(utils.escape_html(str(e))))
            return

        self.allmodules.save_config(module)

        await utils.answer(
            message,
            self.strings["saved"].format(
                utils.escape_html(str(module.name)),
                utils.escape_html(option),
                utils.escape_html(str(module.config[option])),
            ),
        )
