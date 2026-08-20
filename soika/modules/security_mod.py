"""Кто может выполнять команды: sudo, support и маски прав."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/security_banner.png

import contextlib

from .. import loader, security, utils


@loader.tds
class SecurityMod(loader.Module):
    """Управление доступом к командам"""

    strings = {
        "name": "Безопасность",
        "added": "✅ <b>{}</b> <b>добавлен в</b> <code>{}</code>",
        "removed": "✅ <b>{}</b> <b>убран из</b> <code>{}</code>",
        "no_target": "🚫 <b>Ответь на сообщение пользователя или укажи его ID</b>",
        "list": "🪶 <b>Список</b> <code>{}</code><b>:</b>\n\n{}",
        "empty": "<i>пусто</i>",
        "command_missing": "🔎 <b>Команды</b> <code>{}</code> <b>не существует</b>",
        "mask": (
            "🪶 <b>Права команды</b> <code>{}</code>\n\n"
            "<b>Сейчас:</b> {}\n\n"
            "<i>Изменить:</i> <code>{}security {} owner sudo</code>\n"
            "<i>Доступные группы:</i> <code>{}</code>"
        ),
        "mask_set": "✅ <b>Права команды</b> <code>{}</code><b>:</b> {}",
        "mask_reset": "♻️ <b>Права команды</b> <code>{}</code> <b>вернулись к стандартным</b>",
        "unknown_group": "🚫 <b>Не знаю группу</b> <code>{}</code>",
        "rule_usage": (
            "🪶 <b>Точечный доступ — кому что можно</b>\n\n"
            "<code>{0}allow ping</code> — ответом на человека\n"
            "<code>{0}allow ping 123456</code> — по ID или @нику\n"
            "<code>{0}allow ping чат</code> — всем в этом чате\n"
            "<code>{0}allow * </code>— все команды разом\n\n"
            "<i>Забрать:</i> <code>{0}deny</code> с теми же аргументами, "
            "<i>посмотреть:</i> <code>{0}rules</code>"
        ),
        "rule_added": "✅ <b>Команда</b> <code>{}</code> <b>разрешена:</b> {}",
        "rule_removed": "♻️ <b>Команда</b> <code>{}</code> <b>больше не разрешена:</b> {}",
        "rules": "🪶 <b>Точечные разрешения</b>\n\n{}",
        "rule_user": "👤 <code>{}</code>",
        "rule_chat": "💬 чат <code>{}</code>",
        "this_chat": "<b>всем в этом чате</b>",
        "all_commands": "все команды",
    }

    strings_en = {
        "added": "✅ <b>{}</b> <b>added to</b> <code>{}</code>",
        "removed": "✅ <b>{}</b> <b>removed from</b> <code>{}</code>",
        "no_target": "🚫 <b>Reply to a user or provide their ID</b>",
        "list": "🪶 <b>List</b> <code>{}</code><b>:</b>\n\n{}",
        "empty": "<i>empty</i>",
        "command_missing": "🔎 <b>Command</b> <code>{}</code> <b>does not exist</b>",
        "mask": (
            "🪶 <b>Permissions of</b> <code>{}</code>\n\n"
            "<b>Current:</b> {}\n\n"
            "<i>Change:</i> <code>{}security {} owner sudo</code>\n"
            "<i>Groups:</i> <code>{}</code>"
        ),
        "mask_set": "✅ <b>Permissions of</b> <code>{}</code><b>:</b> {}",
        "mask_reset": "♻️ <b>Permissions of</b> <code>{}</code> <b>reset to default</b>",
        "unknown_group": "🚫 <b>Unknown group</b> <code>{}</code>",
        "rule_usage": (
            "🪶 <b>Targeted access — who may run what</b>\n\n"
            "<code>{0}allow ping</code> — replying to a person\n"
            "<code>{0}allow ping 123456</code> — by ID or @username\n"
            "<code>{0}allow ping chat</code> — everyone in this chat\n"
            "<code>{0}allow * </code>— every command at once\n\n"
            "<i>Revoke:</i> <code>{0}deny</code> with the same arguments, "
            "<i>list:</i> <code>{0}rules</code>"
        ),
        "rule_added": "✅ <b>Command</b> <code>{}</code> <b>allowed for:</b> {}",
        "rule_removed": "♻️ <b>Command</b> <code>{}</code> <b>no longer allowed for:</b> {}",
        "rules": "🪶 <b>Targeted permissions</b>\n\n{}",
        "rule_user": "👤 <code>{}</code>",
        "rule_chat": "💬 chat <code>{}</code>",
        "this_chat": "<b>everyone in this chat</b>",
        "all_commands": "every command",
    }

    @property
    def manager(self):
        return self.client.dispatcher.security

    @loader.command()
    async def sudocmd(self, message):
        """[реплай|id] — выдать или забрать полный доступ"""
        await self._toggle(message, "sudo")

    @loader.command()
    async def supportcmd(self, message):
        """[реплай|id] — выдать или забрать ограниченный доступ"""
        await self._toggle(message, "support")

    @loader.command()
    async def ownercmd(self, message):
        """[реплай|id] — список совладельцев юзербота"""
        await self._toggle(message, "owner")

    async def _toggle(self, message, kind: str) -> None:
        storage = getattr(self.manager, kind)
        user = await utils.get_target_user(message)

        if user is None:
            listing = "\n".join(f"▫️ <code>{user_id}</code>" for user_id in storage)
            await utils.answer(
                message,
                self.strings["list"].format(kind, listing or self.strings["empty"]),
            )
            return

        title = utils.escape_html(utils.get_display_name(user))

        if user.id in storage:
            storage.remove(user.id)
            await utils.answer(message, self.strings["removed"].format(title, kind))
            return

        storage.append(user.id)
        await utils.answer(message, self.strings["added"].format(title, kind))

    @loader.command(alias="sec")
    async def securitycmd(self, message):
        """<команда> [группы] — посмотреть или изменить права команды"""
        args = utils.get_args(message)
        prefix = self.client.dispatcher.prefixes[0]

        if not args:
            await self._overview(message)
            return

        command = args[0].lower()
        name, func = self.allmodules.dispatch(command)

        if func is None:
            await utils.answer(message, self.strings["command_missing"].format(command))
            return

        if len(args) == 1:
            await utils.answer(
                message,
                self.strings["mask"].format(
                    name,
                    security.describe(self.manager.mask_for(name, func)),
                    prefix,
                    name,
                    " ".join(security.BITS),
                ),
            )
            return

        if args[1].lower() in {"default", "сброс", "reset"}:
            self.manager.reset_mask(name)
            await utils.answer(message, self.strings["mask_reset"].format(name))
            return

        mask = 0

        for group in args[1:]:
            bit = security.BITS.get(group.lower())

            if bit is None:
                await utils.answer(message, self.strings["unknown_group"].format(group))
                return

            mask |= bit

        self.manager.set_mask(name, mask)
        await utils.answer(
            message,
            self.strings["mask_set"].format(name, security.describe(mask)),
        )

    @loader.owner
    @loader.command()
    async def allowcmd(self, message):
        """<команда> [реплай|id|чат] — разрешить команду человеку или в чате"""
        await self._rule(message, allow=True)

    @loader.owner
    @loader.command()
    async def denycmd(self, message):
        """<команда> [реплай|id|чат] — забрать точечное разрешение"""
        await self._rule(message, allow=False)

    @loader.owner
    @loader.command()
    async def rulescmd(self, message):
        """— кому и что разрешено точечно"""
        lines = []

        for key, commands in sorted(self.manager.chat_rules.items()):
            kind, _, ident = key.partition(":")
            title = self.strings["rule_chat" if kind == "chat" else "rule_user"].format(ident)
            shown = " ".join(
                self.strings["all_commands"] if command == "*" else command
                for command in sorted(commands)
            )
            lines.append(f"▫️ {title}: <code>{shown}</code>")

        await utils.answer(
            message,
            self.strings["rules"].format("\n".join(lines) or self.strings["empty"]),
        )

    async def _rule(self, message, *, allow: bool) -> None:
        """Разрешение живёт отдельно от sudo: одна команда одному человеку."""
        args = utils.get_args(message)
        prefix = self.client.dispatcher.prefixes[0]

        if not args:
            await utils.answer(message, self.strings["rule_usage"].format(prefix))
            return

        command = args[0].lstrip(prefix).lower()

        if command != "*":
            name, func = self.allmodules.dispatch(command)

            if func is None:
                await utils.answer(message, self.strings["command_missing"].format(command))
                return

            command = name

        target = await self._resolve_target(message, args[1:])

        if target is None:
            await utils.answer(message, self.strings["rule_usage"].format(prefix))
            return

        key, title = target

        if allow:
            self.manager.allow(key, command)
        else:
            self.manager.disallow(key, command)

        shown = self.strings["all_commands"] if command == "*" else command
        await utils.answer(
            message,
            self.strings["rule_added" if allow else "rule_removed"].format(shown, title),
        )

    async def _resolve_target(self, message, args: list) -> tuple | None:
        """Кому выдаём: человеку из реплая, по id/нику — или всему чату."""
        if args and args[0].lower() in {"chat", "чат", "here", "тут"}:
            # Ключ должен совпасть с тем, что ищет проверка прав, — там chat_id
            return f"chat:{getattr(message, 'chat_id', 0)}", self.strings["this_chat"]

        reply = await message.get_reply_message()

        if reply and reply.sender_id:
            with contextlib.suppress(Exception):
                user = await self.client.get_entity(reply.sender_id)
                return f"user:{user.id}", utils.escape_html(utils.get_display_name(user))

        if args:
            with contextlib.suppress(Exception):
                target = args[0]
                user = await self.client.get_entity(
                    int(target) if target.lstrip("-").isdigit() else target
                )
                return f"user:{user.id}", utils.escape_html(utils.get_display_name(user))

        return None

    async def _overview(self, message) -> None:
        masks = self.manager.masks

        listing = "\n".join(
            f"▫️ <code>{command}</code>: {security.describe(int(mask))}"
            for command, mask in sorted(masks.items())
        )

        await utils.answer(
            message,
            self.strings["list"].format("маски", listing or self.strings["empty"]),
        )
