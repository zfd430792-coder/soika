"""Кто может выполнять команды: sudo, support и маски прав."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/security_banner.png

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
