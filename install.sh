#!/usr/bin/env bash
# Установка Сойки на Debian/Ubuntu: зависимости, venv, systemd-сервис.
#
#   bash install.sh                  — поставить в /opt/soika
#   SOIKA_DIR=~/soika bash install.sh — поставить в другой каталог

set -euo pipefail

SOIKA_DIR="${SOIKA_DIR:-/opt/soika}"
SOIKA_REPO="${SOIKA_REPO:-https://github.com/zfd430792-coder/soika}"
SERVICE_NAME="${SERVICE_NAME:-soika}"
RUN_USER="${SUDO_USER:-$(id -un)}"

green() { printf '\033[38;5;39m%s\033[0m\n' "$*"; }
warn()  { printf '\033[38;5;214m%s\033[0m\n' "$*"; }
fail()  { printf '\033[38;5;203m%s\033[0m\n' "$*" >&2; exit 1; }

banner() {
    printf '\n\033[38;5;39m'
    cat <<'ART'
   _____       _ _
  / ____|     (_) |            🪶
 | (___   ___  _| | ____ _
  \___ \ / _ \| | |/ / _` |
  ____) | (_) | |   < (_| |
 |_____/ \___/|_|_|\_\__,_|   модульный юзербот
ART
    printf '\033[0m\n'
}

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        fail "Запусти через sudo: sudo bash install.sh"
    fi
}

install_packages() {
    if ! command -v apt-get >/dev/null 2>&1; then
        warn "Не Debian/Ubuntu — ставь зависимости сам: python3.10+, python3-venv, git, ffmpeg"
        return
    fi

    green "==> Ставлю системные пакеты"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
        python3 python3-venv python3-pip git ffmpeg \
        libwebp-dev libjpeg-dev zlib1g-dev >/dev/null
}

check_python() {
    local version
    version=$(python3 -c 'import sys; print("%d%02d" % sys.version_info[:2])')

    if [ "$version" -lt 310 ]; then
        fail "Нужен Python 3.10 или новее, а стоит $(python3 --version)"
    fi
}

fetch_sources() {
    # При установке через «wget ... | bash» BASH_SOURCE пуст — работаем от репозитория
    local script_path="${BASH_SOURCE[0]:-}"
    local script_dir=""

    if [ -n "$script_path" ] && [ -f "$script_path" ]; then
        script_dir=$(cd "$(dirname "$script_path")" && pwd)
    fi

    if [ -n "$script_dir" ] && [ -f "$script_dir/soika/__main__.py" ] && [ "$script_dir" != "$SOIKA_DIR" ]; then
        green "==> Копирую исходники из $script_dir"
        mkdir -p "$SOIKA_DIR"
        cp -r "$script_dir/." "$SOIKA_DIR/"
        return
    fi

    if [ -d "$SOIKA_DIR/.git" ]; then
        green "==> Обновляю существующую установку"
        git -C "$SOIKA_DIR" pull --ff-only || warn "git pull не прошёл, продолжаю с текущей версией"
        return
    fi

    if [ ! -f "$SOIKA_DIR/soika/__main__.py" ]; then
        green "==> Клонирую $SOIKA_REPO"
        git clone --depth 1 "$SOIKA_REPO" "$SOIKA_DIR"
    fi
}

setup_venv() {
    green "==> Собираю виртуальное окружение"
    python3 -m venv "$SOIKA_DIR/venv"
    "$SOIKA_DIR/venv/bin/pip" install --upgrade pip --quiet
    "$SOIKA_DIR/venv/bin/pip" install -r "$SOIKA_DIR/requirements.txt" --quiet
}

write_service() {
    green "==> Создаю сервис $SERVICE_NAME.service"

    cat > "/etc/systemd/system/$SERVICE_NAME.service" <<UNIT
[Unit]
Description=Soika Telegram userbot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$SOIKA_DIR
ExecStart=$SOIKA_DIR/venv/bin/python -m soika
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

    chown -R "$RUN_USER":"$RUN_USER" "$SOIKA_DIR"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" >/dev/null
    systemctl restart "$SERVICE_NAME"
}

finish() {
    green "==> Готово"
    cat <<INFO

Сойка запущена как сервис «$SERVICE_NAME» из каталога $SOIKA_DIR.

Что дальше:
  1. Посмотри логи и найди там ссылку на веб-установщик:
       journalctl -u $SERVICE_NAME -f
  2. Открой ссылку в браузере, введи api_id/api_hash с my.telegram.org
     и войди в аккаунт по QR-коду.
  3. В Telegram напиши себе .help — Сойка ответит.

Полезное:
  systemctl restart $SERVICE_NAME    # перезапуск
  systemctl stop $SERVICE_NAME       # остановить
  journalctl -u $SERVICE_NAME -n 100 # последние логи

Порт веб-панели лучше закрыть фаерволом и ходить через SSH-туннель:
  ssh -L 8080:127.0.0.1:8080 $RUN_USER@<адрес-сервера>
INFO
}

banner
require_root
install_packages
check_python
fetch_sources
setup_venv
write_service
sleep 3
finish
