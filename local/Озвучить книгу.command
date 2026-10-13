#!/bin/bash
# Двойной щелчок: открывает страницу озвучки в браузере. При первом запуске ставит всё нужное.
cd "$(dirname "$0")"
ENV="$HOME/Audiobook/env"
[ -x "$ENV/bin/python" ] || bash ./setup_mac.sh || { read -p "Нажмите Enter, чтобы закрыть"; exit 1; }
"$ENV/bin/python" app.py
