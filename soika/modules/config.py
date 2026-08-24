"""Редактор настроек модулей — с кнопками, прямо в чате."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/config_banner.png

import contextlib

from .. import loader, utils, validators
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
        "by_command": (
            "\n\n<i>Или из любого чата, своим сообщением:</i>\n<code>{}setcfg {} {} значение</code>"
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
        "by_command": (
            "\n\n<i>Or from any chat, as your own message:</i>\n<code>{}setcfg {} {} value</code>"
        ),
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

    async def open_module(self, call: InlineCall, module_name: str) -> None:
        """Открыть настройки модуля из чужой карточки — например из .help.

        Публичный вход в ту же панель, что рисует ``.cfg имя``: кнопка в
        справке не должна повторять её разметку у себя.
        """
        await self._open_module(call, module_name)

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

        text = self.strings["option"].format(
            utils.escape_html(str(module.name)),
            utils.escape_html(option),
            utils.escape_html(config.getdoc(option)),
            utils.escape_html(str(config[option])),
            utils.escape_html(str(config.getdef(option))),
            utils.escape_html(validator.doc["ru"] if validator else "любое значение"),
        )

        # Кнопка ввода работает не везде: в каналах и группах, где запрещены
        # инлайн-боты, она бесполезна. Поэтому рядом всегда лежит готовая
        # команда — её можно отправить своим сообщением из любого чата
        text += self.strings["by_command"].format(
            self.client.dispatcher.prefixes[0],
            utils.escape_html(str(module.name)),
            utils.escape_html(option),
        )

        await call.edit(
            text,
            reply_markup=[
                *self._value_buttons(module, module_name, option),
                [
                    {
                        "text": "♻️ Сбросить",
                        "callback": self._reset_value,
                        "args": (module_name, option),
                    },
                    {
                        "text": "⬅️ Назад",
                        "callback": self._open_module,
                        "args": (module_name,),
                    },
                    {"text": "🗑 Закрыть", "callback": self._close},
                ],
            ],
        )

    # ------------------------------------------------------------------ #
    #  Управление значением — по типу настройки
    # ------------------------------------------------------------------ #
    @staticmethod
    def _unwrap(validator):
        """Из ``Union(NoneType(), Link())`` достать то, что задаёт вид значения."""
        inner = getattr(validator, "validators", None)

        if not inner:
            return validator

        for candidate in inner:
            if not isinstance(candidate, validators.NoneType):
                return candidate

        return validator

    def _value_buttons(self, module, module_name: str, option: str) -> list[list[dict]]:
        """Кнопки под значением.

        Выключатель, выбор из списка и набор переключаются нажатием — писать
        ничего не нужно. Для остальных типов кнопка ввода: она подставляет
        запрос в поле того чата, где открыта панель, и значение уходит
        оттуда же. В личку бота ходить не надо.
        """
        validator = self._unwrap(module.config.getvalidator(option))
        current = module.config[option]

        if isinstance(validator, validators.Boolean):
            return [
                [
                    self._set_button(
                        "✅ Включено" if current else "Включить", True, module_name, option
                    ),
                    self._set_button(
                        "Выключить" if current else "🚫 Выключено", False, module_name, option
                    ),
                ]
            ]

        if isinstance(validator, validators.Choice):
            buttons = [
                self._set_button(
                    f"{'✅ ' if value == current else ''}{value}", value, module_name, option
                )
                for value in validator.possible_values
            ]
            return utils.chunks(buttons, 2)

        if isinstance(validator, validators.MultiChoice):
            chosen = list(current or [])
            buttons = [
                self._set_button(
                    f"{'✅ ' if value in chosen else '▫️ '}{value}",
                    [item for item in chosen if item != value]
                    if value in chosen
                    else [*chosen, value],
                    module_name,
                    option,
                )
                for value in validator.choice.possible_values
            ]
            return utils.chunks(buttons, 2)

        return [[self._input_button(module, module_name, option)]]

    def _set_button(self, text: str, value, module_name: str, option: str) -> dict:
        return {
            "text": text,
            "callback": self._set_value,
            "args": (module_name, option, value),
        }

    def _input_button(self, module, module_name: str, option: str) -> dict:
        return {
            "text": "✏️ Вписать значение",
            "input": f"{module.name} → {option}",
            "handler": self._apply_input,
            "args": (module_name, option),
        }

    async def _set_value(self, call: InlineCall, module_name: str, option: str, value) -> None:
        """Значение выбрано кнопкой — сохраняем и перерисовываем ту же карточку."""
        module = self.lookup(module_name)

        if module is None:
            await call.answer("Модуль пропал")
            return

        try:
            module.config[option] = value
        except ValidationError as e:
            await call.answer(str(e), show_alert=True)
            return

        self.allmodules.save_config(module)
        await self._open_option(call, module_name, option)

    async def _apply_input(self, message, value: str, module_name: str, option: str) -> str:
        """Значение вписали через кнопку ввода. Возвращаем короткий итог."""
        module = self.lookup(module_name)

        if module is None:
            return "🚫 <b>Модуль пропал</b>"

        try:
            module.config[option] = value
        except ValidationError as e:
            return self.strings["invalid"].format(utils.escape_html(str(e)))

        self.allmodules.save_config(module)

        with contextlib.suppress(Exception):
            await self._open_option(message, module_name, option)

        return self.strings["saved"].format(
            utils.escape_html(str(module.name)),
            utils.escape_html(option),
            utils.escape_html(str(module.config[option])),
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
