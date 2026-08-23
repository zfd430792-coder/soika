"""Где допущенным можно стрелять и что дают именованные группы прав.

Права отвечают на вопрос «что человеку можно». Здесь — два других вопроса:
«и где» (nonick) и «а можно ли раздать пачкой нескольким» (группы).
"""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/access_banner.png

import contextlib

from .. import loader, utils
from ..dispatcher import (
    NONICK_ALL,
    NONICK_CHATS,
    NONICK_COMMANDS,
    NONICK_USERS,
    SETTINGS,
)


@loader.tds
class AccessMod(loader.Module):
    """Где допущенным можно работать и группы прав"""

    strings = {
        "name": "Доступ",
        "no_target": "🚫 <b>Ответь на сообщение человека или укажи его ID</b>",
        "no_group": "🔎 <b>Группы</b> <code>{}</code> <b>нет</b>",
        "no_args": "🚫 <b>Не хватает аргументов.</b> {}",
        # -- nonick -------------------------------------------------------- #
        "nonick_user_on": "✅ <b>{}</b> <b>может работать в общих чатах</b>",
        "nonick_user_off": (
            "🔇 <b>{}</b> <b>больше не работает в общих чатах</b>\n"
            "<i>В личке и через</i> <code>{}команда@{}</code> <i>по-прежнему может</i>"
        ),
        "nonick_chat_on": "✅ <b>В этом чате допущенные работают без адресации</b>",
        "nonick_chat_off": "🔇 <b>В этом чате допущенным снова нужна адресация</b>",
        "nonick_cmd_on": "✅ <b>Команда</b> <code>{}</code> <b>работает в общих чатах</b>",
        "nonick_cmd_off": "🔇 <b>Команде</b> <code>{}</code> <b>снова нужна адресация</b>",
        "nonick_all_on": (
            "⚠️ <b>Заслон снят полностью</b>\n"
            "<i>Любой допущенный работает в любом чате без адресации</i>"
        ),
        "nonick_all_off": "🔒 <b>Заслон вернулся</b>",
        "nonick_list": (
            "🔓 <b>Кого пускают в общие чаты</b>\n\n"
            "<b>Заслон снят целиком:</b> {all}\n\n"
            "<b>Люди:</b> {users}\n"
            "<b>Чаты:</b> {chats}\n"
            "<b>Команды:</b> {commands}\n\n"
            "<i>Остальным в группах нужно</i> <code>{prefix}команда@{username}</code>"
        ),
        # -- группы -------------------------------------------------------- #
        "group_created": "✅ <b>Группа</b> <code>{}</code> <b>создана</b>",
        "group_exists": "🚫 <b>Группа</b> <code>{}</code> <b>уже есть</b>",
        "group_deleted": "🗑 <b>Группа</b> <code>{}</code> <b>удалена</b>",
        "group_user_on": "✅ <b>{}</b> <b>в группе</b> <code>{}</code>",
        "group_user_off": "✅ <b>{}</b> <b>убран из группы</b> <code>{}</code>",
        "group_rule_on": "✅ <b>{}</b> <code>{}</code> <b>разрешён группе</b> <code>{}</code>",
        "group_rule_off": "✅ <b>{}</b> <code>{}</code> <b>отобран у группы</b> <code>{}</code>",
        "groups": "🪶 <b>Группы прав</b>\n\n{}",
        "group_row": "▫️ <code>{}</code> — <b>людей:</b> {} · <b>прав:</b> {}",
        "group_info": (
            "🪶 <b>Группа</b> <code>{name}</code>\n\n"
            "<b>Люди:</b> {users}\n"
            "<b>Команды:</b> {commands}\n"
            "<b>Модули целиком:</b> {modules}"
        ),
        "no_groups": "<i>Групп пока нет.</i> <code>{}newsgroup имя</code>",
        "empty": "<i>никого</i>",
        "kind_command": "Команда",
        "kind_module": "Модуль",
        "usage_sgroup": "<code>{0}sgroup имя ping</code> <i>или</i> <code>{0}sgroup имя Заметки</code>",
        "usage_name": "<code>{}newsgroup имя</code>",
    }

    strings_en = {
        "no_target": "🚫 <b>Reply to a person or give their ID</b>",
        "no_group": "🔎 <b>No group</b> <code>{}</code>",
        "empty": "<i>nobody</i>",
        "kind_command": "Command",
        "kind_module": "Module",
    }

    @property
    def manager(self):
        return self.client.dispatcher.security

    @property
    def prefix(self) -> str:
        return self.client.dispatcher.prefixes[0]

    @property
    def username(self) -> str:
        return getattr(self.client.soika_me, "username", None) or "username"

    # ------------------------------------------------------------------ #
    #  Где допущенным можно работать
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command()
    async def nonickusercmd(self, message):
        """[реплай|id] — впустить человека в общие чаты без адресации"""
        target = await self._target(message)

        if target is None:
            await utils.answer(message, self.strings["no_target"])
            return

        user_id, name = target
        added = self._toggle(NONICK_USERS, user_id)

        if added:
            await utils.answer(message, self.strings["nonick_user_on"].format(name))
            return

        await utils.answer(
            message,
            self.strings["nonick_user_off"].format(name, self.prefix, self.username),
        )

    @loader.owner
    @loader.command()
    async def nonickchatcmd(self, message):
        """— впустить всех допущенных в этот чат без адресации"""
        added = self._toggle(NONICK_CHATS, utils.get_chat_id(message))
        await utils.answer(message, self.strings[f"nonick_chat_{'on' if added else 'off'}"])

    @loader.owner
    @loader.command()
    async def nonickcmdcmd(self, message):
        """<команда> — эта команда работает в общих чатах без адресации"""
        command = utils.get_args_raw(message).strip().lstrip(self.prefix)

        if not command:
            await utils.answer(
                message, self.strings["no_args"].format(f"<code>{self.prefix}help</code>")
            )
            return

        added = self._toggle(NONICK_COMMANDS, command)
        key = f"nonick_cmd_{'on' if added else 'off'}"

        await utils.answer(message, self.strings[key].format(utils.escape_html(command)))

    @loader.owner
    @loader.command()
    async def nonickallcmd(self, message):
        """— снять заслон целиком: любой допущенный работает везде"""
        value = not self.db.get(SETTINGS, NONICK_ALL, False)
        self.db.set(SETTINGS, NONICK_ALL, value)

        await utils.answer(message, self.strings[f"nonick_all_{'on' if value else 'off'}"])

    @loader.owner
    @loader.command(alias="nonicks")
    async def nonicklistcmd(self, message):
        """— кого и где пускают работать без адресации"""
        await utils.answer(
            message,
            self.strings["nonick_list"].format(
                all="да" if self.db.get(SETTINGS, NONICK_ALL, False) else "нет",
                users=await self._names(self.db.get(SETTINGS, NONICK_USERS, []) or []),
                chats=self._codes(self.db.get(SETTINGS, NONICK_CHATS, []) or []),
                commands=self._codes(self.db.get(SETTINGS, NONICK_COMMANDS, []) or []),
                prefix=self.prefix,
                username=self.username,
            ),
        )

    # ------------------------------------------------------------------ #
    #  Именованные группы прав
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command()
    async def newsgroupcmd(self, message):
        """<имя> — создать группу прав"""
        name = utils.get_args_raw(message).strip()

        if not name:
            await utils.answer(
                message,
                self.strings["no_args"].format(self.strings["usage_name"].format(self.prefix)),
            )
            return

        key = "group_created" if self.manager.new_sgroup(name) else "group_exists"
        await utils.answer(message, self.strings[key].format(utils.escape_html(name)))

    @loader.owner
    @loader.command()
    async def delsgroupcmd(self, message):
        """<имя> — удалить группу прав"""
        name = utils.get_args_raw(message).strip()

        if not self.manager.del_sgroup(name):
            await utils.answer(message, self.strings["no_group"].format(utils.escape_html(name)))
            return

        await utils.answer(message, self.strings["group_deleted"].format(utils.escape_html(name)))

    @loader.owner
    @loader.command()
    async def sgroupaddcmd(self, message):
        """<имя> [реплай|id] — добавить или убрать человека в группе"""
        args = utils.get_args(message)

        if not args:
            await utils.answer(
                message,
                self.strings["no_args"].format(self.strings["usage_name"].format(self.prefix)),
            )
            return

        name, rest = args[0], args[1:]
        target = await self._target(message, rest)

        if target is None:
            await utils.answer(message, self.strings["no_target"])
            return

        user_id, display = target
        added = self.manager.sgroup_user(name, user_id)

        if added is None:
            await utils.answer(message, self.strings["no_group"].format(utils.escape_html(name)))
            return

        key = "group_user_on" if added else "group_user_off"
        await utils.answer(message, self.strings[key].format(display, utils.escape_html(name)))

    @loader.owner
    @loader.command()
    async def sgroupcmd(self, message):
        """<имя> [команда|модуль] — показать группу или дать/отобрать право"""
        args = utils.get_args(message)

        if not args:
            await utils.answer(
                message,
                self.strings["no_args"].format(self.strings["usage_sgroup"].format(self.prefix)),
            )
            return

        name, rules = args[0], args[1:]
        group = self.manager.sgroup(name)

        if group is None:
            await utils.answer(message, self.strings["no_group"].format(utils.escape_html(name)))
            return

        if not rules:
            await self._show_group(message, name, group)
            return

        for rule in rules:
            await self._grant(message, name, rule.lstrip(self.prefix))

    @loader.owner
    @loader.command(alias="sgroups")
    async def sgrouplistcmd(self, message):
        """— все группы прав"""
        groups = self.manager.sgroups

        listing = "\n".join(
            self.strings["group_row"].format(
                utils.escape_html(name),
                len(group.get("users") or []),
                len(group.get("commands") or []) + len(group.get("modules") or []),
            )
            for name, group in sorted(groups.items())
        )

        await utils.answer(
            message,
            self.strings["groups"].format(listing or self.strings["no_groups"].format(self.prefix)),
        )

    # ------------------------------------------------------------------ #
    #  Внутреннее
    # ------------------------------------------------------------------ #
    async def _grant(self, message, name: str, rule: str) -> None:
        """Правило — это либо команда, либо модуль целиком. Различаем по факту."""
        module = self.lookup(rule)
        kind = (
            "modules" if module is not None and rule not in self.allmodules.commands else "commands"
        )
        value = type(module).__name__ if kind == "modules" else rule

        added = self.manager.sgroup_rule(name, kind, value)
        key = "group_rule_on" if added else "group_rule_off"
        title = self.strings["kind_module" if kind == "modules" else "kind_command"]

        await utils.answer(
            message,
            self.strings[key].format(title, utils.escape_html(rule), utils.escape_html(name)),
        )

    async def _show_group(self, message, name: str, group: dict) -> None:
        await utils.answer(
            message,
            self.strings["group_info"].format(
                name=utils.escape_html(name),
                users=await self._names(group.get("users") or []),
                commands=self._codes(group.get("commands") or []),
                modules=self._codes(group.get("modules") or []),
            ),
        )

    def _toggle(self, key: str, value) -> bool:
        """Добавить или убрать значение в списке настроек. True — добавлено."""
        current = list(self.db.get(SETTINGS, key, []) or [])

        if value in current:
            current.remove(value)
            self.db.set(SETTINGS, key, current)
            return False

        current.append(value)
        self.db.set(SETTINGS, key, current)
        return True

    async def _target(self, message, args: list | None = None) -> tuple[int, str] | None:
        """Человек из реплая, по id или по нику."""
        if args is None:
            args = utils.get_args(message)

        reply = await message.get_reply_message()

        if reply and reply.sender_id:
            with contextlib.suppress(Exception):
                user = await self.client.get_entity(reply.sender_id)
                return user.id, utils.escape_html(utils.get_display_name(user))

        if args:
            with contextlib.suppress(Exception):
                raw = args[0]
                user = await self.client.get_entity(int(raw) if raw.lstrip("-").isdigit() else raw)
                return user.id, utils.escape_html(utils.get_display_name(user))

        return None

    async def _names(self, ids: list) -> str:
        """Список людей именами, а не голыми числами."""
        if not ids:
            return self.strings["empty"]

        names = []

        for user_id in ids:
            name = str(user_id)

            with contextlib.suppress(Exception):
                entity = await self.client.get_entity(user_id)
                name = utils.get_display_name(entity)

            names.append(f"<code>{utils.escape_html(name)}</code>")

        return ", ".join(names)

    def _codes(self, values: list) -> str:
        if not values:
            return self.strings["empty"]

        return ", ".join(f"<code>{utils.escape_html(str(value))}</code>" for value in values)
