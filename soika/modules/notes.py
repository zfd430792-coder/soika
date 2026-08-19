"""Быстрые заметки прямо в Telegram."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/notes_banner.png

# meta developer: @soika
# meta description: Заметки: добавить, посмотреть списком, удалить

import time

from .. import loader, utils


@loader.tds
class NotesMod(loader.Module):
    """Хранит короткие заметки в базе юзербота"""

    strings = {
        "name": "Заметки",
        "added": "📝 <b>Заметка #{} сохранена</b>",
        "empty_note": "🚫 <b>Что записывать-то?</b>",
        "no_notes": "📭 <b>Заметок нет.</b> Добавь: <code>{}note текст</code>",
        "header": "📝 <b>Заметок: {}</b>\n\n",
        "line": "<b>#{}</b> <i>({})</i>\n{}\n\n",
        "removed": "🗑 <b>Заметка #{} удалена</b>",
        "not_found": "🔎 <b>Заметки #{} нет</b>",
        "cleared": "🗑 <b>Все заметки удалены ({} шт.)</b>",
        "usage_del": "🚫 <b>Укажи номер:</b> <code>{}delnote 1</code>",
    }

    strings_en = {
        "added": "📝 <b>Note #{} saved</b>",
        "empty_note": "🚫 <b>Nothing to save</b>",
        "no_notes": "📭 <b>No notes.</b> Add one: <code>{}note text</code>",
        "header": "📝 <b>Notes: {}</b>\n\n",
        "line": "<b>#{}</b> <i>({})</i>\n{}\n\n",
        "removed": "🗑 <b>Note #{} removed</b>",
        "not_found": "🔎 <b>No note #{}</b>",
        "cleared": "🗑 <b>All notes removed ({})</b>",
        "usage_del": "🚫 <b>Provide a number:</b> <code>{}delnote 1</code>",
    }

    config = loader.ModuleConfig(
        loader.ConfigValue(
            "date_format",
            "%d.%m.%Y %H:%M",
            "Формат даты в списке заметок",
            validator=loader.validators.String(max_len=32),
        )
    )

    @property
    def notes(self) -> list:
        return self.pointer("notes", [], item_type=list)

    @loader.command(alias="n")
    async def notecmd(self, message):
        """<текст> — сохранить заметку (можно реплаем на сообщение)"""
        text = utils.get_args_html(message)

        if not text and (reply := await message.get_reply_message()):
            text = reply.text or ""

        if not text.strip():
            await utils.answer(message, self.strings["empty_note"])
            return

        notes = self.notes
        notes.append({"text": text, "time": time.time()})

        await utils.answer(message, self.strings["added"].format(len(notes)))

    @loader.command(alias="ns")
    async def notescmd(self, message):
        """— список заметок"""
        notes = self.notes
        prefix = self.client.dispatcher.prefixes[0]

        if not notes:
            await utils.answer(message, self.strings["no_notes"].format(prefix))
            return

        text = self.strings["header"].format(len(notes))

        for index, note in enumerate(notes, start=1):
            stamp = time.strftime(self.config["date_format"], time.localtime(note["time"]))
            text += self.strings["line"].format(index, stamp, note["text"])

        await utils.answer(message, text)

    @loader.command(alias="dn")
    async def delnotecmd(self, message):
        """<номер> — удалить заметку"""
        args = utils.get_args_raw(message).strip()
        prefix = self.client.dispatcher.prefixes[0]

        if not args.isdigit():
            await utils.answer(message, self.strings["usage_del"].format(prefix))
            return

        index = int(args)
        notes = self.notes

        if not 1 <= index <= len(notes):
            await utils.answer(message, self.strings["not_found"].format(index))
            return

        notes.pop(index - 1)
        await utils.answer(message, self.strings["removed"].format(index))

    @loader.command()
    async def clearnotescmd(self, message):
        """— удалить все заметки"""
        notes = self.notes
        count = len(notes)
        notes.clear()

        await utils.answer(message, self.strings["cleared"].format(count))
