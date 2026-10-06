#!/bin/sh
# Браузерный тест с заглушкой вместо голосов Microsoft. Запуск: sh tests/run.sh
set -e
cd "$(dirname "$0")"
[ -d node_modules/pdfjs-dist ] || npm i --silent
python3 fixtures.py
ffmpeg -loglevel error -y -f lavfi -i "sine=frequency=440:duration=3" -ac 1 -b:a 48k mock.mp3
python3 server.py mock.mp3 > server.log 2>&1 & SERVER=$!
trap 'kill $SERVER' EXIT
sleep 1
PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS=1 node e2e.mjs "$PWD"
