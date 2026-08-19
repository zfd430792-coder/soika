"""Выполнение Python-кода прямо из чата."""

# meta banner: https://raw.githubusercontent.com/zfd430792-coder/soika/main/assets/eval_banner.png

import time
import typing

from meval import meval

from .. import loader, utils


@loader.tds
class EvalMod(loader.Module):
    """Python-консоль внутри Telegram"""

    strings = {
        "name": "Eval",
        "no_code": "🚫 <b>Нечего выполнять</b>",
        "result": (
            "🪶 <b>Код:</b>\n<pre><code class='language-python'>{}</code></pre>\n"
            "<b>Результат:</b>\n<pre><code>{}</code></pre>\n<i>{} мс</i>"
        ),
        "error": (
            "🚫 <b>Код:</b>\n<pre><code class='language-python'>{}</code></pre>\n"
            "<b>Ошибка:</b>\n<pre><code>{}</code></pre>"
        ),
    }

    strings_en = {
        "no_code": "🚫 <b>Nothing to execute</b>",
        "result": (
            "🪶 <b>Code:</b>\n<pre><code class='language-python'>{}</code></pre>\n"
            "<b>Result:</b>\n<pre><code>{}</code></pre>\n<i>{} ms</i>"
        ),
        "error": (
            "🚫 <b>Code:</b>\n<pre><code class='language-python'>{}</code></pre>\n"
            "<b>Error:</b>\n<pre><code>{}</code></pre>"
        ),
    }

    @loader.owner
    @loader.command(alias="e")
    async def evalcmd(self, message):
        """<код> — выполнить Python-код (async поддерживается)"""
        code = utils.get_args_raw(message)

        if not code:
            await utils.answer(message, self.strings["no_code"])
            return

        started = time.perf_counter()

        try:
            result = await meval(code, globals(), **await self._context(message))
        except Exception:  # noqa: BLE001 — показываем ошибку пользователю
            import traceback

            await utils.answer(
                message,
                self.strings["error"].format(
                    utils.escape_html(code),
                    utils.escape_html(traceback.format_exc()[-3000:]),
                ),
            )
            return

        took = round((time.perf_counter() - started) * 1000, 1)

        await utils.answer(
            message,
            self.strings["result"].format(
                utils.escape_html(code),
                utils.escape_html(str(result))[:3000],
                took,
            ),
        )

    async def _context(self, message) -> dict[str, typing.Any]:
        return {
            "message": message,
            "client": self.client,
            "c": self.client,
            "db": self.db,
            "self": self,
            "utils": utils,
            "loader": loader,
            "modules": self.allmodules,
            "inline": self.inline,
            "reply": await message.get_reply_message(),
        }
