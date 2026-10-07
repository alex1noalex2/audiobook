"""Оглавление с таймкодами для готового MP3: python timecodes.py книга.epub папка_с_кусками [--out файл.txt]

Заголовок — отдельный кусок второго голоса до 150 символов, после которого читает основной (оглавление в начале
книги склеено в длинные куски и сюда не попадает). Начало каждой части берётся из длины её MP3, внутри части —
по длине WAV (если WAV нет, по числу символов), поэтому ошибка в пределах нескольких секунд.
"""
import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import book2audio as b


def mp3_seconds(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", str(p)]))


def wav_seconds(p):
    with wave.open(str(p)) as f:
        a = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768
        return len(b.tidy(a, f.getframerate())) / f.getframerate()


def stamp(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("audio", type=Path, help="папка с WAV; части MP3 лежат рядом: <книга>_часть01.mp3")
    ap.add_argument("--part", type=int, default=100)
    ap.add_argument("--max-chars", type=int, default=400)
    ap.add_argument("--out", type=Path, default=Path("timecodes.txt"))
    args = ap.parse_args()

    chunks = b.chunk([(r, b.clean(t, False)) for r, t in b.read_book(args.book)], args.max_chars)
    base = args.book.with_suffix("")
    start, starts = 0.0, {}
    for idx in range((len(chunks) + args.part - 1) // args.part):
        ids = range(idx * args.part, min((idx + 1) * args.part, len(chunks)))
        mp3 = base.with_name(f"{base.name}_часть{idx + 1:02d}.mp3")
        if not mp3.exists():
            sys.exit(f"Нет {mp3.name}: таймкоды считаются по готовым частям")
        total = mp3_seconds(mp3)
        wavs = [args.audio / f"{i:05d}.wav" for i in ids]
        exact = all(p.exists() for p in wavs)
        w = [wav_seconds(p) for p in wavs] if exact else [len(chunks[i][1]) for i in ids]
        k = total / sum(w)
        print(f"часть {idx + 1:02d}: MP3 {total:7.1f} с, {'WAV ' + format(sum(w), '7.1f') + ' с' if exact else 'WAV нет, по символам'}, "
              f"отношение {k:.4f}", file=sys.stderr)
        for i, x in zip(ids, w):
            starts[i] = start
            start += x * k

    lines = []
    for i, (role, text) in enumerate(chunks):
        if role == b.SIDE and len(text) <= 150 and (i + 1 == len(chunks) or chunks[i + 1][0] == b.MAIN):
            lines.append(f"{stamp(starts[i])} {text.rstrip('.').strip()}")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n{len(lines)} заголовков, всего {stamp(start)}; записано в {args.out}")


if __name__ == "__main__":
    main()
