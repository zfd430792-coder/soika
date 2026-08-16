"""Логи юзербота одной командой."""

import io
import logging

from .. import loader, utils
from ..log import memory_handler

LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


@loader.tds
class LogsMod(loader.Module):
    """Отправляет логи и чистит их"""

    strings = {
        "name": "Логи",
        "empty": "🪶 <b>Логов уровня</b> <code>{}</code> <b>нет — и хорошо</b>",
        "caption": "🪶 <b>Логи Сойки</b> · уровень <code>{}</code> · строк: {}",
        "cleared": "🧹 <b>Логи в памяти очищены</b>",
        "unknown_level": "🚫 <b>Уровни:</b> <code>{}</code>",
    }

    strings_en = {
        "empty": "🪶 <b>No logs of level</b> <code>{}</code> <b>— and that's good</b>",
        "caption": "🪶 <b>Soika logs</b> · level <code>{}</code> · lines: {}",
        "cleared": "🧹 <b>In-memory logs cleared</b>",
        "unknown_level": "🚫 <b>Levels:</b> <code>{}</code>",
    }

    @loader.owner
    @loader.command()
    async def logscmd(self, message):
        """[уровень] — прислать логи (debug/info/warning/error)"""
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
    @loader.command()
    async def clearlogscmd(self, message):
        """— очистить логи в памяти"""
        memory_handler().clear()
        await utils.answer(message, self.strings["cleared"])
