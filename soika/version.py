"""Версия и брендинг Сойки."""

__version__ = (1, 8, 0)
__version_str__ = ".".join(map(str, __version__))

BRAND = "Сойка"
BRAND_LATIN = "Soika"
BRAND_EMOJI = "🪶"

#: Используется в юзернейме создаваемого инлайн-бота: soika_XXXXXX_bot
BOT_PREFIX = "soika"

#: Репозиторий по умолчанию — из него тянутся обновления (.update)
DEFAULT_REPO = "https://github.com/zfd430792-coder/soika"

#: Официальный каталог модулей — страница репозитория для ссылок
MODULES_REPO = "https://github.com/zfd430792-coder/Soika-modu"

#: Тот же каталог, но raw — отсюда качает команда .ml
DEFAULT_MODULES_REPO = "https://raw.githubusercontent.com/zfd430792-coder/Soika-modu/main"
