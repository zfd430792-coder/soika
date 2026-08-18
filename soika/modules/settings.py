"""Настройки юзербота: префикс, алиасы, язык, сообщение при запуске."""

from .. import loader, utils

SETTINGS = "soika.settings"
CORE = "soika.core"


@loader.tds
class SettingsMod(loader.Module):
    """Префикс, алиасы команд и язык интерфейса"""

    strings = {
        "name": "Настройки",
        "prefix_set": "✅ <b>Префикс изменён на</b> <code>{}</code>\n<i>Пример:</i> <code>{}help</code>",
        "prefix_current": "🪶 <b>Текущий префикс:</b> <code>{}</code>",
        "prefix_bad": "🚫 <b>Префикс должен быть от 1 до 3 символов</b>",
        "alias_created": "✅ <b>Алиас</b> <code>{}</code> → <code>{}</code>",
        "alias_removed": "✅ <b>Алиас</b> <code>{}</code> <b>удалён</b>",
        "alias_missing": "🚫 <b>Алиаса</b> <code>{}</code> <b>нет</b>",
        "alias_usage": "🚫 <b>Как надо:</b> <code>{}addalias алиас команда</code>",
        "no_command": "🚫 <b>Команды</b> <code>{}</code> <b>не существует</b>",
        "aliases": "🪶 <b>Алиасы:</b>\n\n{}",
        "no_aliases": "🪶 <b>Алиасов нет</b>",
        "lang_set": "✅ <b>Язык интерфейса:</b> {}",
        "lang_unknown": "🚫 <b>Доступные языки:</b> {}",
        "startup_off": "✅ <b>Сообщение при запуске выключено</b>",
    }

    strings_en = {
        "prefix_set": "✅ <b>Prefix changed to</b> <code>{}</code>\n<i>Example:</i> <code>{}help</code>",
        "prefix_current": "🪶 <b>Current prefix:</b> <code>{}</code>",
        "prefix_bad": "🚫 <b>Prefix must be 1 to 3 characters</b>",
        "alias_created": "✅ <b>Alias</b> <code>{}</code> → <code>{}</code>",
        "alias_removed": "✅ <b>Alias</b> <code>{}</code> <b>removed</b>",
        "alias_missing": "🚫 <b>No alias</b> <code>{}</code>",
        "alias_usage": "🚫 <b>Usage:</b> <code>{}addalias alias command</code>",
        "no_command": "🚫 <b>Command</b> <code>{}</code> <b>does not exist</b>",
        "aliases": "🪶 <b>Aliases:</b>\n\n{}",
        "no_aliases": "🪶 <b>No aliases</b>",
        "lang_set": "✅ <b>Interface language:</b> {}",
        "lang_unknown": "🚫 <b>Available languages:</b> {}",
        "startup_off": "✅ <b>Startup message disabled</b>",
    }

    @loader.command()
    async def prefixcmd(self, message):
        """[новый префикс] — посмотреть или сменить префикс команд"""
        args = utils.get_args_raw(message)
        dispatcher = self.client.dispatcher

        if not args:
            await utils.answer(
                message,
                self.strings["prefix_current"].format(dispatcher.prefixes[0]),
            )
            return

        if len(args) > 3:
            await utils.answer(message, self.strings["prefix_bad"])
            return

        dispatcher.set_prefixes([args])
        await utils.answer(message, self.strings["prefix_set"].format(args, args))

    @loader.command()
    async def addaliascmd(self, message):
        """<алиас> <команда> — добавить сокращение для команды"""
        args = utils.get_args(message)
        prefix = self.client.dispatcher.prefixes[0]

        if len(args) != 2:
            await utils.answer(message, self.strings["alias_usage"].format(prefix))
            return

        alias, command = args[0].lower(), args[1].lower()

        if command not in self.allmodules.commands:
            await utils.answer(message, self.strings["no_command"].format(command))
            return

        aliases = self.db.pointer(SETTINGS, "aliases", {}, item_type=dict)
        aliases[alias] = command
        self.allmodules.aliases[alias] = command

        await utils.answer(message, self.strings["alias_created"].format(alias, command))

    @loader.command()
    async def delaliascmd(self, message):
        """<алиас> — удалить сокращение"""
        alias = utils.get_args_raw(message).lower()
        aliases = self.db.pointer(SETTINGS, "aliases", {}, item_type=dict)

        if alias not in aliases:
            await utils.answer(message, self.strings["alias_missing"].format(alias))
            return

        aliases.pop(alias)
        self.allmodules.aliases.pop(alias, None)

        await utils.answer(message, self.strings["alias_removed"].format(alias))

    @loader.command()
    async def aliasescmd(self, message):
        """— список алиасов"""
        aliases = self.db.get(SETTINGS, "aliases", {})

        if not aliases:
            await utils.answer(message, self.strings["no_aliases"])
            return

        listing = "\n".join(
            f"▫️ <code>{alias}</code> → <code>{command}</code>"
            for alias, command in sorted(aliases.items())
        )
        await utils.answer(message, self.strings["aliases"].format(listing))

    @loader.command()
    async def langcmd(self, message):
        """<ru|en> — язык интерфейса"""
        lang = utils.get_args_raw(message).lower()
        translator = self.client.translator

        if lang not in translator.available:
            await utils.answer(
                message,
                self.strings["lang_unknown"].format(", ".join(translator.available)),
            )
            return

        translator.set_lang(lang)
        await utils.answer(message, self.strings["lang_set"].format(lang))
