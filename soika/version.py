"""Версия и брендинг Сойки."""

__version__ = (1, 0, 0)
__version_str__ = ".".join(map(str, __version__))

BRAND = "Сойка"
BRAND_LATIN = "Soika"
BRAND_EMOJI = "🪶"

#: Используется в юзернейме создаваемого инлайн-бота: soika_XXXXXX_bot
BOT_PREFIX = "soika"

#: Репозиторий по умолчанию — из него тянутся обновления (.update)
DEFAULT_REPO = "https://github.com/soika-userbot/soika"

#: Репозиторий сторонних модулей для команды .ml
DEFAULT_MODULES_REPO = "https://raw.githubusercontent.com/soika-userbot/modules/main"
