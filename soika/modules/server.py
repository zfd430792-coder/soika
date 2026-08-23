"""Состояние сервера, на котором живёт Сойка: нагрузка, память, диски, сеть.

Главный вопрос, ради которого модуль написан: тормозит сервер или Telegram.
Поэтому карточка показывает и то и другое рядом и сразу говорит вывод.
"""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/server_banner.png

import contextlib
import platform
import time
import typing

import psutil

from .. import loader, utils

#: Сколько секунд замеряем CPU. Меньше — цифра врёт, больше — ждать ответа
CPU_SAMPLE = 0.4

#: Пороги, за которыми показатель считается тревожным
WARN = 75
CRIT = 90

#: Задержка до Telegram, выше которой связь считается медленной (мс)
SLOW_PING = 400

#: Псевдофайловые системы — в списке дисков они только мешают
SKIP_FS = {
    "autofs",
    "binfmt_misc",
    "bpf",
    "cgroup",
    "cgroup2",
    "configfs",
    "debugfs",
    "devpts",
    "devtmpfs",
    "fuse.gvfsd-fuse",
    "fusectl",
    "hugetlbfs",
    "mqueue",
    "overlay",
    "proc",
    "pstore",
    "securityfs",
    "squashfs",
    "sysfs",
    "tmpfs",
    "tracefs",
}

#: Ширина полоски прогресса в символах
BAR = 10


@loader.tds
class ServerMod(loader.Module):
    """Смотреть сервер, не заходя на него: нагрузка, память, диски, сеть"""

    strings = {
        "name": "Сервер",
        "card": (
            "🖥 <b>Сервер</b>  ·  <code>{host}</code>\n\n"
            "{verdict}\n\n"
            "<b>Нагрузка</b>\n"
            "{cpu_row}\n"
            "{ram_row}\n"
            "{swap_row}"
            "{disk_row}\n\n"
            "<b>Связь с Telegram</b>\n"
            "🏓 <b>Задержка:</b> {ping}\n\n"
            "<b>Система</b>\n"
            "{load_row}"
            "{temp_row}"
            "⏰ <b>Сервер работает:</b> {boot}\n"
            "🪶 <b>Сойка работает:</b> {uptime} · {self_ram} МБ\n"
            "💾 <b>Площадка:</b> {platform}"
        ),
        "row": "{dot} <b>{label}</b>  <code>{bar}</code>  {value}",
        "verdict_ok": "✅ <b>Всё в порядке.</b> И сервер, и связь спокойны",
        "verdict_tg": (
            "📡 <b>Сервер спокоен — дело в Telegram.</b>\n"
            "<i>Нагрузки нет, а ответ идёт {ping}. Ждать или сменить сеть</i>"
        ),
        "verdict_down": (
            "📵 <b>Telegram не отвечает, а сервер спокоен.</b>\n"
            "<i>Нагрузки нет — значит оборвалась связь, а не машина</i>"
        ),
        "verdict_server": ("🔥 <b>Сервер задыхается — дело в нём.</b>\n<i>Перегружено: {what}</i>"),
        "verdict_both": (
            "🔥 <b>Сервер перегружен, и связь медленная.</b>\n<i>Перегружено: {what}</i>"
        ),
        "verdict_busy": (
            "⚠️ <b>Сервер под нагрузкой, но до Telegram доходит быстро.</b>\n"
            "<i>Загружено: {what}</i>"
        ),
        "what_cpu": "процессор",
        "what_ram": "память",
        "what_swap": "подкачка",
        "what_disk": "диск",
        "what_load": "очередь задач",
        "procs": "🧠 <b>Процессы</b>  ·  <i>{count} шт., сортировка по {by}</i>\n\n{body}",
        "proc_row": "{dot} <code>{cpu:>5}%</code> <code>{ram:>7}</code>  {name}",
        "by_cpu": "процессору",
        "by_ram": "памяти",
        "disks": "💾 <b>Диски</b>\n\n{body}",
        "disk_row": (
            "{dot} <b>{mount}</b>  <code>{bar}</code>  {percent} %\n"
            "<i>занято {used} · свободно {free} · {fstype}</i>"
        ),
        "no_disks": "<i>Не нашлось ни одного обычного диска</i>",
        "net": (
            "🌐 <b>Сеть</b>\n\n"
            "⬇️ <b>Сейчас:</b> {rx_rate}/с\n"
            "⬆️ <b>Сейчас:</b> {tx_rate}/с\n\n"
            "⬇️ <b>Принято с загрузки:</b> {rx}\n"
            "⬆️ <b>Отправлено с загрузки:</b> {tx}\n\n"
            "🔌 <b>Соединений:</b> {conns}"
        ),
        "watch_on": "🔔 <b>Слежение включено</b>\n\n{limits}",
        "watch_off": "🔕 <b>Слежение выключено</b>",
        "watch_limits": (
            "<i>Бот напишет, если показатель продержится выше порога {holds} мин подряд:</i>\n"
            "🔄 <b>CPU:</b> {cpu} %\n"
            "👾 <b>RAM:</b> {ram} %\n"
            "💾 <b>Диск:</b> {disk} %"
        ),
        "alert": "🔥 <b>Сервер под нагрузкой</b>\n\n{body}\n\n<i>Держится {held} мин</i>",
        "alert_row": "{dot} <b>{label}:</b> {value} <i>(порог {limit} %)</i>",
        "recovered": "✅ <b>Отпустило</b>\n\n{body}",
        "recovered_row": "🟢 <b>{label}:</b> {value}",
        "btn_refresh": "🔄 Обновить",
        "btn_procs": "🧠 Процессы",
        "btn_disks": "💾 Диски",
        "btn_net": "🌐 Сеть",
        "btn_back": "◀️ Назад",
        "btn_close": "✖️ Закрыть",
        "btn_watch_on": "🔔 Следить",
        "btn_watch_off": "🔕 Не следить",
        "failed": "❌ <b>Не удалось снять показания:</b> <code>{}</code>",
    }

    strings_en = {
        "verdict_ok": "✅ <b>All good.</b> Both the server and the link are calm",
        "verdict_tg": (
            "📡 <b>The server is fine — it's Telegram.</b>\n"
            "<i>No load here, but the reply takes {ping}</i>"
        ),
        "verdict_down": (
            "📵 <b>Telegram is silent, the server is calm.</b>\n"
            "<i>No load here — the link broke, not the machine</i>"
        ),
        "verdict_server": "🔥 <b>The server is choking.</b>\n<i>Overloaded: {what}</i>",
        "verdict_both": "🔥 <b>Server overloaded and the link is slow.</b>\n<i>Overloaded: {what}</i>",
        "verdict_busy": (
            "⚠️ <b>Server is busy, but Telegram answers fast.</b>\n<i>Loaded: {what}</i>"
        ),
        "what_cpu": "CPU",
        "what_ram": "memory",
        "what_swap": "swap",
        "what_disk": "disk",
        "what_load": "task queue",
        "by_cpu": "CPU",
        "by_ram": "memory",
        "no_disks": "<i>No ordinary disks found</i>",
        "watch_off": "🔕 <b>Watching disabled</b>",
        "btn_refresh": "🔄 Refresh",
        "btn_procs": "🧠 Processes",
        "btn_disks": "💾 Disks",
        "btn_net": "🌐 Network",
        "btn_back": "◀️ Back",
        "btn_close": "✖️ Close",
        "btn_watch_on": "🔔 Watch",
        "btn_watch_off": "🔕 Stop watching",
        "failed": "❌ <b>Could not read the metrics:</b> <code>{}</code>",
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "alerts",
            False,
            "Писать в бота, когда сервер уходит под нагрузку",
            validator=loader.validators.Boolean(),
        ),
        loader.ConfigValue(
            "cpu_limit",
            90,
            "Порог по процессору, %",
            validator=loader.validators.Integer(minimum=50, maximum=100),
        ),
        loader.ConfigValue(
            "ram_limit",
            90,
            "Порог по памяти, %",
            validator=loader.validators.Integer(minimum=50, maximum=100),
        ),
        loader.ConfigValue(
            "disk_limit",
            90,
            "Порог по диску, %",
            validator=loader.validators.Integer(minimum=50, maximum=100),
        ),
        loader.ConfigValue(
            "hold",
            3,
            "Сколько минут подряд показатель должен быть выше порога, чтобы бот написал",
            validator=loader.validators.Integer(minimum=1, maximum=60),
        ),
        loader.ConfigValue(
            "top",
            8,
            "Сколько процессов показывать в списке",
            validator=loader.validators.Integer(minimum=3, maximum=25),
        ),
    )

    def __init__(self) -> None:
        #: Счётчики сети с прошлого замера — из них считается скорость
        self._net_mark: tuple[float, int, int] | None = None
        #: Сколько проверок подряд показатель висит выше порога
        self._over: dict[str, int] = {}
        #: О чём уже написали, чтобы не повторяться каждую минуту
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ #
    #  Команды
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command(alias="srv")
    async def servercmd(self, message):
        """— карточка сервера: нагрузка, память, диски и связь с Telegram"""
        await self._show(message, await self._card())

    @loader.owner
    @loader.command(alias="proc")
    async def topcmd(self, message):
        """[ram] — самые прожорливые процессы, по умолчанию по процессору"""
        by_ram = utils.get_args_raw(message).strip().lower() in {"ram", "мем", "память"}
        await self._show(message, await self._processes(by_ram=by_ram))

    @loader.owner
    @loader.command(alias="df")
    async def diskcmd(self, message):
        """— сколько занято на каждом диске"""
        await self._show(message, await self._disks())

    @loader.owner
    @loader.command()
    async def netcmd(self, message):
        """— сколько трафика прошло и какая скорость сейчас"""
        await self._show(message, await self._network())

    @loader.owner
    @loader.command()
    async def watchcmd(self, message):
        """— включить или выключить сообщения о нагрузке"""
        self.config["alerts"] = not self.config["alerts"]
        self.allmodules.save_config(self)
        self._reset_alerts()

        await utils.answer(message, self._watch_text())

    # ------------------------------------------------------------------ #
    #  Отрисовка карточек
    # ------------------------------------------------------------------ #
    async def _show(self, message, text: str) -> None:
        """Показать карточку кнопками, а без бота — простым текстом."""
        if self._inline_ready() and await self.inline.form(
            text,
            message=message,
            reply_markup=self._markup(),
        ):
            return

        await utils.answer(message, text)

    async def _card(self) -> str:
        try:
            stats = await utils.run_sync(self._collect)
        except Exception as e:  # noqa: BLE001 — покажем причину вместо падения
            return self.strings["failed"].format(utils.escape_html(f"{type(e).__name__}: {e}"))

        latency = await self._latency()

        cores = _plural(stats["cores"], "ядро", "ядра", "ядер")

        rows = [
            self._row("CPU", stats["cpu"], f"{stats['cpu']:g} %  ·  {cores}"),
            self._row(
                "RAM",
                stats["ram"],
                f"{_size(stats['ram_used'])} / {_size(stats['ram_total'])}",
            ),
        ]

        swap_row = ""

        if stats["swap_total"]:
            swap_row = (
                self._row(
                    "Swap",
                    stats["swap"],
                    f"{_size(stats['swap_used'])} / {_size(stats['swap_total'])}",
                )
                + "\n"
            )

        # Процент у диска psutil считает как df — от занятого плюс свободного,
        # а не от полного размера. Поэтому рядом печатаем не размер тома,
        # а занято и свободно: иначе цифры выглядели бы противоречиво
        disk_row = self._row(
            "Диск",
            stats["disk"],
            f"{stats['disk']:g} %  ·  свободно {_size(stats['disk_free'])}",
        )

        load_row = ""

        if stats["load"] is not None:
            one, five, fifteen = stats["load"]
            load_row = (
                f"⚖️ <b>Средняя нагрузка:</b> <code>{one:.2f} · {five:.2f} · {fifteen:.2f}</code>\n"
            )

        temp_row = ""

        if stats["temp"] is not None:
            temp_row = f"🌡 <b>Температура:</b> {stats['temp']:.0f} °C\n"

        return self.strings["card"].format(
            host=utils.escape_html(stats["host"]),
            verdict=self._verdict(stats, latency),
            cpu_row=rows[0],
            ram_row=rows[1],
            swap_row=swap_row,
            disk_row=disk_row,
            ping=self._ping_text(latency),
            load_row=load_row,
            temp_row=temp_row,
            boot=utils.format_timedelta(stats["boot"]),
            uptime=utils.formatted_uptime(),
            self_ram=utils.get_ram_usage(),
            platform=utils.get_named_platform(),
        )

    def _row(self, label: str, percent: float, value: str) -> str:
        return self.strings["row"].format(
            dot=_dot(percent),
            label=label,
            bar=_bar(percent),
            value=value,
        )

    def _ping_text(self, latency: float | None) -> str:
        if latency is None:
            return "<i>не ответил</i>"

        return f"<code>{latency:.0f} мс</code> {_dot(latency / SLOW_PING * 100)}"

    def _verdict(self, stats: dict, latency: float | None) -> str:
        """Главный ответ: виноват сервер или Telegram."""
        loaded = self._loaded(stats)
        slow = latency is None or latency >= SLOW_PING

        if loaded and slow:
            return self.strings["verdict_both"].format(what=", ".join(loaded))

        if loaded:
            key = "verdict_server" if self._critical(stats) else "verdict_busy"
            return self.strings[key].format(what=", ".join(loaded))

        if latency is None:
            return self.strings["verdict_down"]

        if slow:
            return self.strings["verdict_tg"].format(ping=self._ping_text(latency))

        return self.strings["verdict_ok"]

    def _loaded(self, stats: dict) -> list[str]:
        """Список того, что сейчас нагружено, человеческими словами."""
        found = []

        if stats["cpu"] >= WARN:
            found.append(self.strings["what_cpu"])

        if stats["ram"] >= WARN:
            found.append(self.strings["what_ram"])

        if stats["swap"] >= WARN and stats["swap_total"]:
            found.append(self.strings["what_swap"])

        if stats["disk"] >= CRIT:
            found.append(self.strings["what_disk"])

        # Очередь вдвое длиннее числа ядер значит, что процессы стоят и ждут
        if stats["load"] is not None and stats["cores"] and stats["load"][0] / stats["cores"] >= 2:
            found.append(self.strings["what_load"])

        return found

    @staticmethod
    def _critical(stats: dict) -> bool:
        return max(stats["cpu"], stats["ram"], stats["disk"]) >= CRIT

    async def _processes(self, *, by_ram: bool) -> str:
        try:
            procs = await utils.run_sync(self._top, by_ram)
        except Exception as e:  # noqa: BLE001 — покажем причину вместо падения
            return self.strings["failed"].format(utils.escape_html(f"{type(e).__name__}: {e}"))

        body = "\n".join(
            self.strings["proc_row"].format(
                dot=_dot(proc["cpu"]),
                cpu=f"{proc['cpu']:.1f}",
                ram=_size(proc["ram"]),
                name=utils.escape_html(proc["name"]),
            )
            for proc in procs
        )

        return self.strings["procs"].format(
            count=len(procs),
            by=self.strings["by_ram" if by_ram else "by_cpu"],
            body=body,
        )

    async def _disks(self) -> str:
        try:
            disks = await utils.run_sync(self._partitions)
        except Exception as e:  # noqa: BLE001 — покажем причину вместо падения
            return self.strings["failed"].format(utils.escape_html(f"{type(e).__name__}: {e}"))

        if not disks:
            return self.strings["disks"].format(body=self.strings["no_disks"])

        body = "\n\n".join(
            self.strings["disk_row"].format(
                dot=_dot(disk["percent"]),
                mount=utils.escape_html(disk["mount"]),
                bar=_bar(disk["percent"]),
                used=_size(disk["used"]),
                free=_size(disk["free"]),
                percent=f"{disk['percent']:g}",
                fstype=utils.escape_html(disk["fstype"]),
            )
            for disk in disks
        )

        return self.strings["disks"].format(body=body)

    async def _network(self) -> str:
        try:
            net = await utils.run_sync(self._net)
        except Exception as e:  # noqa: BLE001 — покажем причину вместо падения
            return self.strings["failed"].format(utils.escape_html(f"{type(e).__name__}: {e}"))

        return self.strings["net"].format(
            rx_rate=_size(net["rx_rate"]),
            tx_rate=_size(net["tx_rate"]),
            rx=_size(net["rx"]),
            tx=_size(net["tx"]),
            conns=net["conns"],
        )

    def _watch_text(self) -> str:
        if not self.config["alerts"]:
            return self.strings["watch_off"]

        return self.strings["watch_on"].format(
            limits=self.strings["watch_limits"].format(
                holds=self.config["hold"],
                cpu=self.config["cpu_limit"],
                ram=self.config["ram_limit"],
                disk=self.config["disk_limit"],
            )
        )

    # ------------------------------------------------------------------ #
    #  Кнопки
    # ------------------------------------------------------------------ #
    def _inline_ready(self) -> bool:
        return self.inline is not None and self.inline.init_complete

    def _markup(self) -> list:
        watching = self.config["alerts"]

        return [
            [{"text": self.strings["btn_refresh"], "callback": self._cb_card}],
            [
                {"text": self.strings["btn_procs"], "callback": self._cb_procs},
                {"text": self.strings["btn_disks"], "callback": self._cb_disks},
                {"text": self.strings["btn_net"], "callback": self._cb_net},
            ],
            [
                {
                    "text": self.strings["btn_watch_off" if watching else "btn_watch_on"],
                    "callback": self._cb_watch,
                },
                {"text": self.strings["btn_close"], "callback": self._cb_close},
            ],
        ]

    def _back_markup(self) -> list:
        return [
            [
                {"text": self.strings["btn_back"], "callback": self._cb_card},
                {"text": self.strings["btn_close"], "callback": self._cb_close},
            ]
        ]

    async def _cb_card(self, call) -> None:
        await call.edit(await self._card(), reply_markup=self._markup())

    async def _cb_procs(self, call) -> None:
        await call.edit(await self._processes(by_ram=False), reply_markup=self._back_markup())

    async def _cb_disks(self, call) -> None:
        await call.edit(await self._disks(), reply_markup=self._back_markup())

    async def _cb_net(self, call) -> None:
        await call.edit(await self._network(), reply_markup=self._back_markup())

    async def _cb_watch(self, call) -> None:
        self.config["alerts"] = not self.config["alerts"]
        self.allmodules.save_config(self)
        self._reset_alerts()

        await call.answer(utils.remove_html(self._watch_text()).split("\n")[0])
        await call.edit(await self._card(), reply_markup=self._markup())

    async def _cb_close(self, call) -> None:
        await call.delete()

    # ------------------------------------------------------------------ #
    #  Слежение
    # ------------------------------------------------------------------ #
    @loader.loop(interval=60, autostart=True, wait_before=True)
    async def watchdog(self):
        """Раз в минуту смотрит на показатели и пишет в бота, если припекло."""
        if not self.config["alerts"] or not self._inline_ready():
            return

        try:
            stats = await utils.run_sync(self._collect)
        except Exception:  # noqa: BLE001 — слежение не должно ронять юзербот
            return

        limits = {
            "cpu": (self.strings["what_cpu"], stats["cpu"], self.config["cpu_limit"]),
            "ram": (self.strings["what_ram"], stats["ram"], self.config["ram_limit"]),
            "disk": (self.strings["what_disk"], stats["disk"], self.config["disk_limit"]),
        }

        hold = self.config["hold"]
        triggered = []
        calmed = []

        for key, (label, value, limit) in limits.items():
            if value >= limit:
                self._over[key] = self._over.get(key, 0) + 1

                if self._over[key] >= hold and key not in self._warned:
                    self._warned.add(key)
                    triggered.append((label, value, limit))

                continue

            self._over[key] = 0

            if key in self._warned:
                self._warned.discard(key)
                calmed.append((label, value))

        if triggered:
            await self._alert(triggered, hold)

        if calmed:
            await self._calmed(calmed)

    async def _alert(self, rows: list[tuple[str, float, int]], held: int) -> None:
        body = "\n".join(
            self.strings["alert_row"].format(
                dot=_dot(value),
                label=label.capitalize(),
                value=f"{value:g} %",
                limit=limit,
            )
            for label, value, limit in rows
        )

        await self._notify(self.strings["alert"].format(body=body, held=held))

    async def _calmed(self, rows: list[tuple[str, float]]) -> None:
        body = "\n".join(
            self.strings["recovered_row"].format(label=label.capitalize(), value=f"{value:g} %")
            for label, value in rows
        )

        await self._notify(self.strings["recovered"].format(body=body))

    async def _notify(self, text: str) -> None:
        """Написать владельцу в личку бота, а если бот молчит — в «Избранное»."""
        if self._inline_ready() and await self.inline.send_pm_unit(
            self.client.tg_id,
            text,
            self._back_markup(),
        ):
            return

        await self.client.send_message("me", text)

    def _reset_alerts(self) -> None:
        self._over.clear()
        self._warned.clear()

    async def on_unload(self) -> None:
        self.watchdog.stop()

    # ------------------------------------------------------------------ #
    #  Замеры
    # ------------------------------------------------------------------ #
    async def _latency(self) -> float | None:
        """Сколько идёт ответ от Telegram. None — не ответил вовсе."""
        start = time.perf_counter_ns()

        try:
            await self.client.get_me()
        except Exception:  # noqa: BLE001 — молчание тоже ответ, так и покажем
            return None

        return (time.perf_counter_ns() - start) / 10**6

    def _collect(self) -> dict:
        """Снять показания сервера. Блокирующая — только через run_sync."""
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")

        return {
            "host": _hostname(),
            "cpu": psutil.cpu_percent(interval=CPU_SAMPLE),
            "cores": psutil.cpu_count() or 0,
            "ram": memory.percent,
            "ram_used": memory.total - memory.available,
            "ram_total": memory.total,
            "swap": swap.percent,
            "swap_used": swap.used,
            "swap_total": swap.total,
            "disk": disk.percent,
            "disk_used": disk.used,
            "disk_free": disk.free,
            "load": _load(),
            "temp": _temperature(),
            "boot": time.time() - psutil.boot_time(),
        }

    def _top(self, by_ram: bool) -> list[dict]:
        """Самые прожорливые процессы. Блокирующая — только через run_sync.

        ``cpu_percent`` считает загрузку с прошлого своего вызова, поэтому
        первый ответ всегда нулевой. Значит, обходим список дважды: сначала
        заводим счётчики, ждём, и только потом снимаем показания.
        """
        watched = []

        for proc in psutil.process_iter():
            with contextlib.suppress(Exception):
                proc.cpu_percent()
                watched.append(proc)

        time.sleep(CPU_SAMPLE)

        procs = []
        cores = psutil.cpu_count() or 1

        for proc in watched:
            try:
                with proc.oneshot():
                    procs.append(
                        {
                            "name": proc.name() or "?",
                            # psutil считает 100% на ядро, приводим к нагрузке всей машины
                            "cpu": proc.cpu_percent() / cores,
                            "ram": proc.memory_info().rss,
                        }
                    )
            except Exception:  # noqa: BLE001 — процесс мог умереть на ходу
                continue

        procs.sort(key=lambda proc: proc["ram" if by_ram else "cpu"], reverse=True)
        return procs[: self.config["top"]]

    @staticmethod
    def _partitions() -> list[dict]:
        """Обычные диски без служебных файловых систем."""
        disks = []
        seen = set()

        for part in psutil.disk_partitions(all=False):
            if part.fstype in SKIP_FS or part.device in seen:
                continue

            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:  # noqa: BLE001 — примонтировано, но не читается
                continue

            seen.add(part.device)
            disks.append(
                {
                    "mount": part.mountpoint,
                    "fstype": part.fstype or "?",
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                }
            )

        return disks

    def _net(self) -> dict:
        """Трафик с загрузки и скорость с прошлого замера."""
        counters = psutil.net_io_counters()
        now = time.monotonic()

        rx_rate = tx_rate = 0.0

        if self._net_mark is not None:
            was, rx, tx = self._net_mark
            passed = now - was

            if passed > 0:
                rx_rate = max(0.0, (counters.bytes_recv - rx) / passed)
                tx_rate = max(0.0, (counters.bytes_sent - tx) / passed)

        self._net_mark = (now, counters.bytes_recv, counters.bytes_sent)

        try:
            conns = len(psutil.net_connections(kind="inet"))
        except Exception:  # noqa: BLE001 — без прав root список бывает закрыт
            conns = 0

        return {
            "rx": counters.bytes_recv,
            "tx": counters.bytes_sent,
            "rx_rate": rx_rate,
            "tx_rate": tx_rate,
            "conns": conns,
        }


# --------------------------------------------------------------------------- #
#  Оформление
# --------------------------------------------------------------------------- #
def _bar(percent: float) -> str:
    """Полоска на BAR символов: ▰ занято, ▱ свободно."""
    filled = min(BAR, max(0, round(percent / 100 * BAR)))
    return "▰" * filled + "▱" * (BAR - filled)


def _dot(percent: float) -> str:
    """Цвет показателя: зелёный до WARN, жёлтый до CRIT, дальше красный."""
    if percent >= CRIT:
        return "🔴"

    return "🟡" if percent >= WARN else "🟢"


def _size(value: float) -> str:
    """Байты человеческими единицами: до мегабайт без дробей, дальше с одной."""
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit in {"Б", "КБ"} else f"{value:.1f} {unit}"

        value /= 1024

    return f"{value:.1f} ТБ"


def _plural(count: int, one: str, few: str, many: str) -> str:
    """«1 ядро», «2 ядра», «8 ядер» — иначе карточка выглядит неряшливо."""
    tail, hundred = count % 10, count % 100

    if tail == 1 and hundred != 11:
        word = one
    elif tail in {2, 3, 4} and hundred not in {12, 13, 14}:
        word = few
    else:
        word = many

    return f"{count} {word}"


def _hostname() -> str:
    with contextlib.suppress(Exception):
        if name := platform.node():
            return name

    return "сервер"


def _load() -> tuple[float, float, float] | None:
    """Средняя нагрузка за 1/5/15 минут. На Windows её нет."""
    try:
        return psutil.getloadavg()
    except (AttributeError, OSError):
        return None


def _temperature() -> float | None:
    """Самый горячий датчик. На VPS датчиков обычно нет вовсе."""
    try:
        sensors: dict[str, list[typing.Any]] = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None

    readings = [entry.current for group in sensors.values() for entry in group if entry.current]

    return max(readings) if readings else None
