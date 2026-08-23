"""Справка по модулям и командам."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/help_banner.png

from .. import loader, utils


@loader.tds
class HelpMod(loader.Module):
    """Показывает список модулей и справку по командам"""

    strings = {
        "name": "Справка",
        "not_found": "🔎 <b>Модуль</b> <code>{}</code> <b>не найден</b>",
        "module": "🪶 <b>{}</b>\n{}\n\n{}",
        "no_docs": "<i>Описания нет</i>",
        "no_commands": "<i>Команд у модуля нет</i>",
        "header": "🪶 <b>Системных: {}</b> · <b>установленных: {}</b>\n\n",
        "no_user": (
            "\n<i>Своих модулей нет.</i> <code>{0}ml имя</code> <i>— из каталога,</i> "
            "<code>{0}dlmod ссылка</code> <i>— по ссылке</i>"
        ),
        "hint": "\n<i>Подробнее по модулю:</i> <code>{}help имя</code>",
        "developer": "\n<b>Автор:</b> {}",
        "hidden": "🙈 <b>Модуль</b> <b>{}</b> <b>скрыт из списка</b>",
        "shown": "👁 <b>Модуль</b> <b>{}</b> <b>снова в списке</b>",
        "hidden_count": "\n<i>Скрыто модулей: {}</i>",
    }

    strings_en = {
        "not_found": "🔎 <b>Module</b> <code>{}</code> <b>not found</b>",
        "no_docs": "<i>No description</i>",
        "no_commands": "<i>Module has no commands</i>",
        "header": "🪶 <b>Built-in: {}</b> · <b>installed: {}</b>\n\n",
        "no_user": (
            "\n<i>Nothing installed yet.</i> <code>{0}ml name</code> <i>— from the catalog,</i> "
            "<code>{0}dlmod link</code> <i>— by link</i>"
        ),
        "hint": "\n<i>Details:</i> <code>{}help name</code>",
        "developer": "\n<b>Developer:</b> {}",
        "hidden": "🙈 <b>Module</b> <b>{}</b> <b>hidden from the list</b>",
        "shown": "👁 <b>Module</b> <b>{}</b> <b>is back in the list</b>",
        "hidden_count": "\n<i>Hidden modules: {}</i>",
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "core_emoji",
            "◾️",
            "Маркер системного модуля в списке .help",
            validator=loader.validators.Emoji(),
        ),
        loader.ConfigValue(
            "user_emoji",
            "◽️",
            "Маркер установленного модуля в списке .help",
            validator=loader.validators.Emoji(),
        ),
    )

    @property
    def prefix(self) -> str:
        return self.client.dispatcher.prefixes[0]

    @loader.command(alias="h")
    async def helpcmd(self, message):
        """[модуль] — список модулей или справка по конкретному модулю"""
        query = utils.get_args_raw(message)

        if query:
            return await self._module_help(message, query)

        return await self._all_modules(message)

    async def _module_help(self, message, query: str) -> None:
        module = self.lookup(query)

        if module is None:
            await utils.answer(message, self.strings["not_found"].format(utils.escape_html(query)))
            return

        lines = []

        for command in sorted(module.commands):
            doc = module.get_command_doc(command) or ""
            lines.append(f"▫️ <code>{self.prefix}{command}</code> {utils.escape_html(doc)}".strip())

        body = "\n".join(lines) if lines else self.strings["no_commands"]
        description = utils.escape_html(module.get_module_doc()) or self.strings["no_docs"]

        text = self.strings["module"].format(
            utils.escape_html(str(module.name)),
            description,
            body,
        )

        if developer := getattr(module, "__meta__", {}).get("developer"):
            text += self.strings["developer"].format(utils.escape_html(developer))

        await utils.answer_with_banner(message, text, utils.get_banner(module))

    @loader.owner
    @loader.command()
    async def helphidecmd(self, message):
        """<модуль> — спрятать модуль из общего списка .help"""
        module = self.lookup(utils.get_args_raw(message).strip())

        if module is None:
            await utils.answer(
                message,
                self.strings["not_found"].format(utils.escape_html(utils.get_args_raw(message))),
            )
            return

        hidden = self.db.pointer("soika.settings", "hidden_modules", [], item_type=list)
        name = type(module).__name__

        if name in hidden:
            hidden.remove(name)
            await utils.answer(message, self.strings["shown"].format(module.name))
            return

        hidden.append(name)
        await utils.answer(message, self.strings["hidden"].format(module.name))

    async def _all_modules(self, message) -> None:
        hidden = self.db.get("soika.settings", "hidden_modules", []) or []
        modules = sorted(
            (module for module in self.allmodules.modules if type(module).__name__ not in hidden),
            key=lambda module: str(module.name).lower(),
        )

        # Свои модули отделены от встроенных: так видно, что ты ставил сам,
        # а что приехало с Сойкой и обновляется вместе с ней
        core = [module for module in modules if self.allmodules.is_builtin(module)]
        user = [module for module in modules if module not in core]

        # Заголовков у разделов нет: счёт стоит в шапке, а к какой группе
        # относится модуль, видно по маркеру — тёмный у системных, светлый
        # у своих. Системные идут первыми
        lines = [self._line(module, self.config["core_emoji"]) for module in core]
        lines += [self._line(module, self.config["user_emoji"]) for module in user]

        if not user:
            lines.append(self.strings["no_user"].format(self.prefix))

        header = self.strings["header"].format(len(core), len(user))
        footer = self.strings["hint"].format(self.prefix)

        if hidden:
            footer += self.strings["hidden_count"].format(len(hidden))

        pages = self._paginate(lines, header, footer)

        inline_ready = self.inline is not None and self.inline.init_complete

        if len(pages) > 1 and inline_ready and await self.inline.list(message, pages):
            return

        await utils.answer(message, pages[0])

    def _line(self, module, marker: str) -> str:
        """Строка модуля в общем списке — только имя.

        Команды сюда не влезают: у модулей вроде Настроек их больше десятка,
        строка переносится и список выглядит рваным. За подробностями —
        ``.help имя``, там и описание, и что делает каждая команда.

        Имя в ``<code>``, чтобы ткнуть и сразу вставить его в ``.help``.
        """
        return f"{marker} <code>{utils.escape_html(str(module.name))}</code>"

    @staticmethod
    def _paginate(lines: list[str], header: str, footer: str, limit: int = 3500) -> list[str]:
        pages: list[str] = []
        current = ""

        for line in lines:
            if len(current) + len(line) > limit:
                pages.append(header + current + footer)
                current = ""

            current += line + "\n"

        pages.append(header + current + footer)
        return pages
