#!/usr/bin/env python3
"""Книга (PDF / EPUB / TXT) -> MP3 голосом OmniVoice на Mac с Apple Silicon.

    python3 local/book2audio.py книга.pdf                  # весь текст, стандартный голос
    python3 local/book2audio.py книга.pdf --test           # только 3 первых куска: проверить звук и скорость
    python3 local/book2audio.py книга.pdf --ref голос.wav --ref-text "что сказано в голос.wav"

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

    def __init__(self):
        super().__init__()
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
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
def synthesize(chunks, out_dir, args):
    import numpy as np
    from mlx_audio.audio_io import write as audio_write
    from mlx_audio.tts.utils import load_model

    model = load_model(MODEL)
    todo = [(i, t) for i, t in enumerate(chunks) if not (out_dir / f"{i:05d}.wav").exists()]
    if args.test:
        todo = todo[:3]
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


def join(out_dir, mp3):
    wavs = sorted(out_dir.glob("*.wav"))
    listing = out_dir / "list.txt"
    listing.write_text("".join(f"file '{w.resolve()}'\n" for w in wavs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-b:a", "64k", str(mp3)], check=True)
    print(f"Готово: {mp3} ({len(wavs)} кусков)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("--ref", help="WAV с твоим голосом (10–15 секунд) для клонирования")
    ap.add_argument("--ref-text", help="Что сказано в --ref (точный текст)")
    ap.add_argument("--max-chars", type=int, default=400, help="длина куска, символов (по умолчанию 400)")
    ap.add_argument("--steps", type=int, default=32, help="шаги модели: 16 быстрее, 32 качественнее")
    ap.add_argument("--chars-per-sec", type=float, default=13, help="сколько символов в секунду произносит голос")
    ap.add_argument("--numbers", action="store_true", help="цифры -> слова (нужен pip install num2words)")
    ap.add_argument("--test", action="store_true", help="озвучить только 3 первых куска")
    ap.add_argument("--dry-run", action="store_true", help="только разобрать книгу на куски, без озвучки")
    args = ap.parse_args()

    chunks = chunk(clean(read_book(args.book), args.numbers), args.max_chars)
    if not chunks:
        sys.exit("В файле нет текста (возможно, это скан)")
    print(f"Книга: {sum(map(len, chunks))} символов, {len(chunks)} кусков")
    if args.dry_run:
        for c in chunks[:3]:
            print("---", c)
        return
    if args.ref and not args.ref_text:
        sys.exit("К --ref нужен --ref-text: точный текст из записи")

    out_dir = args.book.with_suffix("").with_name(args.book.stem + "_audio")
    out_dir.mkdir(exist_ok=True)
    synthesize(chunks, out_dir, args)
    if not args.test:
        join(out_dir, args.book.with_suffix(".mp3"))


if __name__ == "__main__":
    main()
