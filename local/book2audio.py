#!/usr/bin/env python3
"""Книга (PDF / EPUB / TXT) -> MP3 голосом OmniVoice на Mac с Apple Silicon.

    python3 local/book2audio.py книга.pdf                  # весь текст, стандартный голос
    python3 local/book2audio.py книга.pdf --test           # только 3 первых куска: проверить звук и скорость
    python3 local/book2audio.py --voices 8                 # 8 случайных голосов читают одну фразу: выбрать
    python3 local/book2audio.py книга.pdf --ref voices/voice_03.wav   # вся книга выбранным голосом

Можно прервать (Ctrl+C) и запустить снова: готовые куски пропускаются.
"""
import argparse
import html.parser
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

MODEL = "mlx-community/OmniVoice-bf16"


# ---------- текст из файла ----------
class _Text(html.parser.HTMLParser):
    BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "br"}

    SKIP = {"style", "script", "head"}

    def __init__(self):
        super().__init__()
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def read_epub(path):
    with zipfile.ZipFile(path) as z:
        opf_path = re.search(r'full-path="([^"]+)"', z.read("META-INF/container.xml").decode())[1]
        opf = z.read(opf_path).decode()
        base = opf_path.rpartition("/")[0]
        hrefs = dict(re.findall(r'<item[^>]*?id="([^"]+)"[^>]*?href="([^"]+)"', opf))
        hrefs.update({i: h for h, i in re.findall(r'<item[^>]*?href="([^"]+)"[^>]*?id="([^"]+)"', opf)})
        parts = []
        for idref in re.findall(r'<itemref[^>]*?idref="([^"]+)"', opf):
            name = (base + "/" if base else "") + hrefs[idref]
            p = _Text()
            p.feed(z.read(name).decode("utf-8", "ignore"))
            parts.append("".join(p.out))
    return "\n".join(parts)


def read_pdf(path):
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def read_book(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".epub":
        return read_epub(path)
    return path.read_text(encoding="utf-8")


# ---------- подготовка текста ----------
def clean(raw, numbers=False):
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)              # перенос слова между строками
    text = re.sub(r"^\s*\d{1,4}\s*$", "", text, flags=re.M)   # номера страниц
    text = re.sub(r"[ \t ]+", " ", text)
    if numbers:  # падежи не склоняются: «в одна тысяча … году», поэтому по умолчанию выключено
        from num2words import num2words
        text = re.sub(r"\b\d+\b", lambda m: num2words(int(m[0]), lang="ru"), text)
    return text


def chunk(text, max_chars):
    """Куски по абзацам и предложениям, не длиннее max_chars."""
    chunks, cur = [], ""
    for para in (p.strip() for p in text.split("\n")):
        if not para:
            continue
        for sent in re.findall(r"[^.!?…]+[.!?…]*\s*", para) or [para]:
            sent = sent.strip()
            while len(sent) > max_chars:                       # одно предложение длиннее куска
                cut = max(sent.rfind(" ", 0, max_chars), 0) or max_chars
                if cur:
                    chunks.append(cur)
                    cur = ""
                chunks.append(sent[:cut].strip())
                sent = sent[cut:].strip()
            if cur and len(cur) + len(sent) + 1 > max_chars:
                chunks.append(cur)
                cur = ""
            cur = f"{cur} {sent}".strip()
    if cur:
        chunks.append(cur)
    return chunks


# ---------- озвучка ----------
SAMPLE_TEXT = ("Дорогие друзья, сегодня мы начинаем читать новую книгу. "
               "Слушайте внимательно, потому что каждое слово здесь имеет значение.")


def save_wav(path, a, sr):
    import wave
    import numpy as np
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def make_voices(args):
    """Без образца модель выбирает голос случайно для каждого куска. Здесь одну и ту же
    фразу читают N случайных голосов: лучший берём как образец (--ref voice_03.wav)."""
    import numpy as np
    from mlx_audio.tts.utils import load_model

    out_dir = args.out or Path("voices")
    out_dir.mkdir(exist_ok=True)
    model = load_model(MODEL)
    for n in range(1, args.voices + 1):
        r = next(model.generate(text=SAMPLE_TEXT, language="ru", num_steps=args.steps,
                                duration_s=len(SAMPLE_TEXT) / args.chars_per_sec))
        save_wav(out_dir / f"voice_{n:02d}.wav", tidy(np.array(r.audio), r.sample_rate), r.sample_rate)
        (out_dir / f"voice_{n:02d}.txt").write_text(SAMPLE_TEXT, encoding="utf-8")
        print(f"[{n}/{args.voices}] voice_{n:02d}.wav", flush=True)
    print(f"Готово. Послушай файлы в папке {out_dir} и выбери голос: --ref {out_dir}/voice_НОМЕР.wav")


def synthesize(chunks, out_dir, args):
    import numpy as np
    from mlx_audio.audio_io import write as audio_write
    from mlx_audio.tts.utils import load_model

    model = load_model(MODEL)
    todo = [(i, t) for i, t in enumerate(chunks) if not (out_dir / f"{i:05d}.wav").exists()]
    if args.limit:
        todo = todo[:args.limit]
    started = time.time()
    for n, (i, text) in enumerate(todo, 1):
        kwargs = dict(text=text, language="ru", num_steps=args.steps,
                      duration_s=len(text) / args.chars_per_sec)
        if args.ref:
            kwargs.update(ref_audio=args.ref, ref_text=args.ref_text)
        result = next(model.generate(**kwargs))
        audio_write(str(out_dir / f"{i:05d}.wav"), np.array(result.audio), result.sample_rate)
        per = (time.time() - started) / n
        print(f"[{n}/{len(todo)}] кусок {i + 1}/{len(chunks)}, {per:.1f} с на кусок, "
              f"осталось ~{per * (len(todo) - n) / 60:.0f} мин", flush=True)


def tidy(a, sr, max_pause=0.8, keep_pause=0.5):
    """Обрезает тишину по краям куска и сокращает долгие паузы: модель дотягивает
    речь до заданной длины паузами. Возвращает float32 с паузой 0.35 с в конце."""
    import numpy as np
    hop = int(sr * 0.02)
    n = len(a) // hop
    loud = np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1)) > 0.01  # громче -40 дБ
    if not loud.any():
        return a
    first, last = loud.argmax(), n - 1 - loud[::-1].argmax()
    frames, keep, i = loud[first:last + 1], None, 0
    keep = np.ones(len(frames), bool)
    while i < len(frames):
        if frames[i]:
            i += 1
            continue
        j = i
        while j < len(frames) and not frames[j]:
            j += 1
        if (j - i) * 0.02 > max_pause:
            keep[i + int(keep_pause / 0.02):j] = False
        i = j
    body = a[first * hop:(last + 1) * hop][np.repeat(keep, hop)]
    return np.concatenate([np.zeros(int(sr * 0.1), np.float32), body, np.zeros(int(sr * 0.35), np.float32)])


def join(out_dir, mp3):
    import wave
    import numpy as np
    wavs = sorted(out_dir.glob("[0-9]*.wav"))
    raw = out_dir / "all.raw"
    with raw.open("wb") as out:
        for w in wavs:
            with wave.open(str(w)) as f:
                sr = f.getframerate()
                a = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768
            out.write((tidy(a, sr) * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1",
                    "-i", str(raw), "-b:a", "64k", str(mp3)], check=True)
    raw.unlink()
    print(f"Готово: {mp3} ({len(wavs)} кусков)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path, nargs="?")
    ap.add_argument("--voices", type=int, metavar="N", help="озвучить образец фразы N случайными голосами и выбрать")
    ap.add_argument("--ref", help="WAV с твоим голосом (10–15 секунд) для клонирования")
    ap.add_argument("--ref-text", help="Что сказано в --ref (по умолчанию берётся из файла рядом: voice_03.txt)")
    ap.add_argument("--max-chars", type=int, default=400, help="длина куска, символов (по умолчанию 400)")
    ap.add_argument("--steps", type=int, default=32, help="шаги модели: 16 быстрее, 32 качественнее")
    ap.add_argument("--chars-per-sec", type=float, default=13, help="сколько символов в секунду произносит голос")
    ap.add_argument("--numbers", action="store_true", help="цифры -> слова (нужен pip install num2words)")
    ap.add_argument("--test", action="store_true", help="то же, что --limit 3")
    ap.add_argument("--limit", type=int, help="озвучить только N кусков (без склейки в MP3)")
    ap.add_argument("--out", type=Path, help="папка для кусков (по умолчанию <книга>_audio рядом с книгой)")
    ap.add_argument("--dry-run", action="store_true", help="только разобрать книгу на куски, без озвучки")
    args = ap.parse_args()

    if args.voices:
        return make_voices(args)
    if not args.book:
        ap.error("укажи книгу или --voices N")
    chunks = chunk(clean(read_book(args.book), args.numbers), args.max_chars)
    if not chunks:
        sys.exit("В файле нет текста (возможно, это скан)")
    print(f"Книга: {sum(map(len, chunks))} символов, {len(chunks)} кусков")
    if args.dry_run:
        for c in chunks[:3]:
            print("---", c)
        return
    if args.ref and not args.ref_text:
        side = Path(args.ref).with_suffix(".txt")
        if not side.exists():
            sys.exit("К --ref нужен --ref-text или файл с текстом рядом (voice_03.txt)")
        args.ref_text = side.read_text(encoding="utf-8").strip()

    args.limit = args.limit or (3 if args.test else None)
    out_dir = args.out or args.book.with_name(args.book.stem + "_audio")
    out_dir.mkdir(exist_ok=True)
    synthesize(chunks, out_dir, args)
    if not args.limit:
        join(out_dir, args.book.with_suffix(".mp3"))


if __name__ == "__main__":
    main()
