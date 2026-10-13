"""Из длинной записи вашего голоса -> несколько чистых образцов по ~10 с с текстом (ref_NN.wav + ref_NN.txt).
Образец режется по паузам, не посреди слова; текст расшифровывает ASR (GigaAM), проверьте его на слух.
python3 local/make_ref.py запись.mp3 --out папка [--count 6] [--asr-model gigaam-v3-e2e-rnnt | --no-asr]"""
import argparse
import subprocess
from pathlib import Path

import numpy as np

import book2audio as b
import verify

SR, FRAME = 24000, 480            # 20 мс


def load(path):
    if not Path(path).exists():
        raise SystemExit(f"Нет файла {path}. Проверьте имя и что он лежит в папке Audiobook на Диске")
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def phrases(a, min_pause=0.3):
    """Фразы между паузами -> [(начало, конец)] в отсчётах, и уровень шума."""
    rms = np.sqrt(np.mean(a[: len(a) // FRAME * FRAME].reshape(-1, FRAME) ** 2, axis=1))
    noise = np.percentile(rms, 10)
    voiced = rms > max(noise * 4, 0.004)
    out, start, quiet = [], None, 0
    for i, v in enumerate(voiced):
        if v:
            start = i if start is None else start
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet * FRAME / SR >= min_pause:
                out.append((start * FRAME, (i - quiet + 1) * FRAME))
                start = None
    return out, noise


def candidates(a, lo=7.0, hi=11.0, skip=15.0):
    ph, noise = phrases(a)
    ph = [p for p in ph if p[0] > skip * SR]
    found = []
    for i in range(len(ph)):
        for j in range(i, len(ph)):
            n = (ph[j][1] - ph[i][0]) / SR
            if n > hi:
                break
            if n >= lo and np.abs(a[ph[i][0]:ph[j][1]]).max() < 0.95:
                found.append((ph[i][0], ph[j][1], j + 1 < len(ph) and ph[j + 1][0] or len(a)))
                break
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("--out", required=True)
    p.add_argument("--count", type=int, default=6)
    p.add_argument("--asr-model", default="gigaam-v3-e2e-rnnt")
    p.add_argument("--no-asr", action="store_true")
    args = p.parse_args()
    a = load(args.audio)
    cands = candidates(a)
    if not cands:
        raise SystemExit("Не нашёл подходящих кусков 7–11 с с паузами по краям")
    step = max(len(cands) // args.count, 1)
    picked = cands[::step][: args.count]
    asr = None if args.no_asr else verify.load_asr(args.asr_model)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for n, (s, e, nxt) in enumerate(picked, 1):
        tail = a[e:min(nxt, e + int(0.9 * SR))]                   # ~1 с тишины в конце, как просит F5
        clip = np.concatenate([a[max(s - int(0.1 * SR), 0):e], tail])
        b.save_wav(out / f"ref_{n:02d}.wav", clip, SR)
        text = asr(clip, SR).strip() if asr else ""
        (out / f"ref_{n:02d}.txt").write_text(text, encoding="utf-8")
        print(f"ref_{n:02d}: {len(clip) / SR:.1f} с  {'(есть «?») ' if '?' in text else ''}{text}")


if __name__ == "__main__":
    main()
