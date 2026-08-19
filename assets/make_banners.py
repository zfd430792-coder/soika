"""Генератор баннеров Сойки.

Все баннеры собираются из одной подложки ``_banner_base.png`` (градиент и перо),
поэтому набор всегда выглядит как одна семья. Поменял строку в ``BANNERS`` —
перегенерировал:

    python assets/make_banners.py

Нужен только Pillow: ``pip install pillow``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent
BASE = ASSETS / "_banner_base.png"

BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

#: Левый край текста — правее пера
LEFT = 365
#: Сколько места остаётся до правого края
LIMIT = 1024 - LEFT - 45

TITLE_COLOR = (236, 243, 252)
SUBTITLE_COLOR = (138, 160, 190)

#: (файл, заголовок, подпись, высота заглавных букв заголовка)
#: Заголовок совпадает с названием модуля в .help — так баннер и раздел
#: читаются как одно целое
BANNERS: list[tuple[str, str, str, int]] = [
    ("welcome_banner", "СОЙКА", "модульный юзербот для Telegram", 60),
    ("info_banner", "ИНФО", "версия, аптайм и нагрузка", 48),
    ("help_banner", "СПРАВКА", "все модули и команды", 48),
    ("loader_banner", "ЗАГРУЗЧИК", "установка и выгрузка модулей", 48),
    ("settings_banner", "НАСТРОЙКИ", "префикс, алиасы и язык", 48),
    ("config_banner", "КОНФИГ", "настройки модулей кнопками", 48),
    ("bot_banner", "БОТ", "меню, аватарка и токен", 48),
    ("logs_banner", "ЛОГИ", "журнал работы и канал с логами", 48),
    ("backup_banner", "БЭКАП БАЗЫ", "выбери, как часто делать копию", 48),
    ("update_banner", "ОБНОВЛЕНИЕ", "вышла новая версия", 48),
    ("security_banner", "БЕЗОПАСНОСТЬ", "кому и какие команды разрешены", 48),
    ("terminal_banner", "ТЕРМИНАЛ", "команды системы с живым выводом", 48),
    ("eval_banner", "EVAL", "выполнить Python-код прямо из чата", 48),
    ("notes_banner", "ЗАМЕТКИ", "короткие записи в базе юзербота", 48),
    ("id_banner", "ID", "айди чата, сообщения и пользователя", 48),
]


def fit_by_cap(path: str, sample: str, cap: int) -> ImageFont.FreeTypeFont:
    """Шрифт такого размера, чтобы заглавная буква была нужной высоты."""
    best = min(
        range(20, 140),
        key=lambda size: abs(_cap_height(ImageFont.truetype(path, size), sample) - cap),
    )
    return ImageFont.truetype(path, best)


def _cap_height(font: ImageFont.FreeTypeFont, sample: str) -> int:
    box = font.getbbox(sample)
    return box[3] - box[1]


def shrink_to_fit(font: ImageFont.FreeTypeFont, text: str, limit: int) -> ImageFont.FreeTypeFont:
    """Длинная строка не должна вылезать за правый край."""
    while font.size > 12:
        box = font.getbbox(text)

        if box[2] - box[0] <= limit:
            break

        font = ImageFont.truetype(font.path, font.size - 1)

    return font


def draw_line(draw: ImageDraw.ImageDraw, text: str, font, top: int, fill) -> None:
    """Рисуем так, чтобы чернила начинались ровно в (LEFT, top)."""
    box = font.getbbox(text)
    draw.text((LEFT - box[0], top - box[1]), text, font=font, fill=fill)


def build(name: str, title: str, subtitle: str, cap: int) -> Path:
    image = Image.open(BASE).convert("RGB")
    draw = ImageDraw.Draw(image)

    hero = cap > 50

    # На главном баннере имя стоит в заголовке, на остальных — в подписи
    if not hero:
        subtitle = f"Сойка · {subtitle}"

    title_font = shrink_to_fit(fit_by_cap(BOLD, "О", cap), title, LIMIT)
    subtitle_font = shrink_to_fit(fit_by_cap(REGULAR, "С", 20), subtitle, LIMIT)

    # Заголовок покрупнее — опускаем пару строк ниже, чтобы блок остался по центру
    title_top = 150 if hero else 157
    subtitle_top = title_top + cap + 22

    draw_line(draw, title, title_font, title_top, TITLE_COLOR)
    draw_line(draw, subtitle, subtitle_font, subtitle_top, SUBTITLE_COLOR)

    path = ASSETS / f"{name}.png"
    image.save(path, optimize=True)
    return path


def main() -> None:
    for name, title, subtitle, cap in BANNERS:
        path = build(name, title, subtitle, cap)
        print(f"{path.name:20} {title} · {subtitle}")


if __name__ == "__main__":
    main()
