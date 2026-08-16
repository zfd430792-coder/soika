"""Резервные копии базы: вручную, по времени суток или по интервалу."""

import contextlib
import io
import json
import logging
import time
from datetime import datetime

from .. import channels, loader, utils

logger = logging.getLogger(__name__)

MODES = ["off", "daily", "interval"]
TARGETS = ["channel", "saved"]
TIME_RE = r"^([01]?\d|2[0-3]):[0-5]\d$"


@loader.tds
class BackupMod(loader.Module):
    """Бэкапы базы Сойки: вручную, по расписанию, в отдельный канал"""

    strings = {
        "name": "Бэкап",
        "caption": "🪶 <b>Бэкап базы Сойки</b>\n<b>Разделов:</b> {} · <b>время:</b> {}",
        "no_file": "🚫 <b>Ответь на файл с бэкапом</b>",
        "restored": "✅ <b>База восстановлена. Перезапусти Сойку:</b> <code>{}restart</code>",
        "bad_file": "🚫 <b>Это не похоже на бэкап базы</b>",
        "status": (
            "🗄 <b>Бэкапы</b>\n\n"
            "<b>Режим:</b> {mode}\n"
            "<b>Куда:</b> {target}\n"
            "<b>Последний:</b> {last}\n\n"
            "<i>Настроить:</i> <code>{prefix}cfg</code> → Бэкап\n"
            "<i>Быстро:</i> <code>{prefix}autobackup 03:30</code>, "
            "<code>{prefix}autobackup 6h</code>, <code>{prefix}autobackup off</code>"
        ),
        "mode_off": "выключен, только вручную",
        "mode_daily": "каждый день в <code>{}</code> (время сервера)",
        "mode_interval": "каждые <code>{}</code> ч.",
        "target_channel": "в канал <a href=\"{}\">soika-backups</a>",
        "target_saved": "в «Избранное»",
        "never": "<i>ещё не делался</i>",
        "set_daily": "✅ <b>Бэкап каждый день в</b> <code>{}</code>",
        "set_interval": "✅ <b>Бэкап каждые</b> <code>{}</code> <b>ч.</b>",
        "set_off": "✅ <b>Автобэкап выключен</b>",
        "usage": (
            "🚫 <b>Как надо:</b>\n"
            "<code>{0}autobackup 03:30</code> — каждый день в 3:30\n"
            "<code>{0}autobackup 6h</code> — каждые 6 часов\n"
            "<code>{0}autobackup off</code> — выключить"
        ),
        "done": "✅ <b>Бэкап отправлен {}</b>",
    }

    strings_en = {
        "caption": "🪶 <b>Soika database backup</b>\n<b>Sections:</b> {} · <b>time:</b> {}",
        "no_file": "🚫 <b>Reply to a backup file</b>",
        "restored": "✅ <b>Database restored. Restart Soika:</b> <code>{}restart</code>",
        "bad_file": "🚫 <b>This does not look like a backup</b>",
        "status": (
            "🗄 <b>Backups</b>\n\n"
            "<b>Mode:</b> {mode}\n"
            "<b>Target:</b> {target}\n"
            "<b>Last one:</b> {last}\n\n"
            "<i>Configure:</i> <code>{prefix}cfg</code> → Backup"
        ),
        "mode_off": "off, manual only",
        "mode_daily": "daily at <code>{}</code> (server time)",
        "mode_interval": "every <code>{}</code> h.",
        "target_channel": "to <a href=\"{}\">soika-backups</a>",
        "target_saved": "to Saved Messages",
        "never": "<i>never</i>",
        "set_daily": "✅ <b>Backup every day at</b> <code>{}</code>",
        "set_interval": "✅ <b>Backup every</b> <code>{}</code> <b>h.</b>",
        "set_off": "✅ <b>Auto backup disabled</b>",
        "usage": "🚫 <b>Usage:</b> <code>{0}autobackup 03:30</code> / <code>{0}autobackup 6h</code>",
        "done": "✅ <b>Backup sent {}</b>",
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "mode",
            "daily",
            "Режим: off — только вручную, daily — раз в сутки, interval — раз в N часов",
            validator=loader.validators.Choice(MODES),
        ),
        loader.ConfigValue(
            "time",
            "04:00",
            "Во сколько делать ежедневный бэкап, ЧЧ:ММ по времени сервера",
            validator=loader.validators.RegExp(TIME_RE, description="время в формате ЧЧ:ММ"),
        ),
        loader.ConfigValue(
            "interval",
            12,
            "Каждые сколько часов делать бэкап в режиме interval",
            validator=loader.validators.Integer(minimum=1, maximum=168),
        ),
        loader.ConfigValue(
            "target",
            "channel",
            "Куда складывать: channel — в soika-backups, saved — в «Избранное»",
            validator=loader.validators.Choice(TARGETS),
        ),
        loader.ConfigValue(
            "keep",
            20,
            "Сколько последних бэкапов хранить в канале",
            validator=loader.validators.Integer(minimum=1, maximum=200),
        ),
    )

    def __init__(self) -> None:
        self._channel = None

    # ------------------------------------------------------------------ #
    #  Команды
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command(alias="bkp")
    async def backupcmd(self, message):
        """— сделать бэкап прямо сейчас"""
        await utils.answer_file(message, *self._payload())

    @loader.owner
    @loader.command()
    async def backupscmd(self, message):
        """— расписание бэкапов и куда они уезжают"""
        prefix = self.client.dispatcher.prefixes[0]
        mode = self.config["mode"]

        if mode == "daily":
            mode_text = self.strings["mode_daily"].format(self.config["time"])
        elif mode == "interval":
            mode_text = self.strings["mode_interval"].format(self.config["interval"])
        else:
            mode_text = self.strings["mode_off"]

        if self.config["target"] == "channel":
            channel = await self._ensure_channel()
            link = await channels.channel_link(self.client, channel) if channel else "—"
            target_text = self.strings["target_channel"].format(link)
        else:
            target_text = self.strings["target_saved"]

        last = self.get("last_backup", 0)
        last_text = (
            time.strftime("%d.%m.%Y %H:%M", time.localtime(last))
            if last
            else self.strings["never"]
        )

        await utils.answer(
            message,
            self.strings["status"].format(
                mode=mode_text,
                target=target_text,
                last=last_text,
                prefix=prefix,
            ),
        )

    @loader.owner
    @loader.command()
    async def autobackupcmd(self, message):
        """<ЧЧ:ММ | Nh | off> — расписание бэкапа одной командой"""
        args = utils.get_args_raw(message).lower().strip()
        prefix = self.client.dispatcher.prefixes[0]

        if args in {"off", "выкл", "0", "нет"}:
            self.config["mode"] = "off"
            self.allmodules.save_config(self)
            await utils.answer(message, self.strings["set_off"])
            return

        if args.endswith(("h", "ч")) and args[:-1].strip().isdigit():
            hours = int(args[:-1].strip())
            self.config["interval"] = hours
            self.config["mode"] = "interval"
            self.allmodules.save_config(self)
            await utils.answer(message, self.strings["set_interval"].format(hours))
            return

        if ":" in args:
            try:
                self.config["time"] = args
            except loader.validators.ValidationError:
                await utils.answer(message, self.strings["usage"].format(prefix))
                return

            self.config["mode"] = "daily"
            self.allmodules.save_config(self)
            await utils.answer(message, self.strings["set_daily"].format(args))
            return

        await utils.answer(message, self.strings["usage"].format(prefix))

    @loader.owner
    @loader.command()
    async def restoredbcmd(self, message):
        """— восстановить базу из файла (ответом на файл)"""
        reply = await message.get_reply_message()

        if not reply or not reply.document:
            await utils.answer(message, self.strings["no_file"])
            return

        payload = await reply.download_media(bytes)

        try:
            data = json.loads(payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            await utils.answer(message, self.strings["bad_file"])
            return

        if not isinstance(data, dict):
            await utils.answer(message, self.strings["bad_file"])
            return

        self.db.clear()
        self.db.update(data)
        await self.db.flush()

        prefix = self.client.dispatcher.prefixes[0]
        await utils.answer(message, self.strings["restored"].format(prefix))

    # ------------------------------------------------------------------ #
    #  Расписание
    # ------------------------------------------------------------------ #
    @loader.loop(interval=60, autostart=True, wait_before=True)
    async def backup_loop(self):
        mode = self.config["mode"]

        if mode == "off" or not self._is_due(mode):
            return

        try:
            await self._send_backup()
        except Exception:
            logger.exception("Автобэкап не удался")

    def _is_due(self, mode: str) -> bool:
        now = datetime.now()

        if mode == "interval":
            return time.time() - self.get("last_backup", 0) >= self.config["interval"] * 3600

        # daily: сегодня ещё не делали и время уже наступило
        today = now.strftime("%Y-%m-%d")

        if self.get("last_daily") == today:
            return False

        return now.strftime("%H:%M") >= self._normalized_time()

    def _normalized_time(self) -> str:
        hours, _, minutes = str(self.config["time"]).partition(":")
        return f"{int(hours):02d}:{minutes}"

    # ------------------------------------------------------------------ #
    #  Отправка
    # ------------------------------------------------------------------ #
    def _payload(self) -> tuple:
        dump = json.dumps(dict(self.db), ensure_ascii=False, indent=2)
        payload = io.BytesIO(dump.encode())
        payload.name = f"soika-db-{self.client.tg_id}-{time.strftime('%Y%m%d-%H%M')}.json"
        caption = self.strings["caption"].format(len(self.db), time.strftime("%d.%m.%Y %H:%M"))
        return payload, caption

    async def _ensure_channel(self):
        if self._channel is None:
            self._channel = await channels.ensure_channel(self.client, self.db, "backups")

        return self._channel

    async def _send_backup(self) -> None:
        payload, caption = self._payload()
        target = "me"

        if self.config["target"] == "channel":
            channel = await self._ensure_channel()

            if channel is not None:
                target = channel

        await self.client.send_file(target, payload, caption=caption)

        self.set("last_backup", time.time())
        self.set("last_daily", datetime.now().strftime("%Y-%m-%d"))

        if target != "me":
            await self._prune(target)

    async def _prune(self, channel) -> None:
        """Оставить в канале только последние N бэкапов."""
        keep = self.config["keep"]

        with contextlib.suppress(Exception):
            messages = await self.client.get_messages(channel, limit=keep + 25)
            extra = [message.id for message in messages[keep:]]

            if extra:
                await self.client.delete_messages(channel, extra)
