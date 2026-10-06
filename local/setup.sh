#!/bin/sh
# Установка и проверка озвучки на Mac. Запуск: sh local/setup.sh путь/к/книге.epub
# Повторный запуск уже установленного: .venv/bin/python local/book2audio.py книга.epub
set -e
BOOK="$1"
[ -f "$BOOK" ] || { echo "Укажи файл книги: sh local/setup.sh путь/к/книге.epub"; exit 1; }
command -v brew >/dev/null || {
  echo "Сначала установи Homebrew (одна команда с https://brew.sh), потом запусти это снова."; exit 1; }

brew install python@3.12 ffmpeg
cd "$(dirname "$0")/.."
python3.12 -m venv .venv
. .venv/bin/activate
pip install -q mlx-audio pypdf torch torchaudio
python local/book2audio.py "$BOOK" --test

OUT="${BOOK%.*}_audio"
echo "Готово. Послушай файлы в папке: $OUT"
[ -d "$OUT" ] && open "$OUT"
