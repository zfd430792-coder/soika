"""Логи: файлом по команде и потоком в служебный канал."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/logs_banner.png

import contextlib
import io
import logging

from .. import channels, loader, utils
from ..log import memory_handler

LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}
CHANNEL_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
MAX_FAILURES = 5


@loader.tds
class LogsMod(loader.Module):
    """Логи Сойки: файлом в чат и потоком в служебный канал"""

    strings = {
        "name": "Логи",
        "empty": "🪶 <b>Логов уровня</b> <code>{}</code> <b>нет — и хорошо</b>",
        "caption": "🪶 <b>Логи Сойки</b> · уровень <code>{}</code> · строк: {}",
        "cleared": "🧹 <b>Логи в памяти очищены</b>",
        "dump": "🔬 <b>Объект сообщения</b>\n<pre><code>{}</code></pre>",
        "unknown_level": "🚫 <b>Уровни:</b> <code>{}</code>",
        "channel_on": (
            '📜 <b>Лог-канал:</b> <a href="{}">soika-logs</a>\n'
            "<b>Уровень:</b> <code>{}</code> · <b>отправка раз в</b> {} с\n\n"
            "<i>Канал в архиве и заглушён. Выключить:</i> <code>{}logchannel off</code>"
        ),
        "channel_off": (
            "📜 <b>Лог-канал выключен</b>\n\n<i>Включить:</i> <code>{}logchannel on</code>"
        ),
        "channel_failed": "🚫 <b>Не получилось создать лог-канал — проверь лимит каналов</b>",
        "channel_enabled": '✅ <b>Лог-канал включён:</b> <a href="{}">soika-logs</a>',
        "channel_disabled": "✅ <b>Лог-канал выключен</b>",
    }

    strings_en = {
        "empty": "🪶 <b>No logs of level</b> <code>{}</code> <b>— and that's good</b>",
        "caption": "🪶 <b>Soika logs</b> · level <code>{}</code> · lines: {}",
        "cleared": "🧹 <b>In-memory logs cleared</b>",
        "unknown_level": "🚫 <b>Levels:</b> <code>{}</code>",
        "channel_on": (
            '📜 <b>Log channel:</b> <a href="{}">soika-logs</a>\n'
            "<b>Level:</b> <code>{}</code> · <b>flush every</b> {} s\n\n"
            "<i>Disable:</i> <code>{}logchannel off</code>"
        ),
        "channel_off": "📜 <b>Log channel is off</b>\n\n<i>Enable:</i> <code>{}logchannel on</code>",
        "channel_failed": "🚫 <b>Could not create the log channel — check the channel limit</b>",
        "channel_enabled": '✅ <b>Log channel enabled:</b> <a href="{}">soika-logs</a>',
        "channel_disabled": "✅ <b>Log channel disabled</b>",
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "channel",
            True,
            "Слать логи в служебный канал soika-logs",
            validator=loader.validators.Boolean(),
        ),
        loader.ConfigValue(
            "level",
            "ERROR",
            "С какого уровня слать логи в канал",
            validator=loader.validators.Choice(CHANNEL_LEVELS),
        ),
        loader.ConfigValue(
            "interval",
            15,
            "Как часто отправлять накопленное в канал, секунд",
            validator=loader.validators.Integer(minimum=5, maximum=600),
        ),
    )

    def __init__(self) -> None:
        self._last_id = 0
        self._channel = None
        self._failures = 0
        self._busy = False

    async def client_ready(self, client, db):
        # Стартуем с текущей позиции: старые записи в канал не сыпем
        self._last_id = memory_handler().last_id
        self.log_sender.interval = self.config["interval"]

        if self.config["channel"]:
            await self._ensure_channel()

    async def config_complete(self):
        with contextlib.suppress(Exception):
            self.log_sender.interval = self.config["interval"]

    async def _ensure_channel(self):
        if self._channel is None:
            self._channel = await channels.ensure_channel(self.client, self.db, "logs")

        return self._channel

    # ------------------------------------------------------------------ #
    #  Поток логов в канал
    # ------------------------------------------------------------------ #
    @loader.loop(interval=15, autostart=True, wait_before=True)
    async def log_sender(self):
        if not self.config["channel"] or self._busy or self._failures >= MAX_FAILURES:
            return

        channel = await self._ensure_channel()

        if channel is None:
            self._failures += 1
            return

        level = LEVELS.get(str(self.config["level"]).lower(), logging.ERROR)
        self._last_id, lines = memory_handler().dumps_since(self._last_id, level)

        if not lines:
            return

        self._busy = True

        # Внутри — молча: жалоба на неудачную отправку логов сама попадёт
        # в логи и мы будем гонять её по кругу
        try:
            for chunk in utils.smart_split("\n".join(lines), 3500):
                await self.client.send_message(
                    channel,
                    f"<pre><code>{utils.escape_html(chunk)}</code></pre>",
                )

            self._failures = 0
        except Exception:  # noqa: BLE001
            self._failures += 1
        finally:
            self._busy = False

    # ------------------------------------------------------------------ #
    #  Команды
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command()
    async def dumpcmd(self, message):
        """— показать объект сообщения, на которое отвечаешь"""
        reply = await message.get_reply_message()
        target = reply or message
        dump = target.stringify() if hasattr(target, "stringify") else repr(target)

        if len(dump) > 3000:
            payload = io.BytesIO(dump.encode())
            payload.name = "dump.txt"
            await utils.answer_file(message, payload)
            return

        await utils.answer(message, self.strings["dump"].format(utils.escape_html(dump)))

    @loader.owner
    @loader.command()
    async def logscmd(self, message):
        """[уровень] — прислать логи файлом (debug/info/warning/error)"""
        raw = utils.get_args_raw(message).lower().strip()
        level = logging.INFO

        if raw:
            if raw.isdigit():
                level = int(raw)
            elif raw in LEVELS:
                level = LEVELS[raw]
            else:
                await utils.answer(
                    message,
                    self.strings["unknown_level"].format(", ".join(LEVELS)),
                )
                return

        entries = memory_handler().dumps(level)

        if not entries:
            await utils.answer(message, self.strings["empty"].format(logging.getLevelName(level)))
            return

        payload = io.BytesIO("\n".join(entries).encode())
        payload.name = "soika-logs.txt"

        await utils.answer_file(
            message,
            payload,
            caption=self.strings["caption"].format(logging.getLevelName(level), len(entries)),
        )

    @loader.owner
    @loader.command(alias="logchat")
    async def logchannelcmd(self, message):
        """[on|off] — лог-канал: ссылка, включение и выключение"""
        args = utils.get_args_raw(message).lower().strip()
        prefix = self.client.dispatcher.prefixes[0]

        if args in {"off", "выкл", "0"}:
            self.config["channel"] = False
            self.allmodules.save_config(self)
            await utils.answer(message, self.strings["channel_disabled"])
            return

        if args in {"on", "вкл", "1"}:
            self.config["channel"] = True
            self.allmodules.save_config(self)
            channel = await self._ensure_channel()

            if channel is None:
                await utils.answer(message, self.strings["channel_failed"])
                return

            link = await channels.channel_link(self.client, channel)
            await utils.answer(message, self.strings["channel_enabled"].format(link))
            return

        if not self.config["channel"]:
            await utils.answer(message, self.strings["channel_off"].format(prefix))
            return

        channel = await self._ensure_channel()

        if channel is None:
            await utils.answer(message, self.strings["channel_failed"])
            return

        link = await channels.channel_link(self.client, channel)
        await utils.answer(
            message,
            self.strings["channel_on"].format(
                link,
                self.config["level"],
                self.config["interval"],
                prefix,
            ),
        )

    @loader.owner
    @loader.command()
    async def clearlogscmd(self, message):
        """— очистить логи в памяти"""
        memory_handler().clear()
        self._last_id = 0
        await utils.answer(message, self.strings["cleared"])
