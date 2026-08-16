"""Резервные копии базы данных."""

import io
import json
import logging
import time

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class BackupMod(loader.Module):
    """Бэкап и восстановление базы Сойки"""

    strings = {
        "name": "Бэкап",
        "caption": "🪶 <b>Бэкап базы Сойки</b>\nЗаписей: {}",
        "no_file": "🚫 <b>Ответь на файл с бэкапом</b>",
        "restored": "✅ <b>База восстановлена. Перезапусти Сойку:</b> <code>{}restart</code>",
        "bad_file": "🚫 <b>Это не похоже на бэкап базы</b>",
        "auto_on": "✅ <b>Автобэкап включён: раз в {} ч.</b>",
        "auto_off": "✅ <b>Автобэкап выключен</b>",
    }

    strings_en = {
        "caption": "🪶 <b>Soika database backup</b>\nEntries: {}",
        "no_file": "🚫 <b>Reply to a backup file</b>",
        "restored": "✅ <b>Database restored. Restart Soika:</b> <code>{}restart</code>",
        "bad_file": "🚫 <b>This does not look like a backup</b>",
        "auto_on": "✅ <b>Auto backup enabled: every {} h.</b>",
        "auto_off": "✅ <b>Auto backup disabled</b>",
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "interval",
            24,
            "Как часто делать автобэкап в «Избранное», часов",
            validator=loader.validators.Integer(minimum=1, maximum=168),
        ),
        loader.ConfigValue(
            "auto",
            False,
            "Включить автоматический бэкап",
            validator=loader.validators.Boolean(),
        ),
    )

    @loader.owner
    @loader.command(alias="bkp")
    async def backupcmd(self, message):
        """— прислать бэкап базы"""
        await self._send_backup(message)

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
            assert isinstance(data, dict)
        except (json.JSONDecodeError, UnicodeDecodeError, AssertionError):
            await utils.answer(message, self.strings["bad_file"])
            return

        self.db.clear()
        self.db.update(data)
        await self.db.flush()

        prefix = self.client.dispatcher.prefixes[0]
        await utils.answer(message, self.strings["restored"].format(prefix))

    @loader.owner
    @loader.command()
    async def autobackupcmd(self, message):
        """— включить/выключить автобэкап"""
        self.config["auto"] = not self.config["auto"]
        self.allmodules.save_config(self)

        await utils.answer(
            message,
            self.strings["auto_on"].format(self.config["interval"])
            if self.config["auto"]
            else self.strings["auto_off"],
        )

    async def _send_backup(self, message=None) -> None:
        payload = io.BytesIO(json.dumps(dict(self.db), ensure_ascii=False, indent=2).encode())
        payload.name = f"soika-db-{self.client.tg_id}.json"
        caption = self.strings["caption"].format(len(self.db))

        if message is not None:
            await utils.answer_file(message, payload, caption=caption)
            return

        await self.client.send_file("me", payload, caption=caption)

    @loader.loop(interval=3600, autostart=True, wait_before=True)
    async def backup_loop(self):
        if not self.config["auto"]:
            return

        last = self.get("last_backup", 0)
        interval = self.config["interval"] * 3600

        if time.time() - last < interval:
            return

        self.set("last_backup", time.time())

        try:
            await self._send_backup()
        except Exception:
            logger.exception("Автобэкап не удался")
