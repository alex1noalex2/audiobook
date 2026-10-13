#!/bin/bash
# Один раз: готовит окружение для озвучки на Mac (Python 3.12, F5-TTS, Silero Stress, GigaAM, ffmpeg).
set -e
ENV="$HOME/Audiobook/env"
command -v ffmpeg >/dev/null || { echo "Нужен ffmpeg: установите Homebrew (brew.sh), затем в Терминале: brew install ffmpeg"; exit 1; }
PY=$(command -v python3.12 || command -v python3.11 || command -v python3.13 || true)
[ -n "$PY" ] || { echo "Нужен Python 3.12: brew install python@3.12"; exit 1; }
mkdir -p "$HOME/Audiobook/voices" "$HOME/Audiobook/books"
"$PY" -m venv "$ENV"
"$ENV/bin/pip" install -q --upgrade pip
"$ENV/bin/pip" install f5-tts silero-stress onnxruntime "onnx-asr[hub]" num2words praat-parselmouth pypdf numpy
echo "Готово. Модели скачаются сами при первой озвучке (около 3 ГБ)."
