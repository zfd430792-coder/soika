"""Версия и брендинг Сойки."""

__version__ = (1, 2, 0)
__version_str__ = ".".join(map(str, __version__))

BRAND = "Сойка"
BRAND_LATIN = "Soika"
BRAND_EMOJI = "🪶"

#: Используется в юзернейме создаваемого инлайн-бота: soika_XXXXXX_bot
BOT_PREFIX = "soika"

#: Репозиторий по умолчанию — из него тянутся обновления (.update)
DEFAULT_REPO = "https://github.com/zfd430792-coder/soika"

#: Каталог модулей для команды .ml — берётся из того же репозитория
DEFAULT_MODULES_REPO = "https://raw.githubusercontent.com/zfd430792-coder/soika/main/modules"
