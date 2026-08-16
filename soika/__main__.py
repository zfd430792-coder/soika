"""Точка входа: ``python -m soika``."""

import sys

if sys.version_info < (3, 10):  # noqa: UP036 — проверка нужна именно на старых версиях
    print(f"Сойке нужен Python 3.10 или новее. Установлен: {sys.version.split()[0]}")
    sys.exit(1)


def entrypoint() -> None:
    # Windows-консоль по умолчанию не в UTF-8, а мы рисуем QR-код и пишем по-русски
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    from .main import Soika

    Soika().main()


if __name__ == "__main__":
    entrypoint()
