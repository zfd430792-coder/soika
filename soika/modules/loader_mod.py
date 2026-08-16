"""Установка, обновление и выгрузка модулей."""

import aiohttp

from .. import loader, utils
from ..types import LoadError
from ..version import DEFAULT_MODULES_REPO


@loader.tds
class LoaderMod(loader.Module):
    """Ставит модули из файлов, ссылок и репозитория"""

    strings = {
        "name": "Загрузчик",
        "no_file": "🚫 <b>Ответь на сообщение с .py файлом</b>",
        "no_link": "🚫 <b>Дай ссылку на .py файл</b>",
        "downloading": "🪶 <b>Скачиваю модуль...</b>",
        "installing": "🪶 <b>Устанавливаю зависимости...</b>",
        "loaded": "✅ <b>Модуль</b> <code>{}</code> <b>загружен</b>\n{}\n\n{}",
        "failed": "🚫 <b>Модуль не загрузился</b>\n\n<code>{}</code>",
        "unloaded": "✅ <b>Модуль</b> <code>{}</code> <b>выгружен</b>",
        "not_found": "🔎 <b>Модуль</b> <code>{}</code> <b>не найден</b>",
        "builtin": "🚫 <b>Встроенный модуль выгрузить нельзя</b>",
        "modules": "🪶 <b>Установлено модулей: {}</b>\n\n{}",
        "no_commands": "<i>без команд</i>",
        "repo_missing": "🔎 <b>В репозитории нет модуля</b> <code>{}</code>",
    }

    strings_en = {
        "no_file": "🚫 <b>Reply to a message with a .py file</b>",
        "no_link": "🚫 <b>Provide a link to a .py file</b>",
        "downloading": "🪶 <b>Downloading module...</b>",
        "installing": "🪶 <b>Installing requirements...</b>",
        "loaded": "✅ <b>Module</b> <code>{}</code> <b>loaded</b>\n{}\n\n{}",
        "failed": "🚫 <b>Module failed to load</b>\n\n<code>{}</code>",
        "unloaded": "✅ <b>Module</b> <code>{}</code> <b>unloaded</b>",
        "not_found": "🔎 <b>Module</b> <code>{}</code> <b>not found</b>",
        "builtin": "🚫 <b>Built-in modules cannot be unloaded</b>",
        "modules": "🪶 <b>Modules installed: {}</b>\n\n{}",
        "no_commands": "<i>no commands</i>",
        "repo_missing": "🔎 <b>Repository has no module</b> <code>{}</code>",
    }

    @loader.command(alias="lm")
    async def loadmodcmd(self, message):
        """— установить модуль из .py файла (ответом на файл)"""
        reply = await message.get_reply_message()

        if not reply or not reply.document:
            await utils.answer(message, self.strings["no_file"])
            return

        source = await reply.download_media(bytes)
        name = getattr(reply.file, "name", "module.py")

        await self._install(message, source.decode("utf-8"), origin=f"<файл {name}>")

    @loader.command(alias="dlm")
    async def dlmodcmd(self, message):
        """<ссылка> — скачать и установить модуль по ссылке"""
        url = utils.get_args_raw(message)

        if not utils.check_url(url):
            await utils.answer(message, self.strings["no_link"])
            return

        message = await utils.answer(message, self.strings["downloading"])
        source = await self._download(url)

        if source is None:
            await utils.answer(message, self.strings["failed"].format("Ссылка недоступна"))
            return

        await self._install(message, source, origin=url)

    @loader.command()
    async def mlcmd(self, message):
        """<имя> — установить модуль из репозитория Сойки"""
        name = utils.get_args_raw(message).strip()

        if not name:
            await utils.answer(message, self.strings["repo_missing"].format("?"))
            return

        repo = self.config["repo"].rstrip("/")
        url = f"{repo}/{name}.py"

        message = await utils.answer(message, self.strings["downloading"])
        source = await self._download(url)

        if source is None:
            await utils.answer(message, self.strings["repo_missing"].format(name))
            return

        await self._install(message, source, origin=url)

    @loader.command(alias="ulm")
    async def unloadmodcmd(self, message):
        """<имя> — выгрузить модуль"""
        name = utils.get_args_raw(message).strip()
        module = self.lookup(name)

        if module is None:
            await utils.answer(message, self.strings["not_found"].format(utils.escape_html(name)))
            return

        if self._is_builtin(module):
            await utils.answer(message, self.strings["builtin"])
            return

        unloaded = await self.allmodules.unload_module(type(module).__name__)
        await utils.answer(message, self.strings["unloaded"].format(", ".join(unloaded)))

    @loader.command(alias="mods")
    async def modulescmd(self, message):
        """— список установленных модулей и их источники"""
        installed = self.db.get("soika.loader", "installed", {})
        lines = []

        for module in sorted(self.allmodules.modules, key=lambda m: str(m.name).lower()):
            mark = "📦" if self._is_builtin(module) else "🧩"
            origin = installed.get(type(module).__name__, "")
            source = f' — <a href="{origin}">источник</a>' if origin else ""
            commands = ", ".join(sorted(module.commands)) or self.strings["no_commands"]
            lines.append(
                f"{mark} <b>{utils.escape_html(str(module.name))}</b>{source}\n"
                f"    <code>{commands}</code>"
            )

        await utils.answer(
            message,
            self.strings["modules"].format(len(self.allmodules.modules), "\n".join(lines)),
        )

    # ------------------------------------------------------------------ #
    async def _install(self, message, source: str, *, origin: str) -> None:
        try:
            instance = await self.allmodules.load_module(source, origin=origin, save_fs=True)
        except LoadError as e:
            await utils.answer(message, self.strings["failed"].format(utils.escape_html(str(e))))
            return
        except Exception as e:  # noqa: BLE001 — покажем пользователю, что именно сломалось
            await utils.answer(
                message,
                self.strings["failed"].format(utils.escape_html(f"{type(e).__name__}: {e}")),
            )
            return

        prefix = self.client.dispatcher.prefixes[0]
        commands = "\n".join(
            f"▫️ <code>{prefix}{command}</code> "
            f"{utils.escape_html(instance.get_command_doc(command))}".strip()
            for command in sorted(instance.commands)
        )

        await utils.answer(
            message,
            self.strings["loaded"].format(
                utils.escape_html(str(instance.name)),
                utils.escape_html(instance.get_module_doc()),
                commands or self.strings["no_commands"],
            ),
        )

    @staticmethod
    async def _download(url: str) -> str | None:
        try:
            async with aiohttp.ClientSession() as session, session.get(url) as response:
                response.raise_for_status()
                return await response.text()
        except Exception:  # noqa: BLE001 — сеть может отвалиться, это нормально
            return None

    def _is_builtin(self, module) -> bool:
        origin = str(getattr(module, "__origin__", ""))
        return "soika" in origin and "loaded_modules" not in origin

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "repo",
            DEFAULT_MODULES_REPO,
            "Репозиторий модулей для команды .ml",
            validator=loader.validators.Link(),
        )
    )
