"""Выполнение команд операционной системы."""

import asyncio
import contextlib
import os
import time

from .. import configuration, loader, utils

UPDATE_INTERVAL = 1.5
OUTPUT_LIMIT = 3500


@loader.tds
class TerminalMod(loader.Module):
    """Терминал прямо в Telegram: вывод обновляется на лету"""

    strings = {
        "name": "Терминал",
        "no_command": "🚫 <b>Что выполнять-то?</b>",
        "running": "⌛️ <b>Выполняется:</b> <code>{}</code>\n\n<pre><code>{}</code></pre>",
        "done": "✅ <b>Готово:</b> <code>{}</code>\n\n<pre><code>{}</code></pre>",
        "failed": "🚫 <b>Код выхода {}:</b> <code>{}</code>\n\n<pre><code>{}</code></pre>",
        "empty": "<i>(пусто)</i>",
        "killed": "🛑 <b>Процесс остановлен</b>",
    }

    strings_en = {
        "no_command": "🚫 <b>Nothing to execute</b>",
        "running": "⌛️ <b>Running:</b> <code>{}</code>\n\n<pre><code>{}</code></pre>",
        "done": "✅ <b>Done:</b> <code>{}</code>\n\n<pre><code>{}</code></pre>",
        "failed": "🚫 <b>Exit code {}:</b> <code>{}</code>\n\n<pre><code>{}</code></pre>",
        "empty": "<i>(empty)</i>",
        "killed": "🛑 <b>Process killed</b>",
    }

    def __init__(self) -> None:
        self._processes: dict[int, asyncio.subprocess.Process] = {}

    @loader.owner
    @loader.command(alias="sh")
    async def shellcmd(self, message):
        """<команда> — выполнить команду в системе"""
        command = utils.get_args_raw(message)

        if not command:
            await utils.answer(message, self.strings["no_command"])
            return

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(configuration.repo_root()),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

        message = await utils.answer(
            message,
            self.strings["running"].format(utils.escape_html(command), ""),
        )
        self._processes[message.id] = process

        output = await self._stream(message, command, process)
        self._processes.pop(message.id, None)

        template = "done" if process.returncode == 0 else "failed"
        text = (
            self.strings["done"].format(utils.escape_html(command), output)
            if process.returncode == 0
            else self.strings[template].format(
                process.returncode,
                utils.escape_html(command),
                output,
            )
        )

        await utils.answer(message, text)

    async def _stream(self, message, command: str, process) -> str:
        """Читать вывод и обновлять сообщение, но не чаще раза в полторы секунды."""
        collected = b""
        last_update = 0.0

        while True:
            try:
                chunk = await asyncio.wait_for(process.stdout.readline(), timeout=1)
            except asyncio.TimeoutError:
                chunk = b""

            if chunk:
                collected += chunk
            elif process.returncode is not None or process.stdout.at_eof():
                break

            if time.time() - last_update > UPDATE_INTERVAL and chunk:
                last_update = time.time()
                await utils.answer(
                    message,
                    self.strings["running"].format(
                        utils.escape_html(command),
                        self._tail(collected),
                    ),
                )

        await process.wait()
        return self._tail(collected)

    def _tail(self, data: bytes) -> str:
        text = data.decode("utf-8", errors="replace").strip()

        if not text:
            return self.strings["empty"]

        return utils.escape_html(text[-OUTPUT_LIMIT:])

    @loader.owner
    @loader.command()
    async def killshellcmd(self, message):
        """— остановить все запущенные через .shell процессы"""
        for process in list(self._processes.values()):
            with contextlib.suppress(ProcessLookupError):
                process.kill()

        self._processes.clear()
        await utils.answer(message, self.strings["killed"])
