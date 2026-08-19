"""Резервные копии базы: вручную, по времени суток или по интервалу.

Расписание настраивается кнопками — командой ``.backups``, из меню бота
или при первом запуске, когда Сойка сама спрашивает, когда бэкапить.
"""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/backup_banner.png

import asyncio
import contextlib
import io
import json
import logging
import time
import typing
import zipfile
from datetime import datetime
from pathlib import Path

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

#: Подпись, которую оставляли версии 1.5.1 — при восстановлении её выбрасываем
MARKER = "soika.backup"

#: Карта «модуль → ссылка» внутри архива с модулями
MODS_MAP = "modules.json"

#: Раздел базы с инлайн-ботом. Из копии он не переносится: чужой токен всё
#: равно не заработает, а свой после восстановления заводить заново не нужно
INLINE_OWNER = "soika.inline"
INLINE_KEEP = ("bot_token", "bot_username")

ASK_DELAY = 12


@loader.tds
class BackupMod(loader.Module):
    """Бэкапы базы Сойки: вручную, по расписанию, в отдельный канал"""

    strings = {
        "name": "Бэкап",
        "caption": (
            "🪶 <b>Резервная копия базы Сойки</b>\n"
            "<b>Разделов:</b> {} · <b>снята:</b> {}\n\n"
            "<i>Внутри настройки, модули и доступы — не пересылай её никому.</i>\n"
            "<b>Восстановить:</b> <code>{}restoredb</code> ответом на этот файл"
        ),
        "backup_sent": "🗂 <b>Копия базы отправлена в «Избранное»</b>",
        "mods_caption": (
            "🗂 <b>Бэкап модулей: {}</b>\n\n"
            "<b>Восстановить:</b> <code>{}restoremods</code> ответом на этот файл"
        ),
        "no_mods": "🚫 <b>Своих модулей нет — архивировать нечего</b>",
        "mods_restored": "✅ <b>Модулей восстановлено: {}</b>",
        "bad_mods": "🚫 <b>Это не похоже на архив с модулями Сойки</b>",
        "no_file": "🚫 <b>Ответь на файл с бэкапом</b>",
        "restored": (
            "✅ <b>База восстановлена</b> — разделов: {}\n"
            "<i>Прежняя копия отложена рядом с базой, файл</i> "
            "<code>db-….json.rev1</code>"
        ),
        "bad_file": (
            "🚫 <b>Это не похоже на бэкап базы Сойки</b>\n"
            "<i>Восстанавливать нечего — база осталась как была.</i>"
        ),
        "title": "🗄 <b>Бэкап базы</b>",
        "title_first_run": (
            "🗄 <b>Настроим бэкап базы?</b>\n"
            "<i>В базе — настройки, модули и доступы. Без копии всё это "
            "уедет вместе с сервером.</i>"
        ),
        "mode_line": "🕒 <b>Когда:</b> {}",
        "last_line": "🕘 <b>Последний:</b> {}",
        "keep_line": "📦 <b>Копий в канале:</b> {}",
        "now_line": "<i>На сервере сейчас {}</i>",
        "mode_off": "не делается, только вручную",
        "mode_daily": "каждый день в <code>{}</code>",
        "mode_interval": "каждые <code>{}</code> ч.",
        "target_channel": '📢 <b>Куда:</b> <a href="{}">soika-backups</a>',
        "target_channel_plain": "📢 <b>Куда:</b> в канал soika-backups",
        "target_saved": "💾 <b>Куда:</b> в «Избранное»",
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
        "done": "✅ Бэкап отправлен",
        "failed": "🚫 Не получилось: {}",
        "btn_custom": "✏️ Своё",
        "btn_by_interval": "⏱ По интервалу",
        "btn_by_time": "🕒 По времени",
        "btn_off": "Выключить",
        "btn_channel": "В канал",
        "btn_saved": "В «Избранное»",
        "btn_open": "📂 Открыть канал",
        "btn_now": "⬇️ Бэкап сейчас",
        "btn_close": "🗑 Закрыть",
    }

    strings_en = {
        "caption": (
            "🪶 <b>Soika database backup</b>\n"
            "<b>Sections:</b> {} · <b>taken:</b> {}\n\n"
            "<i>It holds your settings, modules and access lists — do not forward it.</i>\n"
            "<b>Restore:</b> <code>{}restoredb</code> in reply to this file"
        ),
        "backup_sent": "🗂 <b>Database copy sent to Saved Messages</b>",
        "mods_caption": (
            "🗂 <b>Modules backup: {}</b>\n\n"
            "<b>Restore:</b> <code>{}restoremods</code> in reply to this file"
        ),
        "no_mods": "🚫 <b>No user modules to archive</b>",
        "mods_restored": "✅ <b>Modules restored: {}</b>",
        "bad_mods": "🚫 <b>This does not look like a Soika modules archive</b>",
        "no_file": "🚫 <b>Reply to a backup file</b>",
        "restored": (
            "✅ <b>Database restored</b> — sections: {}\n"
            "<i>The previous copy is kept next to the database as</i> "
            "<code>db-….json.rev1</code>"
        ),
        "bad_file": (
            "🚫 <b>This does not look like a Soika backup</b>\n"
            "<i>Nothing to restore — the database is untouched.</i>"
        ),
        "title": "🗄 <b>Database backup</b>",
        "title_first_run": (
            "🗄 <b>Let's set up backups</b>\n"
            "<i>The database keeps settings, modules and access lists. "
            "Without a copy it is gone with the server.</i>"
        ),
        "mode_line": "🕒 <b>When:</b> {}",
        "last_line": "🕘 <b>Last one:</b> {}",
        "keep_line": "📦 <b>Copies kept:</b> {}",
        "now_line": "<i>Server time is {}</i>",
        "mode_off": "never, manual only",
        "mode_daily": "every day at <code>{}</code>",
        "mode_interval": "every <code>{}</code> h.",
        "target_channel": '📢 <b>Where:</b> <a href="{}">soika-backups</a>',
        "target_channel_plain": "📢 <b>Where:</b> soika-backups channel",
        "target_saved": "💾 <b>Where:</b> Saved Messages",
        "never": "<i>never</i>",
        "set_daily": "✅ <b>Backup every day at</b> <code>{}</code>",
        "set_interval": "✅ <b>Backup every</b> <code>{}</code> <b>h.</b>",
        "set_off": "✅ <b>Auto backup disabled</b>",
        "usage": "🚫 <b>Usage:</b> <code>{0}autobackup 03:30</code> / <code>{0}autobackup 6h</code>",
        "ask_time": "Send the time as HH:MM to @{}",
        "bad_time": "🚫 Time must look like 03:30",
        "time_set": "✅ Backup every day at {}",
        "done": "✅ Backup sent",
        "failed": "🚫 Failed: {}",
        "btn_custom": "✏️ Custom",
        "btn_by_interval": "⏱ By interval",
        "btn_by_time": "🕒 By time",
        "btn_off": "Turn off",
        "btn_channel": "To channel",
        "btn_saved": "To Saved",
        "btn_open": "📂 Open channel",
        "btn_now": "⬇️ Back up now",
        "btn_close": "🗑 Close",
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

    async def client_ready(self, client, db):
        # При первой установке спрашиваем про бэкап — молча его не включаем
        if not self.get("setup_asked"):
            utils.spawn(self._ask_on_first_run())

    def _inline_ready(self) -> bool:
        return self.inline is not None and self.inline.init_complete

    # ------------------------------------------------------------------ #
    #  Карточка настроек
    # ------------------------------------------------------------------ #
    def _describe_mode(self) -> str:
        mode = self.config["mode"]

        if mode == "daily":
            return self.strings["mode_daily"].format(self._normalized_time())

        if mode == "interval":
            return self.strings["mode_interval"].format(self.config["interval"])

        return self.strings["mode_off"]

    async def _describe_target(self) -> str:
        if self.config["target"] != "channel":
            return self.strings["target_saved"]

        link = await self._channel_link()

        if not link:
            return self.strings["target_channel_plain"]

        return self.strings["target_channel"].format(link)

    async def _card_text(self, *, first_run: bool = False) -> str:
        last = self.get("last_backup", 0)

        lines = [
            self.strings["mode_line"].format(self._describe_mode()),
            await self._describe_target(),
            self.strings["last_line"].format(
                time.strftime("%d.%m.%Y, %H:%M", time.localtime(last))
                if last
                else self.strings["never"]
            ),
        ]

        # Сколько копий хранить — имеет смысл только для канала
        if self.config["target"] == "channel":
            lines.append(self.strings["keep_line"].format(self.config["keep"]))

        lines += ["", self.strings["now_line"].format(time.strftime("%H:%M"))]
        title = self.strings["title_first_run" if first_run else "title"]

        return title + "\n\n" + "\n".join(lines)

    async def _card_markup(self) -> list[list[dict]]:
        """Первый экран — сетка интервалов, второй — время суток.

        Маркер выбранного пункта заменяет эмодзи, а не добавляется к нему —
        иначе кнопки в ряду разъезжаются по ширине.
        """
        mode = self.config["mode"]
        rows: list[list[dict]] = []

        if mode == "daily":
            current = self._normalized_time()
            choices = [
                {
                    "text": f"{'✅' if choice == current else '🕒'} {choice}",
                    "callback": self._cb_time,
                    "args": (choice,),
                }
                for choice in TIME_CHOICES
            ]
            choices.append({"text": self.strings["btn_custom"], "callback": self._cb_custom_time})
            rows += utils.chunks(choices, 3)
            rows.append(
                [
                    {
                        "text": self.strings["btn_by_interval"],
                        "callback": self._cb_mode,
                        "args": ("interval",),
                    },
                    {
                        "text": f"🚫 {self.strings['btn_off']}",
                        "callback": self._cb_mode,
                        "args": ("off",),
                    },
                ]
            )
        else:
            current = self.config["interval"]
            rows += utils.chunks(
                [
                    {
                        "text": (
                            f"{'✅' if mode == 'interval' and hours == current else '🕰'} {hours} ч"
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
                        "text": self.strings["btn_by_time"],
                        "callback": self._cb_mode,
                        "args": ("daily",),
                    },
                    {
                        "text": f"{'✅' if mode == 'off' else '🚫'} {self.strings['btn_off']}",
                        "callback": self._cb_mode,
                        "args": ("off",),
                    },
                ]
            )

        target = self.config["target"]
        rows.append(
            [
                {
                    "text": f"{'✅' if target == 'channel' else '📢'} {self.strings['btn_channel']}",
                    "callback": self._cb_target,
                    "args": ("channel",),
                },
                {
                    "text": f"{'✅' if target == 'saved' else '💾'} {self.strings['btn_saved']}",
                    "callback": self._cb_target,
                    "args": ("saved",),
                },
            ]
        )

        if target == "channel" and (link := await self._channel_link()):
            rows.append([{"text": self.strings["btn_open"], "url": link}])

        rows.append(
            [
                {"text": self.strings["btn_now"], "callback": self._cb_now},
                {"text": self.strings["btn_close"], "callback": self._cb_close},
            ]
        )

        return rows

    async def _redraw(self, call) -> None:
        await call.edit(await self._card_text(), reply_markup=await self._card_markup())

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
        """Кнопка «Бэкап» в меню бота"""
        if call.data != BACKUP_CALLBACK:
            return

        await call.answer()
        await self.inline.send_pm_unit(
            call.from_user.id,
            await self._card_text(),
            await self._card_markup(),
        )

    # ------------------------------------------------------------------ #
    #  Первый запуск
    # ------------------------------------------------------------------ #
    async def _ask_on_first_run(self) -> None:
        await asyncio.sleep(ASK_DELAY)
        self.set("setup_asked", True)

        text = await self._card_text(first_run=True)

        try:
            if self._inline_ready() and await self.inline.form(
                text,
                message=None,
                reply_markup=await self._card_markup(),
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
        """— прислать копию базы в «Избранное»"""
        payload, caption = self._payload()

        # В файле лежит токен бота и список доверенных, поэтому копия уходит
        # в «Избранное», а не в тот чат, где набрали команду
        await self.client.send_file("me", payload, caption=caption)
        await utils.answer(message, self.strings["backup_sent"])

    @loader.owner
    @loader.command(alias="bkpmods")
    async def backupmodscmd(self, message):
        """— прислать архив с установленными модулями"""
        installed = self.db.get("soika.loader", "installed", {}) or {}
        files = sorted(self.allmodules.external_dir.glob("*.py"))

        if not files and not installed:
            await utils.answer(message, self.strings["no_mods"])
            return

        archive = io.BytesIO()

        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                bundle.writestr(path.name, path.read_bytes())

            bundle.writestr(MODS_MAP, json.dumps(installed, ensure_ascii=False, indent=2))

        archive.seek(0)
        archive.name = f"soika-mods-{time.strftime('%Y%m%d-%H%M')}.zip"

        await utils.answer_file(
            message,
            archive,
            caption=self.strings["mods_caption"].format(
                len(files),
                self.client.dispatcher.prefixes[0],
            ),
        )

    @loader.owner
    @loader.command(alias="rstmods")
    async def restoremodscmd(self, message):
        """— восстановить модули из архива (ответом на файл)"""
        reply = await message.get_reply_message()

        if not reply or not reply.document:
            await utils.answer(message, self.strings["no_file"])
            return

        payload = await reply.download_media(bytes)
        restored = self._unpack_mods(payload)

        if restored is None:
            await utils.answer(message, self.strings["bad_mods"])
            return

        sent = await utils.answer(message, self.strings["mods_restored"].format(restored))
        await self._restart_after(sent)

    def _unpack_mods(self, payload: bytes) -> int | None:
        """Разложить архив по каталогу модулей. ``None`` — архив не наш."""
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
                names = bundle.namelist()

                if MODS_MAP in names:
                    installed = json.loads(bundle.read(MODS_MAP).decode())

                    if isinstance(installed, dict) and all(
                        isinstance(name, str) and utils.check_url(url)
                        for name, url in installed.items()
                    ):
                        self.db.set("soika.loader", "installed", installed)

                target = self.allmodules.external_dir
                restored = 0

                for name in names:
                    if name == MODS_MAP or not name.endswith(".py"):
                        continue

                    # Path(name).name — чтобы архив не разложил файлы куда попало
                    (target / Path(name).name).write_bytes(bundle.read(name))
                    restored += 1
        except (zipfile.BadZipFile, json.JSONDecodeError, OSError, UnicodeDecodeError):
            logger.exception("Архив с модулями не разобрался")
            return None

        return restored

    @loader.owner
    @loader.command()
    async def backupscmd(self, message):
        """— расписание бэкапов: показать и поменять кнопками"""
        text = await self._card_text()

        if self._inline_ready() and await self.inline.form(
            text,
            message=message,
            reply_markup=await self._card_markup(),
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

        data = self._autofix(data)

        if data is None:
            await utils.answer(message, self.strings["bad_file"])
            return

        # Инлайн-бот остаётся тот, что уже поднят на этом аккаунте: Hikka в этом
        # месте просто выбрасывает чужой токен, но тогда после восстановления
        # своей же копии бот заводится заново — поэтому свой сохраняем
        with contextlib.suppress(KeyError):
            data[INLINE_OWNER].pop("bot_token")

        own_bot = {
            key: value
            for key, value in (self.db.get(INLINE_OWNER, None, {}) or {}).items()
            if key in INLINE_KEEP
        }

        # Подпись версий 1.5.1 в базе не нужна
        data.pop(MARKER, None)

        # Прежнюю базу откладываем в ревизию: восстановление перезаписывает всё,
        # и если файл окажется не тем, откатиться будет не на что
        self.db.keep_revision()

        self.db.clear()
        self.db.update(data)

        if own_bot:
            self.db.setdefault(INLINE_OWNER, {}).update(own_bot)

        await self.db.flush()

        sent = await utils.answer(message, self.strings["restored"].format(len(data)))
        await self._restart_after(sent)

    @staticmethod
    def _autofix(data: typing.Any) -> dict | None:
        """Почистить содержимое копии перед восстановлением.

        База выглядит как ``{раздел: {ключ: значение}}``. Всё, что на неё не
        похоже, выбрасываем с записью в лог, а не роняем восстановление — так
        сделано в Hikka (``process_db_autofix``). Если после чистки ничего не
        осталось, это был не бэкап, и трогать базу нельзя.
        """
        if not isinstance(data, dict):
            return None

        clean: dict = {}

        for owner, section in data.items():
            if not isinstance(owner, str) or not isinstance(section, dict):
                logger.warning("Бэкап: выброшен раздел %r — не похож на раздел базы", owner)
                continue

            clean[owner] = {key: value for key, value in section.items() if isinstance(key, str)}

        return clean or None

    async def _restart_after(self, message) -> None:
        """Перезапуститься, чтобы модули подхватили новую базу — как у Hikka."""
        if isinstance(message, list):
            message = message[0]

        try:
            await self.invoke("restart", message=message)
        except Exception:
            logger.exception("Не получилось перезапуститься после восстановления")

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
        caption = self.strings["caption"].format(
            len(self.db),
            time.strftime("%d.%m.%Y %H:%M"),
            self.client.dispatcher.prefixes[0],
        )
        return payload, caption

    async def _ensure_channel(self):
        """Канал бэкапов — на виду, а не в архиве: копии должны быть заметны."""
        if self._channel is None:
            self._channel = await channels.ensure_channel(
                self.client,
                self.db,
                "backups",
                archive=False,
                mute=False,
            )

            # Канал мог быть создан прошлой версией — вытащим из архива один раз
            if self._channel is not None and not self.get("unarchived"):
                self.set("unarchived", True)
                await channels.show_in_list(self.client, self._channel)

        return self._channel

    async def _channel_link(self) -> str:
        """Ссылка на канал бэкапов — сразу на последнюю копию, если она есть."""
        channel = await self._ensure_channel()

        if channel is None:
            return ""

        return await channels.channel_link(self.client, channel, self.get("last_message", 1))

    async def _send_backup(self) -> None:
        payload, caption = self._payload()
        target = "me"

        if self.config["target"] == "channel" and (channel := await self._ensure_channel()):
            target = channel

        sent = await self.client.send_file(target, payload, caption=caption)

        # Кнопка «Открыть канал» ведёт на свежую копию
        if target != "me" and getattr(sent, "id", None):
            self.set("last_message", sent.id)

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
