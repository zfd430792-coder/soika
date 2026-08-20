"""Настройки юзербота: префикс, алиасы, язык, сообщение при запуске."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/settings_banner.png

from .. import loader, utils
from ..dispatcher import (
    BLACKLIST_CHATS,
    BLACKLIST_USERS,
    DISABLED_WATCHERS,
)

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
        "no_target": "🚫 <b>Ответь на сообщение человека или укажи его ID</b>",
        "muted": "🔇 <b>Сойка молчит в этом чате</b>",
        "unmuted": "🔊 <b>Сойка снова слушает этот чат</b>",
        "muted_chat": "🔇 <b>Чат</b> <code>{}</code> <b>в чёрном списке</b>",
        "unmuted_chat": "🔊 <b>Чат</b> <code>{}</code> <b>убран из чёрного списка</b>",
        "muted_user": "🔇 <b>{}</b> <b>в чёрном списке</b>",
        "unmuted_user": "🔊 <b>{}</b> <b>убран из чёрного списка</b>",
        "blacklists": ("🔇 <b>Чёрный список</b>\n\n<b>Чаты:</b> {}\n<b>Люди:</b> {}"),
        "watchers": "👁 <b>Вотчеры</b>\n\n{}",
        "no_watchers": "👁 <b>Вотчеров нет</b>",
        "watcher_line": "{} <b>{}</b>{}",
        "watcher_off_here": "🚫 выключен здесь",
        "watcher_off_all": "🚫 выключен везде",
        "watcher_module": "🚫 <b>Модуля</b> <code>{}</code> <b>нет или у него нет вотчера</b>",
        "watcher_disabled": "🚫 <b>Вотчер</b> <b>{}</b> <b>выключен {}</b>",
        "watcher_enabled": "✅ <b>Вотчер</b> <b>{}</b> <b>снова работает {}</b>",
        "here": "в этом чате",
        "everywhere": "везде",
        "suspended": "😴 <b>Сойка не отвечает {} с.</b>",
        "suspend_usage": "🚫 <b>Сколько секунд молчать:</b> <code>{}suspend 60</code>",
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
        "no_target": "🚫 <b>Reply to a person or provide their ID</b>",
        "muted": "🔇 <b>Soika stays silent in this chat</b>",
        "unmuted": "🔊 <b>Soika listens to this chat again</b>",
        "muted_chat": "🔇 <b>Chat</b> <code>{}</code> <b>blacklisted</b>",
        "unmuted_chat": "🔊 <b>Chat</b> <code>{}</code> <b>removed from blacklist</b>",
        "muted_user": "🔇 <b>{}</b> <b>blacklisted</b>",
        "unmuted_user": "🔊 <b>{}</b> <b>removed from blacklist</b>",
        "blacklists": "🔇 <b>Blacklist</b>\n\n<b>Chats:</b> {}\n<b>People:</b> {}",
        "watchers": "👁 <b>Watchers</b>\n\n{}",
        "no_watchers": "👁 <b>No watchers</b>",
        "watcher_line": "{} <b>{}</b>{}",
        "watcher_off_here": "🚫 off here",
        "watcher_off_all": "🚫 off everywhere",
        "watcher_module": "🚫 <b>No module</b> <code>{}</code> <b>or it has no watcher</b>",
        "watcher_disabled": "🚫 <b>Watcher</b> <b>{}</b> <b>disabled {}</b>",
        "watcher_enabled": "✅ <b>Watcher</b> <b>{}</b> <b>works again {}</b>",
        "here": "in this chat",
        "everywhere": "everywhere",
        "suspended": "😴 <b>Soika is silent for {} s</b>",
        "suspend_usage": "🚫 <b>How long to stay silent:</b> <code>{}suspend 60</code>",
    }

    @loader.command(alias="setprefix")
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

    # ------------------------------------------------------------------ #
    #  Где Сойка молчит
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command(alias="bl")
    async def blacklistcmd(self, message):
        """[id чата] — не отвечать в этом чате (повторно — вернуть)"""
        args = utils.get_args_raw(message).strip()
        chat = self._chat_id(args) if args else utils.get_chat_id(message)
        chats = self.db.pointer(SETTINGS, BLACKLIST_CHATS, [], item_type=list)

        if chat in chats:
            chats.remove(chat)
            key = "unmuted_chat" if args else "unmuted"
        else:
            chats.append(chat)
            key = "muted_chat" if args else "muted"

        await utils.answer(message, self.strings[key].format(chat) if args else self.strings[key])

    @loader.owner
    @loader.command(alias="blu")
    async def blacklistusercmd(self, message):
        """[реплай|id] — не слушать команды этого человека (повторно — вернуть)"""
        user = await utils.get_target_user(message)

        if user is None:
            await utils.answer(message, self.strings["no_target"])
            return

        users = self.db.pointer(SETTINGS, BLACKLIST_USERS, [], item_type=list)
        title = utils.escape_html(utils.get_display_name(user))

        if user.id in users:
            users.remove(user.id)
            await utils.answer(message, self.strings["unmuted_user"].format(title))
            return

        users.append(user.id)
        await utils.answer(message, self.strings["muted_user"].format(title))

    @loader.owner
    @loader.command(alias="bls")
    async def blacklistscmd(self, message):
        """— кого и где Сойка не слушает"""
        chats = self.db.get(SETTINGS, BLACKLIST_CHATS, []) or []
        users = self.db.get(SETTINGS, BLACKLIST_USERS, []) or []

        await utils.answer(
            message,
            self.strings["blacklists"].format(
                ", ".join(f"<code>{chat}</code>" for chat in chats) or "—",
                ", ".join(f"<code>{user}</code>" for user in users) or "—",
            ),
        )

    @loader.owner
    @loader.command()
    async def suspendcmd(self, message):
        """<секунды> — не отвечать на команды заданное время"""
        args = utils.get_args_raw(message).strip()
        prefix = self.client.dispatcher.prefixes[0]

        if not args.isdigit() or not int(args):
            await utils.answer(message, self.strings["suspend_usage"].format(prefix))
            return

        seconds = int(args)
        await utils.answer(message, self.strings["suspended"].format(seconds))
        self.client.dispatcher.suspend(seconds)

    # ------------------------------------------------------------------ #
    #  Вотчеры
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command()
    async def watcherscmd(self, message):
        """— какие модули следят за сообщениями и где они выключены"""
        disabled = self.db.get(SETTINGS, DISABLED_WATCHERS, {}) or {}
        here = utils.get_chat_id(message)
        lines = []

        for handler in self.allmodules.watchers:
            module = getattr(handler, "__self__", None)

            if module is None:
                continue

            where = disabled.get(type(module).__name__, [])

            if "*" in where:
                state, note = "🚫", " · " + self.strings["watcher_off_all"]
            elif here in where:
                state, note = "🚫", " · " + self.strings["watcher_off_here"]
            else:
                state, note = "✅", ""

            lines.append(self.strings["watcher_line"].format(state, module.name, note))

        await utils.answer(
            message,
            self.strings["watchers"].format("\n".join(lines))
            if lines
            else self.strings["no_watchers"],
        )

    @loader.owner
    @loader.command(alias="wbl")
    async def watcherblcmd(self, message):
        """<модуль> [везде] — выключить вотчер модуля здесь или везде"""
        args = utils.get_args(message)

        if not args:
            await self.watcherscmd(message)
            return

        module = self.lookup(args[0])

        if module is None or not module.watchers:
            await utils.answer(message, self.strings["watcher_module"].format(args[0]))
            return

        everywhere = len(args) > 1 and args[1].lower() in {"везде", "all", "*"}
        target = "*" if everywhere else utils.get_chat_id(message)
        scope = self.strings["everywhere" if everywhere else "here"]

        disabled = self.db.pointer(SETTINGS, DISABLED_WATCHERS, {}, item_type=dict)
        where = list(disabled.get(type(module).__name__, []))

        if target in where:
            where.remove(target)
            key = "watcher_enabled"
        else:
            where.append(target)
            key = "watcher_disabled"

        if where:
            disabled[type(module).__name__] = where
        else:
            disabled.pop(type(module).__name__, None)

        await utils.answer(message, self.strings[key].format(module.name, scope))

    @staticmethod
    def _chat_id(value: str) -> int:
        """«-1001234567890» и «1234567890» — один и тот же чат."""
        digits = value.strip().lstrip("-")
        return int(digits.removeprefix("100") if digits.startswith("100") else digits)

    @loader.command(alias="setlang")
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
