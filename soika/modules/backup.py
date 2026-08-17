"""Резервные копии базы: вручную, по времени суток или по интервалу.

Расписание настраивается кнопками — командой ``.backups``, из приветствия бота
или при первом запуске, когда Сойка сама спрашивает, когда бэкапить.
"""

import asyncio
import contextlib
import io
import json
import logging
import time
from datetime import datetime

from .. import channels, loader, utils
from ..inline.core import BACKUP_CALLBACK

logger = logging.getLogger(__name__)

MODES = ["off", "daily", "interval"]
TARGETS = ["channel", "saved"]
TIME_RE = r"^([01]?\d|2[0-3]):[0-5]\d$"

#: Набор интервалов как у Hikka — сетка по три кнопки в ряд
INTERVAL_CHOICES = [1, 2, 4, 6, 8, 12, 24, 48, 168]
TIME_CHOICES = ["00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00"]

BANNER = "https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/backup_banner.png"

ASK_DELAY = 12


@loader.tds
class BackupMod(loader.Module):
    """Бэкапы базы Сойки: вручную, по расписанию, в отдельный канал"""

    strings = {
        "name": "Бэкап",
        "caption": "🪶 <b>Бэкап базы Сойки</b>\n<b>Разделов:</b> {} · <b>время:</b> {}",
        "no_file": "🚫 <b>Ответь на файл с бэкапом</b>",
        "restored": "✅ <b>База восстановлена. Перезапусти Сойку:</b> <code>{}restart</code>",
        "bad_file": "🚫 <b>Это не похоже на бэкап базы</b>",
        "card": (
            "🗄 <b>Бэкап базы</b>\n\n"
            "<b>Когда:</b> {mode}\n"
            "<b>Куда:</b> {target}\n"
            "<b>Последний:</b> {last}"
        ),
        "first_run": (
            "🗄 <b>Настроим бэкап базы?</b>\n\n"
            "В базе живут настройки, список модулей, доступы и всё, что "
            "накопят модули. Если сервер умрёт, без бэкапа это не вернуть.\n\n"
            "Сейчас: {mode}, {target}.\n"
            "Поменяй кнопками ниже или оставь как есть."
        ),
        "mode_off": "выключено, только вручную",
        "mode_daily": "каждый день в <code>{}</code>",
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
        "ask_time": "Пришли время в формате ЧЧ:ММ в личку боту @{}",
        "bad_time": "🚫 Нужно время в формате ЧЧ:ММ, например 03:30",
        "time_set": "✅ Бэкап каждый день в {}",
        "doing": "⏳ Делаю бэкап...",
        "done": "✅ Бэкап отправлен",
        "failed": "🚫 Не получилось: {}",
    }

    strings_en = {
        "caption": "🪶 <b>Soika database backup</b>\n<b>Sections:</b> {} · <b>time:</b> {}",
        "no_file": "🚫 <b>Reply to a backup file</b>",
        "restored": "✅ <b>Database restored. Restart Soika:</b> <code>{}restart</code>",
        "bad_file": "🚫 <b>This does not look like a backup</b>",
        "card": (
            "🗄 <b>Database backup</b>\n\n"
            "<b>When:</b> {mode}\n"
            "<b>Where:</b> {target}\n"
            "<b>Last one:</b> {last}"
        ),
        "first_run": (
            "🗄 <b>Let's set up backups</b>\n\n"
            "The database keeps settings, modules and access lists. "
            "Without a backup it is gone with the server.\n\n"
            "Now: {mode}, {target}."
        ),
        "mode_off": "off, manual only",
        "mode_daily": "every day at <code>{}</code>",
        "mode_interval": "every <code>{}</code> h.",
        "target_channel": "to <a href=\"{}\">soika-backups</a>",
        "target_saved": "to Saved Messages",
        "never": "<i>never</i>",
        "set_daily": "✅ <b>Backup every day at</b> <code>{}</code>",
        "set_interval": "✅ <b>Backup every</b> <code>{}</code> <b>h.</b>",
        "set_off": "✅ <b>Auto backup disabled</b>",
        "usage": "🚫 <b>Usage:</b> <code>{0}autobackup 03:30</code> / <code>{0}autobackup 6h</code>",
        "ask_time": "Send the time as HH:MM to @{}",
        "bad_time": "🚫 Time must look like 03:30",
        "time_set": "✅ Backup every day at {}",
        "doing": "⏳ Backing up...",
        "done": "✅ Backup sent",
        "failed": "🚫 Failed: {}",
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
            "03:00",
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

    def _inline_ready(self) -> bool:
        return self.inline is not None and self.inline.init_complete

    async def client_ready(self, client, db):
        # При первой установке спрашиваем про бэкап — молча его не включаем
        if not self.get("setup_asked"):
            utils.spawn(self._ask_on_first_run())

    # ------------------------------------------------------------------ #
    #  Карточка настроек
    # ------------------------------------------------------------------ #
    async def _describe_target(self) -> str:
        if self.config["target"] != "channel":
            return self.strings["target_saved"]

        channel = await self._ensure_channel()
        link = await channels.channel_link(self.client, channel) if channel else "—"
        return self.strings["target_channel"].format(link)

    def _describe_mode(self) -> str:
        mode = self.config["mode"]

        if mode == "daily":
            return self.strings["mode_daily"].format(self._normalized_time())

        if mode == "interval":
            return self.strings["mode_interval"].format(self.config["interval"])

        return self.strings["mode_off"]

    async def _card_text(self, template: str = "card") -> str:
        last = self.get("last_backup", 0)

        return self.strings[template].format(
            mode=self._describe_mode(),
            target=await self._describe_target(),
            last=(
                time.strftime("%d.%m.%Y %H:%M", time.localtime(last))
                if last
                else self.strings["never"]
            ),
        )

    def _card_markup(self) -> list[list[dict]]:
        """Первый экран — сетка интервалов, второй — время суток."""
        mode = self.config["mode"]

        def mark(active: bool, text: str) -> str:
            return f"✅ {text}" if active else text

        rows: list[list[dict]] = []

        if mode == "daily":
            current = self._normalized_time()
            rows += utils.chunks(
                [
                    {
                        "text": mark(choice == current, choice),
                        "callback": self._cb_time,
                        "args": (choice,),
                    }
                    for choice in TIME_CHOICES
                ],
                4,
            )
            rows.append(
                [
                    {"text": "✏️ Своё время", "callback": self._cb_custom_time},
                    {
                        "text": "⏱ По интервалу",
                        "callback": self._cb_mode,
                        "args": ("interval",),
                    },
                ]
            )
        else:
            current = self.config["interval"]
            rows += utils.chunks(
                [
                    {
                        "text": (
                            f"✅ {hours} ч"
                            if mode == "interval" and hours == current
                            else f"🕰 {hours} ч"
                        ),
                        "callback": self._cb_interval,
                        "args": (hours,),
                    }
                    for hours in INTERVAL_CHOICES
                ],
                3,
            )
            rows.append(
                [
                    {
                        "text": mark(mode == "off", "🚫 Никогда"),
                        "callback": self._cb_mode,
                        "args": ("off",),
                    }
                ]
            )
            rows.append(
                [
                    {
                        "text": "🕒 В своё время суток",
                        "callback": self._cb_mode,
                        "args": ("daily",),
                    }
                ]
            )

        target = self.config["target"]
        rows.append(
            [
                {
                    "text": mark(target == "channel", "📢 В канал"),
                    "callback": self._cb_target,
                    "args": ("channel",),
                },
                {
                    "text": mark(target == "saved", "💾 В «Избранное»"),
                    "callback": self._cb_target,
                    "args": ("saved",),
                },
            ]
        )
        rows.append([{"text": "⬇️ Сделать бэкап сейчас", "callback": self._cb_now}])
        rows.append([{"text": "🗑 Закрыть", "callback": self._cb_close}])

        return rows

    async def _redraw(self, call) -> None:
        await call.edit(await self._card_text(), reply_markup=self._card_markup())

    # ------------------------------------------------------------------ #
    #  Кнопки
    # ------------------------------------------------------------------ #
    async def _cb_mode(self, call, mode: str) -> None:
        self.config["mode"] = mode
        self.allmodules.save_config(self)
        await self._redraw(call)

    async def _cb_time(self, call, value: str) -> None:
        self.config["time"] = value
        self.config["mode"] = "daily"
        self.allmodules.save_config(self)
        await self._redraw(call)

    async def _cb_interval(self, call, hours: int) -> None:
        self.config["interval"] = hours
        self.config["mode"] = "interval"
        self.allmodules.save_config(self)
        await self._redraw(call)

    async def _cb_target(self, call, target: str) -> None:
        self.config["target"] = target
        self.allmodules.save_config(self)
        await self._redraw(call)

    async def _cb_custom_time(self, call) -> None:
        async def receive(bot_message) -> None:
            value = (bot_message.text or "").strip()

            try:
                self.config["time"] = value
            except loader.validators.ValidationError:
                await bot_message.answer(self.strings["bad_time"])
                return

            self.config["mode"] = "daily"
            self.allmodules.save_config(self)
            await bot_message.answer(self.strings["time_set"].format(self._normalized_time()))
            await self._redraw(call)

        self.inline.set_fsm_state(self.client.tg_id, {"callback": receive})
        await call.answer(
            self.strings["ask_time"].format(self.inline.bot_username),
            show_alert=True,
        )

    async def _cb_now(self, call) -> None:
        try:
            await self._send_backup()
        except Exception as e:  # noqa: BLE001 — покажем причину прямо в кнопке
            await call.answer(self.strings["failed"].format(e), show_alert=True)
            return

        await self._redraw(call)
        await call.answer(self.strings["done"], show_alert=True)

    async def _cb_close(self, call) -> None:
        await call.delete()

    @loader.callback_handler()
    async def backup_settings_callback_handler(self, call):
        """Кнопка «Бэкап базы» в приветствии бота"""
        if call.data != BACKUP_CALLBACK:
            return

        await call.answer()
        await self.inline.send_pm_unit(
            call.from_user.id,
            await self._card_text(),
            self._card_markup(),
        )

    # ------------------------------------------------------------------ #
    #  Первый запуск
    # ------------------------------------------------------------------ #
    async def _ask_on_first_run(self) -> None:
        await asyncio.sleep(ASK_DELAY)
        self.set("setup_asked", True)

        text = await self._card_text("first_run")

        try:
            if self._inline_ready() and await self.inline.form(
                text,
                message=None,
                reply_markup=self._card_markup(),
                photo=BANNER,
            ):
                return

            prefix = self.client.dispatcher.prefixes[0]
            await self.client.send_message(
                "me",
                f"{text}\n\n{self.strings['usage'].format(prefix)}",
            )
        except Exception:
            logger.exception("Не смог спросить про бэкап при первом запуске")

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
        """— расписание бэкапов: показать и поменять кнопками"""
        text = await self._card_text()

        if self._inline_ready() and await self.inline.form(
            text,
            message=message,
            reply_markup=self._card_markup(),
            photo=BANNER,
        ):
            return

        prefix = self.client.dispatcher.prefixes[0]
        await utils.answer(message, f"{text}\n\n{self.strings['usage'].format(prefix)}")

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
            await utils.answer(message, self.strings["set_daily"].format(self._normalized_time()))
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
        if self.get("last_daily") == now.strftime("%Y-%m-%d"):
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
