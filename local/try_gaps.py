"""Проба пауз между словами: python try_gaps.py кусок.wav [--out папка] [--factors 1 1.3 1.6 2]
Один кусок записывается несколькими вариантами (1 = как сейчас). Темп слов не меняется."""
import argparse
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import book2audio as b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", type=Path)
    ap.add_argument("--out", type=Path, default=Path("gaps"))
    ap.add_argument("--factors", type=float, nargs="+", default=[1, 1.3, 1.6, 2])
    args = ap.parse_args()
    with wave.open(str(args.wav)) as f:
        sr = f.getframerate()
        a = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768
    args.out.mkdir(parents=True, exist_ok=True)
    base = b.tidy(a, sr)
    for k in args.factors:
        out = args.out / f"{args.wav.stem}_x{k:g}.wav"
        b.save_wav(out, b.widen_gaps(base, sr, k), sr)
        print(f"{out.name}: {len(b.widen_gaps(base, sr, k)) / sr:.1f} с")


if __name__ == "__main__":
    main()
