#!/usr/bin/env python3
"""Проба ударений на Mac: Silero Stress ставит ударения, мы записываем их так, как модель может понять.

    .venv/bin/pip install -q silero-stress
    .venv/bin/python local/try_stress.py ~/Books/babylon.epub --ref ~/Desktop/voices12/voice_05.wav --chunks 102 105 106

Для каждого куска (номера как в 00102.wav, берётся тот же текст, что уходит в модель) три варианта:
  1_plain      как сейчас
  2_caps       ударная гласная заглавной (замОк)
  3_caps_ref   то же, и в записи образца голоса (voice_05.txt) ударения тоже заглавными: модель учится на образце
Файлы в ~/Desktop/stress, имя 00102_1_plain.wav и т. д. Слушайте и пишите, какой вариант читает верно.
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book2audio as b  # noqa: E402

VOWELS = "аеёиоуыэюя"


def caps(marked):
    """Мен+я зов+ут -> МенЯ зовУт (ё и так ударная, плюс перед ней убираем)."""
    def one(m):
        v = m.group(1)
        return v if v.lower() == "ё" else v.upper()
    return re.sub(r"\+([" + VOWELS + VOWELS.upper() + "])", one, marked)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("--ref", required=True, help="WAV голоса; рядом лежит .txt с текстом записи")
    ap.add_argument("--chunks", type=int, nargs="+", required=True, help="номера кусков (как в 00102.wav)")
    ap.add_argument("--fixes", type=Path, help="файл поправок (по умолчанию fixes.txt рядом с книгой)")
    ap.add_argument("--out", type=Path, default=Path.home() / "Desktop" / "stress")
    ap.add_argument("--steps", type=int, default=16)
    args = ap.parse_args()

    import numpy as np
    from mlx_audio.tts.utils import load_model
    from silero_stress import load_accentor

    chunks = b.chunk([(r, b.clean(t, False)) for r, t in b.read_book(args.book)], 400)
    fixes = b.load_fixes(args.fixes or args.book.with_name("fixes.txt"))
    accentor = load_accentor()
    model = load_model(b.MODEL)
    tokens, ref_text = b.load_voice(model, args.ref)
    ref_caps = caps(accentor(ref_text))
    print(f"Образец: {ref_text}\nС ударениями: {ref_caps}\n")
    args.out.mkdir(parents=True, exist_ok=True)

    for n in args.chunks:
        plain = b.speak(chunks[n][1], fixes)
        marked = caps(accentor(plain))
        print(f"[{n}] {marked}\n")
        for tag, text, ref in (("1_plain", plain, ref_text), ("2_caps", marked, ref_text),
                               ("3_caps_ref", marked, ref_caps)):
            started = time.time()
            r = next(model.generate(text=text, language="ru", num_steps=args.steps, guidance_scale=2.0,
                                    duration_s=len(text) / 13, ref_tokens=tokens, ref_text=ref))
            name = f"{n:05d}_{tag}.wav"
            b.save_wav(args.out / name, b.tidy(np.array(r.audio), r.sample_rate), r.sample_rate)
            print(f"  {name} ({time.time() - started:.0f} с)", flush=True)
    print(f"Готово. Файлы в папке {args.out}")
    if sys.platform == "darwin":
        subprocess.run(["open", str(args.out)])


if __name__ == "__main__":
    main()
