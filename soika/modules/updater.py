"""Обновление из git, перезапуск и уведомления о новых версиях."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/update_banner.png

import asyncio
import contextlib
import logging
import os
import re
import sys
import time

from .. import configuration, loader, utils
from ..version import DEFAULT_REPO, __version_str__

logger = logging.getLogger(__name__)

CORE = "soika.core"

#: Сколько коммитов показываем в списке изменений
CHANGELOG_LIMIT = 8

#: Кнопка «Обновить» под уведомлением должна жить долго — неделя
NOTIFY_TTL = 7 * 24 * 3600

#: Первая проверка обновлений после старта: даём боту подняться
FIRST_CHECK_DELAY = 120

#: Версия в исходниках — читаем её и у себя, и на сервере
VERSION_RE = re.compile(r"__version__\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")

#: Баннер уведомления об обновлении
DEFAULT_BANNER = (
    "https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/update_banner.png"
)


@loader.tds
class UpdaterMod(loader.Module):
    """Обновляет Сойку, перезапускает процесс и следит за новыми версиями"""

    strings = {
        "name": "Обновление",
        "restarting": "🪶 <b>Перезапускаюсь...</b>",
        "updating": "🪶 <b>Обновляюсь...</b>",
        "no_git": (
            "🚫 <b>Это не git-репозиторий или не настроен remote.</b>\n"
            "<i>Обновляться неоткуда — переустанови Сойку через install.sh</i>"
        ),
        "up_to_date": "✅ <b>Уже последняя версия</b> — <b>Сойка {}</b>",
        "deps": "🪶 <b>Ставлю зависимости...</b>",
        "failed": "🚫 <b>Обновление не удалось:</b>\n<code>{}</code>",
        "available": (
            "🪶 <b>Вышло обновление Сойки</b>\n\n"
            "{versions}\n"
            "📦 <b>Новых коммитов:</b> {count}\n\n"
            "{changelog}"
        ),
        "auto_updating": "🤖 <b>Нашлось обновление — обновляюсь сам</b>\n\n{versions}\n\n{changelog}",
        "updated": "✅ <b>Сойка обновлена</b>\n\n{versions}\n\n{changelog}",
        "versions_new": "🕸 <b>Версия:</b> <code>{}</code> → <code>{}</code>",
        "versions_same": "🕸 <b>Версия:</b> <code>{}</code> <i>(номер не менялся)</i>",
        "changelog": "📝 <b>Что изменилось:</b>\n{}",
        "changelog_more": "\n<i>…и ещё коммитов: {}</i>",
        "changelog_empty": "<i>Список изменений недоступен</i>",
        "check_now": "🔎 <b>Проверяю обновления...</b>",
        "no_updates": "✅ <b>Обновлений нет</b> — <b>Сойка {}</b>",
        "auto_on": "🤖 <b>Автообновление включено</b> — буду обновляться сам",
        "auto_off": "✋ <b>Автообновление выключено</b> — только по команде",
        "later": "Ладно, потом",
        "btn_update": "⬇️ Обновить",
        "btn_later": "🚫 Позже",
        "btn_commits": "📖 Коммиты",
        "hint": "\n\n<i>Обновиться:</i> <code>{}update</code>",
    }

    strings_en = {
        "restarting": "🪶 <b>Restarting...</b>",
        "updating": "🪶 <b>Updating...</b>",
        "no_git": "🚫 <b>Not a git repository or no remote configured</b>",
        "up_to_date": "✅ <b>Already up to date</b> — <b>Soika {}</b>",
        "deps": "🪶 <b>Installing requirements...</b>",
        "failed": "🚫 <b>Update failed:</b>\n<code>{}</code>",
        "available": (
            "🪶 <b>Soika update available</b>\n\n"
            "{versions}\n"
            "📦 <b>New commits:</b> {count}\n\n"
            "{changelog}"
        ),
        "auto_updating": "🤖 <b>Found an update, updating myself</b>\n\n{versions}\n\n{changelog}",
        "updated": "✅ <b>Soika updated</b>\n\n{versions}\n\n{changelog}",
        "versions_new": "🕸 <b>Version:</b> <code>{}</code> → <code>{}</code>",
        "versions_same": "🕸 <b>Version:</b> <code>{}</code> <i>(number unchanged)</i>",
        "changelog": "📝 <b>What changed:</b>\n{}",
        "changelog_more": "\n<i>…and {} more commits</i>",
        "changelog_empty": "<i>Changelog is not available</i>",
        "check_now": "🔎 <b>Checking for updates...</b>",
        "no_updates": "✅ <b>No updates</b> — <b>Soika {}</b>",
        "auto_on": "🤖 <b>Auto update enabled</b>",
        "auto_off": "✋ <b>Auto update disabled</b>",
        "later": "Fine, later",
        "btn_update": "⬇️ Update",
        "btn_later": "🚫 Later",
        "btn_commits": "📖 Commits",
        "hint": "\n\n<i>To update:</i> <code>{}update</code>",
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "check",
            True,
            "Проверять обновления автоматически",
            validator=loader.validators.Boolean(),
        ),
        loader.ConfigValue(
            "interval",
            60,
            "Как часто проверять обновления, минут",
            validator=loader.validators.Integer(minimum=5, maximum=1440),
        ),
        loader.ConfigValue(
            "auto_update",
            False,
            "Обновляться самостоятельно, не спрашивая",
            validator=loader.validators.Boolean(),
        ),
        loader.ConfigValue(
            "banner_url",
            DEFAULT_BANNER,
            "Баннер уведомления об обновлении. Пусто — только текст",
            validator=loader.validators.Union(
                loader.validators.NoneType(),
                loader.validators.Link(),
            ),
        ),
    )

    #: Первую проверку после старта делаем с задержкой, дальше — по интервалу
    _checked_once = False

    async def client_ready(self, client, db):
        self.update_checker.interval = self.config["interval"] * 60

        # После обновления рассказываем, что именно приехало
        if self.get("update_report"):
            utils.spawn(self._report_update())

    async def config_complete(self):
        with contextlib.suppress(Exception):
            self.update_checker.interval = self.config["interval"] * 60

    # ------------------------------------------------------------------ #
    #  Команды
    # ------------------------------------------------------------------ #
    @loader.owner
    @loader.command()
    async def restartcmd(self, message):
        """— перезапустить Сойку"""
        await self._restart(message, self.strings["restarting"])

    @loader.command(alias="up")
    async def updatecmd(self, message):
        """— скачать обновление из git и перезапуститься"""
        repo = self._repo()

        if repo is None:
            await utils.answer(message, self.strings["no_git"])
            return

        message = await utils.answer(message, self.strings["updating"])
        await self._update(message, repo=repo)

    @loader.owner
    @loader.command(alias="upcheck")
    async def updatecheckcmd(self, message):
        """— проверить обновления прямо сейчас"""
        repo = self._repo()

        if repo is None:
            await utils.answer(message, self.strings["no_git"])
            return

        message = await utils.answer(message, self.strings["check_now"])
        commits = await self._new_commits(repo)

        if not commits:
            await utils.answer(
                message,
                self.strings["no_updates"].format(__version_str__),
            )
            return

        await self._offer(commits, repo, message=message)

    @loader.owner
    @loader.command()
    async def autoupdatecmd(self, message):
        """— включить или выключить автообновление"""
        self.config["auto_update"] = not self.config["auto_update"]
        self.allmodules.save_config(self)

        await utils.answer(
            message,
            self.strings["auto_on"] if self.config["auto_update"] else self.strings["auto_off"],
        )

    @loader.command()
    async def versioncmd(self, message):
        """— какая версия Сойки установлена"""
        commit, built, url = await utils.run_sync(utils.get_build)
        link = utils.build_link(url, commit)

        text = f"🪶 <b>Сойка {__version_str__}</b>"

        if built:
            text += f"\n📅 <b>Сборка от</b> {built}"

        if link:
            text += f'\n🕸 <a href="{link}">исходники</a>'

        auto = self.strings["auto_on"] if self.config["auto_update"] else self.strings["auto_off"]
        await utils.answer(message, f"{text}\n\n{auto}")

    # ------------------------------------------------------------------ #
    #  Автопроверка
    # ------------------------------------------------------------------ #
    @loader.loop(interval=3600, autostart=True)
    async def update_checker(self):
        # Раньше первая проверка ждала целый час и обнулялась при каждом
        # перезапуске — уведомление могло не прийти вообще никогда
        if not self._checked_once:
            self._checked_once = True
            await asyncio.sleep(FIRST_CHECK_DELAY)

        if not self.config["check"]:
            return

        repo = self._repo()

        if repo is None:
            return

        commits = await self._new_commits(repo)

        if not commits:
            return

        if self.config["auto_update"]:
            logger.info("Найдено обновление %s — обновляюсь сам", commits[0].hexsha[:8])
            await self._notify(
                self.strings["auto_updating"].format(
                    versions=await self._versions(repo),
                    changelog=self._changelog(commits),
                )
            )
            await self._update(None, repo=repo, commits=commits)
            return

        if self.get("notified") == commits[0].hexsha:
            return

        self.set("notified", commits[0].hexsha)
        await self._offer(commits, repo)

    # ------------------------------------------------------------------ #
    #  Уведомления
    # ------------------------------------------------------------------ #
    async def _offer(self, commits, repo, message=None) -> None:
        """Показать, что вышло обновление, и дать кнопку «Обновить»."""
        text = self.strings["available"].format(
            versions=await self._versions(repo),
            count=len(commits),
            changelog=self._changelog(commits),
        )
        buttons = [
            [
                {"text": self.strings["btn_update"], "callback": self._cb_update},
                {"text": self.strings["btn_later"], "callback": self._cb_later},
            ]
        ]

        if link := self._commits_link(repo):
            buttons.append([{"text": self.strings["btn_commits"], "url": link}])

        # Команду .upcheck отвечаем туда, где её позвали
        if message is not None:
            if self._bot_alive() and await self.inline.form(
                text,
                message=message,
                reply_markup=buttons,
                ttl=NOTIFY_TTL,
            ):
                return

            await utils.answer(message, text + self._hint())
            return

        # Сама проверка стучится в личку бота — там кнопка под рукой
        if await self._notify(text, buttons):
            return

        await self.client.send_message("me", text + self._hint())

    async def _notify(self, text: str, buttons=None) -> bool:
        """Написать в личку собственного бота. False — если бот недоступен."""
        if not self._bot_alive():
            return False

        return bool(
            await self.inline.send_pm_unit(
                self.client.tg_id,
                text,
                buttons,
                photo=self.config["banner_url"] or None,
                ttl=NOTIFY_TTL,
            )
        )

    async def _report_update(self) -> None:
        """После перезапуска рассказать, что именно обновилось."""
        report = self.get("update_report") or {}
        self.set("update_report", None)

        # Ждём, пока поднимется бот — отчёт должен прийти именно в него
        for _ in range(30):
            if self._bot_alive():
                break

            await asyncio.sleep(2)

        changelog = self._changelog_from(
            report.get("changelog") or [],
            report.get("extra", 0),
        )
        text = self.strings["updated"].format(
            versions=self._versions_text(
                report.get("from_version", ""),
                report.get("to_version", ""),
            ),
            changelog=changelog,
        )

        if not await self._notify(text):
            with contextlib.suppress(Exception):
                await self.client.send_message("me", text)

    async def _cb_update(self, call) -> None:
        await call.answer(self.strings["updating"])

        with contextlib.suppress(Exception):
            await call.edit(self.strings["updating"], reply_markup=[])

        await self._update(None)

    async def _cb_later(self, call) -> None:
        await call.answer(self.strings["later"])
        await call.delete()

    # ------------------------------------------------------------------ #
    #  Тексты
    # ------------------------------------------------------------------ #
    def _hint(self) -> str:
        return self.strings["hint"].format(self.client.dispatcher.prefixes[0])

    def _bot_alive(self) -> bool:
        return self.inline is not None and self.inline.init_complete

    @staticmethod
    def _headline(commit) -> str:
        return commit.message.strip().splitlines()[0]

    def _changelog(self, commits) -> str:
        headlines = [self._headline(commit) for commit in commits[:CHANGELOG_LIMIT]]
        return self._changelog_from(headlines, max(len(commits) - CHANGELOG_LIMIT, 0))

    def _changelog_from(self, headlines: list, extra: int = 0) -> str:
        if not headlines:
            return self.strings["changelog_empty"]

        listing = "\n".join(f"▫️ {utils.escape_html(line)}" for line in headlines)
        text = self.strings["changelog"].format(listing)

        if extra > 0:
            text += self.strings["changelog_more"].format(extra)

        return text

    def _versions_text(self, current: str, latest: str) -> str:
        """Строчка «Версия» — номерами, без хешей: их читать невозможно."""
        if latest and latest != current:
            return self.strings["versions_new"].format(current, latest)

        return self.strings["versions_same"].format(current or __version_str__)

    async def _versions(self, repo) -> str:
        return self._versions_text(
            __version_str__,
            await self._remote_version(repo, self._branch(repo)),
        )

    # ------------------------------------------------------------------ #
    #  Работа с git
    # ------------------------------------------------------------------ #
    def _repo(self):
        """Репозиторий Сойки — или None, если обновляться неоткуда."""
        try:
            from git import Repo

            repo = Repo(configuration.repo_root())
            return repo if repo.remotes else None
        except Exception:  # noqa: BLE001 — git может отсутствовать целиком
            return None

    @staticmethod
    def _branch(repo) -> str:
        with contextlib.suppress(Exception):
            return repo.active_branch.name

        return "main"

    @staticmethod
    def _commits_link(repo) -> str:
        """Ссылка на список коммитов — кнопкой под уведомлением."""
        with contextlib.suppress(Exception):
            url = next(repo.remote().urls, "") or DEFAULT_REPO

            if url.startswith("http"):
                return f"{url.removesuffix('.git')}/commits"

        return ""

    @staticmethod
    def _parse_version(source: str) -> str:
        match = VERSION_RE.search(source or "")
        return ".".join(match.groups()) if match else ""

    async def _remote_version(self, repo, branch: str) -> str:
        """Версия, которая лежит на сервере — читаем version.py из origin."""
        try:
            source = await utils.run_sync(
                repo.git.show,
                f"origin/{branch}:soika/version.py",
            )
        except Exception:  # noqa: BLE001 — файла может не быть в старых сборках
            return ""

        return self._parse_version(source)

    def _installed_version(self) -> str:
        """Версия из файлов на диске — после git reset она уже новая."""
        path = configuration.repo_root() / "soika" / "version.py"

        try:
            return self._parse_version(path.read_text(encoding="utf-8"))
        except OSError:
            return ""

    async def _new_commits(self, repo) -> list:
        """Коммиты, которые есть на сервере, но не у нас."""
        try:
            await utils.run_sync(repo.remote().fetch)
            return list(repo.iter_commits(f"HEAD..origin/{self._branch(repo)}"))
        except Exception as e:
            # Раньше это глушилось в debug — и молчание было неотличимо от «всё ок»
            logger.warning("Проверка обновлений не удалась: %s", e, exc_info=True)
            return []

    # ------------------------------------------------------------------ #
    #  Само обновление
    # ------------------------------------------------------------------ #
    async def _update(self, message, repo=None, commits=None) -> None:
        """Подтянуть новую версию, поставить зависимости и перезапуститься."""
        repo = repo or self._repo()

        if repo is None:
            await self._say(message, self.strings["no_git"])
            return

        old = repo.head.commit.hexsha

        try:
            if commits is None:
                commits = await self._new_commits(repo)

            await utils.run_sync(repo.git.reset, "--hard", f"origin/{self._branch(repo)}")
        except Exception as e:  # noqa: BLE001 — покажем причину пользователю
            await self._say(message, self.strings["failed"].format(utils.escape_html(str(e))))
            return

        new = repo.head.commit.hexsha

        if old == new:
            await self._say(
                message,
                self.strings["up_to_date"].format(__version_str__),
            )
            return

        # Что рассказать после перезапуска — в процессе уже нового кода
        self.set(
            "update_report",
            {
                "from_version": __version_str__,
                "to_version": self._installed_version(),
                "changelog": [self._headline(commit) for commit in commits[:CHANGELOG_LIMIT]],
                "extra": max(len(commits) - CHANGELOG_LIMIT, 0),
            },
        )

        await self._say(message, self.strings["deps"])
        await self._install_requirements()
        await self._restart(message, self.strings["restarting"])

    async def _say(self, message, text: str) -> None:
        """Промежуточный статус: в чат, если команду позвали руками."""
        if message is None:
            logger.info("%s", utils.remove_html(text))
            return

        await utils.answer(message, text)

    async def _install_requirements(self) -> None:
        requirements = configuration.repo_root() / "requirements.txt"

        if not requirements.is_file():
            return

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements),
            "--disable-pip-version-check",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()

    async def _restart(self, message, text: str) -> None:
        if message is not None:
            sent = await utils.answer(message, text)

            if isinstance(sent, list):
                sent = sent[0]

            self.db.set(
                CORE,
                "restart_info",
                {
                    "chat": utils.get_chat_id(sent) if hasattr(sent, "peer_id") else None,
                    "message": getattr(sent, "id", None),
                    "started": time.time(),
                },
            )

        await self.db.flush()

        # Гасим бота вежливо: иначе его getUpdates ещё минуту держит Telegram,
        # новый процесс получает 409 и бот молчит после перезапуска
        if self.inline is not None:
            with contextlib.suppress(Exception):
                await self.inline.stop()

        logger.info("Перезапуск процесса")
        await asyncio.sleep(0.5)

        os.execl(sys.executable, sys.executable, "-m", "soika", *sys.argv[1:])
