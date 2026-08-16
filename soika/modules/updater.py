"""Обновление из git и перезапуск."""

import asyncio
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
    """Обновляет Сойку и перезапускает процесс"""

    strings = {
        "name": "Обновление",
        "restarting": "🪶 <b>Перезапускаюсь...</b>",
        "updating": "🪶 <b>Обновляюсь...</b>",
        "no_git": (
            "🚫 <b>Это не git-репозиторий или нет remote.</b>\n"
            "<i>Обновляться неоткуда — переустанови Сойку через install.sh</i>"
        ),
        "up_to_date": "✅ <b>Уже последняя версия</b> (<code>{}</code>)",
        "updated": "✅ <b>Обновлено:</b> <code>{}</code> → <code>{}</code>\n{}\n\n<i>Перезапускаюсь...</i>",
        "deps": "🪶 <b>Ставлю зависимости...</b>",
        "failed": "🚫 <b>Обновление не удалось:</b>\n<code>{}</code>",
        "new_version": (
            "🪶 <b>Вышло обновление Сойки</b>\n\n"
            "<b>Новых коммитов:</b> {}\n<b>Последний:</b> <i>{}</i>\n\n"
            "<i>Обновиться:</i> <code>{}update</code>"
        ),
    }

    strings_en = {
        "restarting": "🪶 <b>Restarting...</b>",
        "updating": "🪶 <b>Updating...</b>",
        "no_git": "🚫 <b>Not a git repository or no remote configured</b>",
        "up_to_date": "✅ <b>Already up to date</b> (<code>{}</code>)",
        "updated": "✅ <b>Updated:</b> <code>{}</code> → <code>{}</code>\n{}\n\n<i>Restarting...</i>",
        "deps": "🪶 <b>Installing requirements...</b>",
        "failed": "🚫 <b>Update failed:</b>\n<code>{}</code>",
        "new_version": (
            "🪶 <b>Soika update available</b>\n\n"
            "<b>New commits:</b> {}\n<b>Latest:</b> <i>{}</i>\n\n"
            "<i>Update:</i> <code>{}update</code>"
        ),
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "notify",
            True,
            "Сообщать в «Избранное» о новых версиях",
            validator=loader.validators.Boolean(),
        )
    )

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
                utils.escape_html(repo.head.commit.message.strip().splitlines()[0]),
                "",
            ),
        )

    # ------------------------------------------------------------------ #
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

        logger.info("Перезапуск по команде пользователя")
        await asyncio.sleep(0.5)

        os.execl(sys.executable, sys.executable, "-m", "soika", *sys.argv[1:])

    def _repo(self):
        """Репозиторий Сойки — или None, если обновляться неоткуда."""
        try:
            from git import Repo

            repo = Repo(configuration.repo_root())
            return repo if repo.remotes else None
        except Exception:  # noqa: BLE001 — git может отсутствовать целиком
            return None

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

    @loader.loop(interval=3600, autostart=True, wait_before=True)
    async def update_checker(self):
        """Раз в час смотрим, не появилось ли обновление."""
        if not self.config["notify"]:
            return

        repo = self._repo()

        if repo is None:
            return

        try:
            await utils.run_sync(repo.remote().fetch)
            branch = repo.active_branch.name
            commits = list(repo.iter_commits(f"HEAD..origin/{branch}"))
        except Exception:  # noqa: BLE001 — сеть/гит могут не отвечать
            return

        if not commits:
            return

        latest = commits[0].hexsha

        if self.get("notified") == latest:
            return

        self.set("notified", latest)
        prefix = self.client.dispatcher.prefixes[0]

        await self.client.send_message(
            "me",
            self.strings["new_version"].format(
                len(commits),
                utils.escape_html(commits[0].message.strip().splitlines()[0]),
                prefix,
            ),
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

        await utils.answer(message, text)
