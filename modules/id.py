"""Показывает ID чата, пользователя и сообщения."""

# meta developer: @soika
# meta description: ID чата, пользователя и сообщения одной командой

from .. import loader, utils


@loader.tds
class IdMod(loader.Module):
    """Достаёт ID чата, пользователя и сообщения"""

    strings = {
        "name": "ID",
        "info": (
            "🆔 <b>Чат:</b> <code>{chat}</code>\n"
            "<b>Сообщение:</b> <code>{message}</code>\n"
            "{user}"
        ),
        "user": "<b>Пользователь:</b> <code>{id}</code> — {name}",
        "no_user": "<i>Пользователь не определён</i>",
    }

    strings_en = {
        "info": (
            "🆔 <b>Chat:</b> <code>{chat}</code>\n"
            "<b>Message:</b> <code>{message}</code>\n"
            "{user}"
        ),
        "user": "<b>User:</b> <code>{id}</code> — {name}",
        "no_user": "<i>No user detected</i>",
    }

    @loader.command(alias="айди")
    async def idcmd(self, message):
        """[реплай] — показать ID чата, сообщения и пользователя"""
        user = await utils.get_target_user(message)

        await utils.answer(
            message,
            self.strings["info"].format(
                chat=utils.get_chat_id(message),
                message=message.id,
                user=self.strings["user"].format(
                    id=user.id,
                    name=utils.escape_html(utils.get_display_name(user)),
                )
                if user
                else self.strings["no_user"],
            ),
        )
