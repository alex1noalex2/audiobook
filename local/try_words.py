#!/usr/bin/env python3
"""Как модель читает слово: сравнить варианты записи на Mac, пока озвучка идёт в Colab.

    .venv/bin/python local/try_words.py --ref ~/Desktop/voices12/voice_05.wav Яхве Яхуа Иауэ
    .venv/bin/python local/try_words.py --ref ~/Desktop/voices12/voice_05.wav --template "Слово: {w}. Ещё раз: {w}." Элохим Улхим

Каждый вариант читается в одной и той же фразе, файлы лежат в ~/Desktop/words: 01_Яхве.wav, 02_Яхуа.wav …
Тем же голосом, что и книга (--ref голоса №5 для основного текста, №6 для заголовков и примечаний).
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book2audio as b  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="+", help="варианты записи слова")
    ap.add_argument("--ref", required=True, help="WAV голоса; рядом лежит .txt с текстом записи")
    ap.add_argument("--template", default="Это слово читается так: {w}. И ещё раз: {w}.",
                    help="фраза, в которую подставляется слово ({w})")
    ap.add_argument("--out", type=Path, default=Path.home() / "Desktop" / "words")
    ap.add_argument("--steps", type=int, default=16)
    args = ap.parse_args()

    import numpy as np
    from mlx_audio.tts.utils import load_model

    b.ref_text_file(args.ref)
    model = load_model(b.MODEL)
    tokens, ref_text = b.load_voice(model, args.ref)
    args.out.mkdir(parents=True, exist_ok=True)
    for n, word in enumerate(args.words, 1):
        text = args.template.format(w=word)
        started = time.time()
        r = next(model.generate(text=text, language="ru", num_steps=args.steps, guidance_scale=2.0,
                                duration_s=len(text) / 13, ref_tokens=tokens, ref_text=ref_text))
        name = f"{n:02d}_{re.sub(r'[^0-9A-Za-zА-Яа-яЁё-]+', '_', word)}.wav"
        b.save_wav(args.out / name, b.tidy(np.array(r.audio), r.sample_rate), r.sample_rate)
        print(f"[{n}/{len(args.words)}] {name}  ({time.time() - started:.0f} с)", flush=True)
    print(f"Готово. Файлы в папке {args.out}")
    if sys.platform == "darwin":
        subprocess.run(["open", str(args.out)])


if __name__ == "__main__":
    main()
