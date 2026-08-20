"""Кто может выполнять команды: sudo, support и маски прав."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/security_banner.png

import contextlib
import time

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
        "forever": "навсегда",
        "for_time": "на {}",
        "until": " · осталось {}",
        "bounding": (
            "🔒 <b>Потолок прав</b>\n\n"
            "<i>Что бы ни просил модуль, выше этого команда не поднимется.</i>\n"
            "<b>Сейчас:</b> {}"
        ),
        "mask_panel": (
            "🪶 <b>Права команды</b> <code>{}</code>\n\n<i>Жми кнопки — они переключают группы.</i>"
        ),
        "btn_reset": "♻️ Сбросить",
        "btn_close": "✖️ Закрыть",
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
        "forever": "forever",
        "for_time": "for {}",
        "until": " · {} left",
        "bounding": (
            "🔒 <b>Permission ceiling</b>\n\n"
            "<i>No command rises above this, whatever the module asks for.</i>\n"
            "<b>Now:</b> {}"
        ),
        "mask_panel": (
            "🪶 <b>Permissions of</b> <code>{}</code>\n\n<i>Tap the buttons to toggle groups.</i>"
        ),
        "btn_reset": "♻️ Reset",
        "btn_close": "✖️ Close",
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
            if self._inline_ready() and await self.inline.form(
                self.strings["bounding"].format(security.describe(self.manager.bounding_mask)),
                message=message,
                reply_markup=self._bounding_markup(),
            ):
                return

            await self._overview(message)
            return

        command = args[0].lower()
        name, func = self.allmodules.dispatch(command)

        if func is None:
            await utils.answer(message, self.strings["command_missing"].format(command))
            return

        if len(args) == 1:
            # Как у Hikka: панель с кнопками-переключателями, текст — если бота нет
            if self._inline_ready() and await self.inline.form(
                self.strings["mask_panel"].format(name),
                message=message,
                reply_markup=self._mask_markup(name),
            ):
                return

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
        """<команда> [реплай|id|чат] [время] — разрешить команду"""
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

        now = time.time()

        for key in sorted(self.manager.chat_rules):
            kind, _, ident = key.partition(":")
            title = self.strings["rule_chat" if kind == "chat" else "rule_user"].format(ident)

            for command, until in sorted(self.manager.rules_for(key).items()):
                shown = self.strings["all_commands"] if command == "*" else command
                left = (
                    self.strings["until"].format(utils.format_timedelta(int(until - now)))
                    if until
                    else ""
                )
                lines.append(f"▫️ {title}: <code>{shown}</code>{left}")

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

        rest = list(args[1:])
        seconds = self._parse_time(rest[-1]) if rest else 0

        if seconds:
            rest.pop()

        target = await self._resolve_target(message, rest)

        if target is None:
            await utils.answer(message, self.strings["rule_usage"].format(prefix))
            return

        key, title = target

        if allow:
            self.manager.allow(key, command, seconds)
        else:
            self.manager.disallow(key, command)

        shown = self.strings["all_commands"] if command == "*" else command
        note = (
            self.strings["for_time"].format(utils.format_timedelta(int(seconds)))
            if seconds
            else self.strings["forever"]
        )
        await utils.answer(
            message,
            self.strings["rule_added" if allow else "rule_removed"].format(shown, title)
            + (f" · {note}" if allow else ""),
        )

    @staticmethod
    def _parse_time(value: str) -> float:
        """«30m», «2h», «7d» → секунды. Не время — 0."""
        units = {"m": 60, "м": 60, "h": 3600, "ч": 3600, "d": 86400, "д": 86400}
        value = value.strip().lower()

        if len(value) < 2 or value[-1] not in units or not value[:-1].isdigit():
            return 0

        return int(value[:-1]) * units[value[-1]]

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

    # ------------------------------------------------------------------ #
    #  Панели с кнопками
    # ------------------------------------------------------------------ #
    def _inline_ready(self) -> bool:
        return self.inline is not None and self.inline.init_complete

    def _mask_markup(self, command: str) -> list:
        """Кнопка на каждую группу прав: нажал — включилась или выключилась."""
        _, func = self.allmodules.dispatch(command)
        mask = self.manager.mask_for(command, func)

        buttons = [
            {
                "text": f"{'✅' if mask & bit else '🚫'} {security.TITLES[bit]}",
                "callback": self._toggle_bit,
                "args": (command, name),
            }
            for name, bit in security.BITS.items()
        ]

        return [
            *utils.chunks(buttons, 2),
            [
                {
                    "text": self.strings["btn_reset"],
                    "callback": self._reset_mask,
                    "args": (command,),
                },
                {"text": self.strings["btn_close"], "callback": self._close},
            ],
        ]

    async def _toggle_bit(self, call, command: str, group: str) -> None:
        _, func = self.allmodules.dispatch(command)
        mask = self.manager.mask_for(command, func) ^ security.BITS[group]

        self.manager.set_mask(command, mask)
        await call.answer(security.describe(mask))
        await call.edit(
            self.strings["mask_panel"].format(command),
            reply_markup=self._mask_markup(command),
        )

    async def _reset_mask(self, call, command: str) -> None:
        self.manager.reset_mask(command)
        await call.answer(self.strings["mask_reset"].format(command))
        await call.edit(
            self.strings["mask_panel"].format(command),
            reply_markup=self._mask_markup(command),
        )

    def _bounding_markup(self) -> list:
        """Потолок прав — те же группы, но общие для всех команд."""
        mask = self.manager.bounding_mask

        buttons = [
            {
                "text": f"{'✅' if mask & bit else '🚫'} {security.TITLES[bit]}",
                "callback": self._toggle_bounding,
                "args": (name,),
            }
            for name, bit in security.BITS.items()
        ]

        return [
            *utils.chunks(buttons, 2),
            [{"text": self.strings["btn_close"], "callback": self._close}],
        ]

    async def _toggle_bounding(self, call, group: str) -> None:
        mask = self.manager.bounding_mask ^ security.BITS[group]

        # Владельца из потолка не выкидываем — иначе своими же руками себя запрёшь
        mask |= security.OWNER

        self.manager.set_bounding_mask(mask)
        await call.answer(security.describe(mask))
        await call.edit(
            self.strings["bounding"].format(security.describe(mask)),
            reply_markup=self._bounding_markup(),
        )

    async def _close(self, call) -> None:
        await call.delete()

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
