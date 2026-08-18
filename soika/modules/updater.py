"""Обновление из git, перезапуск и автопроверка новых версий."""

import asyncio
import contextlib
import logging
import os
import sys
import time

from .. import configuration, loader, utils
from ..version import __version_str__

logger = logging.getLogger(__name__)

CORE = "soika.core"


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
        "up_to_date": "✅ <b>Уже последняя версия</b> (<code>{}</code>)",
        "deps": "🪶 <b>Ставлю зависимости...</b>",
        "failed": "🚫 <b>Обновление не удалось:</b>\n<code>{}</code>",
        "updated": "✅ <b>Обновился:</b> <code>{}</code> → <code>{}</code>\n<i>{}</i>",
        "available": (
            "🪶 <b>Вышло обновление Сойки</b>\n\n"
            "<b>Новых коммитов:</b> {count}\n"
            "<b>Последний:</b> <i>{message}</i>\n"
            "<b>Версия:</b> <code>{current}</code> → <code>{latest}</code>"
        ),
        "check_now": "🔎 <b>Проверяю обновления...</b>",
        "no_updates": "✅ <b>Обновлений нет</b> (<code>{}</code>)",
        "auto_on": "🤖 <b>Автообновление включено</b> — буду обновляться сам",
        "auto_off": "✋ <b>Автообновление выключено</b> — только по команде",
        "later": "Ладно, потом",
        "btn_update": "⬇️ Обновить",
        "btn_later": "🚫 Позже",
        "auto_updating": "🤖 <b>Нашёл обновление и обновляюсь сам</b>\n<i>{}</i>",
    }

    strings_en = {
        "restarting": "🪶 <b>Restarting...</b>",
        "updating": "🪶 <b>Updating...</b>",
        "no_git": "🚫 <b>Not a git repository or no remote configured</b>",
        "up_to_date": "✅ <b>Already up to date</b> (<code>{}</code>)",
        "deps": "🪶 <b>Installing requirements...</b>",
        "failed": "🚫 <b>Update failed:</b>\n<code>{}</code>",
        "updated": "✅ <b>Updated:</b> <code>{}</code> → <code>{}</code>\n<i>{}</i>",
        "available": (
            "🪶 <b>Soika update available</b>\n\n"
            "<b>New commits:</b> {count}\n"
            "<b>Latest:</b> <i>{message}</i>\n"
            "<b>Version:</b> <code>{current}</code> → <code>{latest}</code>"
        ),
        "check_now": "🔎 <b>Checking for updates...</b>",
        "no_updates": "✅ <b>No updates</b> (<code>{}</code>)",
        "auto_on": "🤖 <b>Auto update enabled</b>",
        "auto_off": "✋ <b>Auto update disabled</b>",
        "later": "Fine, later",
        "btn_update": "⬇️ Update",
        "btn_later": "🚫 Later",
        "auto_updating": "🤖 <b>Found an update, updating myself</b>\n<i>{}</i>",
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
    )

    async def client_ready(self, client, db):
        self.update_checker.interval = self.config["interval"] * 60

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

    @loader.owner
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
                self.strings["no_updates"].format(repo.head.commit.hexsha[:8]),
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
        commit, url = utils.get_git_info()
        text = f"🪶 <b>Сойка {__version_str__}</b>"

        if commit:
            text += f"\n<b>Коммит:</b> <code>{commit[:8]}</code>"

        if url:
            text += f"\n<b>Репозиторий:</b> {utils.escape_html(url)}"

        auto = self.strings["auto_on"] if self.config["auto_update"] else self.strings["auto_off"]
        await utils.answer(message, f"{text}\n\n{auto}")

    # ------------------------------------------------------------------ #
    #  Автопроверка
    # ------------------------------------------------------------------ #
    @loader.loop(interval=3600, autostart=True, wait_before=True)
    async def update_checker(self):
        if not self.config["check"]:
            return

        repo = self._repo()

        if repo is None:
            return

        commits = await self._new_commits(repo)

        if not commits:
            return

        headline = self._headline(commits[0])

        if self.config["auto_update"]:
            logger.info("Найдено обновление %s — обновляюсь сам", commits[0].hexsha[:8])
            sent = await self.client.send_message(
                "me",
                self.strings["auto_updating"].format(utils.escape_html(headline)),
            )
            await self._update(sent, repo=repo)
            return

        if self.get("notified") == commits[0].hexsha:
            return

        self.set("notified", commits[0].hexsha)
        await self._offer(commits, repo)

    async def _offer(self, commits, repo, message=None) -> None:
        """Показать, что вышло обновление, и предложить кнопку обновления."""
        text = self.strings["available"].format(
            count=len(commits),
            message=utils.escape_html(self._headline(commits[0])),
            current=repo.head.commit.hexsha[:8],
            latest=commits[0].hexsha[:8],
        )
        buttons = [
            {"text": self.strings["btn_update"], "callback": self._cb_update},
            {"text": self.strings["btn_later"], "callback": self._cb_later},
        ]

        inline_ready = self.inline is not None and self.inline.init_complete

        if inline_ready and await self.inline.form(text, message=message, reply_markup=buttons):
            return

        prefix = self.client.dispatcher.prefixes[0]
        tail = f"\n\n<i>Обновиться:</i> <code>{prefix}update</code>"

        if message is not None:
            await utils.answer(message, text + tail)
            return

        await self.client.send_message("me", text + tail)

    async def _cb_update(self, call) -> None:
        await call.answer(self.strings["updating"])
        sent = await self.client.send_message("me", self.strings["updating"])

        with contextlib.suppress(Exception):
            await call.delete()

        await self._update(sent)

    async def _cb_later(self, call) -> None:
        await call.answer(self.strings["later"])
        await call.delete()

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
    def _headline(commit) -> str:
        return commit.message.strip().splitlines()[0]

    async def _new_commits(self, repo) -> list:
        """Коммиты, которые есть на сервере, но не у нас."""
        try:
            await utils.run_sync(repo.remote().fetch)
            branch = repo.active_branch.name
            return list(repo.iter_commits(f"HEAD..origin/{branch}"))
        except Exception:
            logger.debug("Проверка обновлений не удалась", exc_info=True)
            return []

    async def _update(self, message, repo=None) -> None:
        """Подтянуть новую версию, поставить зависимости и перезапуститься."""
        repo = repo or self._repo()

        if repo is None:
            await utils.answer(message, self.strings["no_git"])
            return

        old = repo.head.commit.hexsha

        try:
            await utils.run_sync(repo.remote().fetch)
            branch = repo.active_branch.name
            await utils.run_sync(repo.git.reset, "--hard", f"origin/{branch}")
        except Exception as e:  # noqa: BLE001 — покажем причину пользователю
            await utils.answer(message, self.strings["failed"].format(utils.escape_html(str(e))))
            return

        new = repo.head.commit.hexsha

        if old == new:
            await utils.answer(message, self.strings["up_to_date"].format(old[:8]))
            return

        await utils.answer(message, self.strings["deps"])
        await self._install_requirements()

        await self._restart(
            message,
            self.strings["updated"].format(
                old[:8],
                new[:8],
                utils.escape_html(self._headline(repo.head.commit)),
            ),
        )

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

        logger.info("Перезапуск процесса")
        await asyncio.sleep(0.5)

        os.execl(sys.executable, sys.executable, "-m", "soika", *sys.argv[1:])
