#!/usr/bin/env python3
"""Книга (PDF / EPUB / TXT) -> MP3 голосом OmniVoice на Mac с Apple Silicon.

    python3 local/book2audio.py --voices 8 --out ~/Desktop/voices        # 8 голосов читают одну фразу: выбрать
    python3 local/book2audio.py книга.epub --ref voices/voice_01.wav --ref2 voices/voice_05.wav
        # основной текст читает первый голос; заголовки, оглавление и примечания (*) — второй
    python3 local/book2audio.py книга.epub --limit 3                     # 3 первых куска: проверить звук и скорость

Можно прервать (Ctrl+C) и запустить снова: готовые куски пропускаются.
Через каждые --part кусков (≈ 40 минут звука) появляется отдельный MP3: слушать можно, пока идёт озвучка.
"""
import argparse
import hashlib
import html.parser
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

MODEL = "mlx-community/OmniVoice-bf16"
MAIN, SIDE = "main", "side"          # основной голос / второй (заголовки, оглавление, примечания)
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


# ---------- текст из файла ----------
class _Paras(html.parser.HTMLParser):
    """Абзацы страницы: (тег, класс, текст)."""
    BLOCKS = {"p", "div", "li", "blockquote"} | HEADINGS
    SKIP = {"style", "script", "head"}

    def __init__(self):
        super().__init__()
        self.paras, self.buf, self.skip, self.tag, self.cls = [], [], 0, "", ""

    def flush(self):
        text = "".join(self.buf).strip()
        if text:
            self.paras.append((self.tag, self.cls, text))
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCKS:
            self.flush()
            self.tag, self.cls = tag, dict(attrs).get("class") or ""
        elif tag == "br":
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip -= 1
        elif tag in self.BLOCKS:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def _attrs(tag):
    return dict(re.findall(r'([\w:-]+)="([^"]*)"', tag))


def _centered_or_bold(z):
    """Классы CSS, которыми набраны заголовки: по центру или жирным."""
    found = set()
    for name in z.namelist():
        if name.endswith(".css"):
            for cls, body in re.findall(r"\.([\w-]+)\s*\{([^}]*)\}", z.read(name).decode("utf-8", "ignore")):
                if re.search(r"text-align:\s*center|font-weight:\s*bold", body):
                    found.add(cls)
    return found


def role_of(tag, cls, text, headings):
    """Второй голос: заголовки, примечания (с «*») и короткие абзацы по центру или жирным."""
    if tag in HEADINGS or text.startswith("*"):
        return SIDE
    if len(text) <= 150 and any(c in headings for c in cls.split()):
        return SIDE
    return MAIN


def read_epub(path):
    with zipfile.ZipFile(path) as z:
        opf_path = re.search(r'full-path="([^"]+)"', z.read("META-INF/container.xml").decode())[1]
        opf = z.read(opf_path).decode()
        base = opf_path.rpartition("/")[0]
        manifest = {a["id"]: a for a in map(_attrs, re.findall(r"<item\b[^>]*>", opf)) if "id" in a}
        headings = _centered_or_bold(z)

        def read(href):
            return z.read((base + "/" if base else "") + href).decode("utf-8", "ignore")

        items = []
        nav = next((a["href"] for a in manifest.values() if "nav" in a.get("properties", "").split()), None)
        if nav:  # оглавление лежит вне основного текста — читаем его в начале
            titles = [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t))).strip()
                      for t in re.findall(r"<a\b[^>]*>(.*?)</a>", read(nav), flags=re.S)]
            if any(titles):
                items += [(SIDE, "Оглавление.")] + [(SIDE, t) for t in titles if t]
        for idref in re.findall(r'<itemref\b[^>]*?idref="([^"]+)"', opf):
            p = _Paras()
            p.feed(read(manifest[idref]["href"]))
            p.flush()
            items += [(role_of(tag, cls, text, headings), text) for tag, cls, text in p.paras]
    return items


def read_pdf(path):
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def read_book(path):
    """Список (роль, текст). Роли различает только EPUB; PDF и TXT читает один голос."""
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return read_epub(path)
    return [(MAIN, read_pdf(path) if suffix == ".pdf" else path.read_text(encoding="utf-8"))]


# ---------- подготовка текста ----------
def clean(raw, numbers=False):
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)              # перенос слова между строками
    text = re.sub(r"^\s*\d{1,4}\s*$", "", text, flags=re.M)   # номера страниц
    text = text.replace("*", "")                              # звёздочки сносок
    text = re.sub(r"[ \t ]+", " ", text)
    if numbers:  # падежи не склоняются: «в одна тысяча … году», поэтому по умолчанию выключено
        from num2words import num2words
        text = re.sub(r"\b\d+\b", lambda m: num2words(int(m[0]), lang="ru"), text)
    return text


def chunk(items, max_chars):
    """Куски по абзацам и предложениям, не длиннее max_chars; голос в куске один. -> [(роль, текст)]"""
    chunks, cur, role = [], "", MAIN
    for r, raw in items:
        if r != role and cur:
            chunks.append((role, cur))
            cur = ""
        role = r
        for para in (p.strip() for p in raw.split("\n")):
            if not para:
                continue
            if role == SIDE and para[-1] not in ".!?…:;":
                para += "."                                    # заголовку нужна пауза после
            for sent in re.findall(r"[^.!?…]+[.!?…]*\s*", para) or [para]:
                sent = sent.strip()
                while len(sent) > max_chars:                   # одно предложение длиннее куска
                    cut = max(sent.rfind(" ", 0, max_chars), 0) or max_chars
                    if cur:
                        chunks.append((role, cur))
                        cur = ""
                    chunks.append((role, sent[:cut].strip()))
                    sent = sent[cut:].strip()
                if cur and len(cur) + len(sent) + 1 > max_chars:
                    chunks.append((role, cur))
                    cur = ""
                cur = f"{cur} {sent}".strip()
    if cur:
        chunks.append((role, cur))
    return chunks


# ---------- то, что уходит в модель ----------
def load_fixes(path):
    """Файл поправок: «слово = как его записать», по одной строке; # — комментарий. -> [(слово, замена)]"""
    fixes = []
    if path and Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                word, repl = line.split("=", 1)
                if word.strip():
                    fixes.append((word.strip(), repl.strip()))
    return fixes


def speak(text, fixes=()):
    """Текст куска для модели. Границы куска ломают озвучку: запятая в начале, многоточие
    или обрыв без знака в конце дают лишние звуки. Разбивку на куски это не меняет."""
    t = re.sub(r"[=_~#*-]{3,}", " ", text).strip()                      # строки-разделители
    t = re.sub(r"^[^\w«\"“(—]+", "", t)                                 # не начинать со знака
    t = re.sub(r"\(\s*[^()А-Яа-яЁё]*[A-Za-z][^()А-Яа-яЁё]*\)", " ", t)    # (Brahm), (PAUSANIAS, Attica): латиница в скобках
    t = re.sub(r"(?:\b[A-Za-z][\w'’.\-]*[,.;]?\s+){2,}[A-Za-z][\w'’.\-]*", " ", t)  # три и больше латинских слов подряд
    t = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s{2,}", " ", t)).strip()
    t = re.sub(r"\b[А-ЯЁ]{3,}\b", lambda m: m[0].capitalize(), t)        # ЙАУХУ -> Йаухy: слова КАПСОМ модель читает набором звуков
    t = re.sub(r"(\.\.\.|…)+\s*$", ".", t)                              # многоточие в конце -> точка
    if re.search(r"\w$", t):
        t += ","                                                        # оборванный кусок: пауза, а не обрыв
    for word, repl in fixes:
        t = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", lambda m: repl, t)
    return t


def text_hash(t):
    return hashlib.sha1(t.encode()).hexdigest()[:12]


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
    frames, i = loud[first:last + 1], 0
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


def make_voices(args):
    """Без образца модель выбирает голос случайно для каждого куска. Здесь одну и ту же
    фразу читают N случайных голосов: выбранные берём как образцы (--ref, --ref2)."""
    import numpy as np
    from mlx_audio.tts.utils import load_model

    out_dir = args.out or Path("voices")
    out_dir.mkdir(exist_ok=True)
    model = load_model(MODEL)
    for n in range(1, args.voices + 1):
        r = next(model.generate(text=SAMPLE_TEXT, language="ru", num_steps=args.steps,
                                guidance_scale=args.guidance, duration_s=len(SAMPLE_TEXT) / args.chars_per_sec))
        save_wav(out_dir / f"voice_{n:02d}.wav", tidy(np.array(r.audio), r.sample_rate), r.sample_rate)
        (out_dir / f"voice_{n:02d}.txt").write_text(SAMPLE_TEXT, encoding="utf-8")
        print(f"[{n}/{args.voices}] voice_{n:02d}.wav", flush=True)
    print(f"Готово. Послушай файлы в папке {out_dir}.\n"
          f"Основной голос и второй: --ref {out_dir}/voice_НОМЕР.wav --ref2 {out_dir}/voice_НОМЕР.wav")


def ref_text_file(ref):
    side = Path(ref).expanduser().with_suffix(".txt")
    if not side.exists():
        sys.exit(f"Рядом с {ref} нужен файл {side.name} с точным текстом записи")
    return side


def load_voice(model, ref):
    from mlx_audio.tts.models.omnivoice.utils import create_voice_clone_prompt
    tokens = create_voice_clone_prompt(str(Path(ref).expanduser()), tokenizer=model.audio_tokenizer,
                                       max_duration_s=10.0)
    return tokens, ref_text_file(ref).read_text(encoding="utf-8").strip()


def synthesize(chunks, out_dir, base, args):
    import numpy as np
    from mlx_audio.tts.utils import load_model

    model = load_model(MODEL)
    voices = {}
    if args.ref:
        voices[MAIN] = load_voice(model, args.ref)
        voices[SIDE] = load_voice(model, args.ref2) if args.ref2 else voices[MAIN]
    todo = [i for i in range(len(chunks)) if not (out_dir / f"{i:05d}.wav").exists()]
    if args.limit:
        todo = todo[:args.limit]
    common = dict(language="ru", num_steps=args.steps, guidance_scale=args.guidance)
    started = time.time()
    for g in range(0, len(todo), args.batch):
        ids = todo[g:g + args.batch]
        kws = []
        for i in ids:
            role, text = chunks[i]
            kw = dict(text=text, duration_s=len(text) / args.chars_per_sec)
            if role in voices:
                kw["ref_tokens"], kw["ref_text"] = voices[role]
            kws.append(kw)
        if len(ids) == 1:
            results = [next(model.generate(**kws[0], **common))]
        else:
            batch = dict(text=[k["text"] for k in kws], duration_s=[k["duration_s"] for k in kws],
                         max_batch_size=len(ids), **common)
            if voices:
                batch["ref_tokens"] = [k["ref_tokens"] for k in kws]
                batch["ref_text"] = [k["ref_text"] for k in kws]
            results = model.generate_batch(**batch)
        for i, r in zip(ids, results):
            save_wav(out_dir / f"{i:05d}.wav", np.array(r.audio), r.sample_rate)
        done = g + len(ids)
        per = (time.time() - started) / done
        print(f"[{done}/{len(todo)}] кусок {ids[-1] + 1}/{len(chunks)}, {per:.1f} с на кусок, "
              f"осталось ~{per * (len(todo) - done) / 3600:.1f} ч", flush=True)
        if not args.limit:
            join(out_dir, base, len(chunks), args.part)


def join(out_dir, base, total, part_size):
    """MP3 на каждые part_size кусков; файл появляется, когда готовы все куски части."""
    import wave
    import numpy as np
    for start in range(0, total, part_size):
        ids = range(start, min(start + part_size, total))
        mp3 = base.with_name(f"{base.name}_часть{start // part_size + 1:02d}.mp3")
        if mp3.exists() or not all((out_dir / f"{i:05d}.wav").exists() for i in ids):
            continue
        raw = out_dir / "part.raw"
        with raw.open("wb") as out:
            for i in ids:
                with wave.open(str(out_dir / f"{i:05d}.wav")) as f:
                    sr = f.getframerate()
                    a = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768
                out.write((tidy(a, sr) * 32767).astype(np.int16).tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1",
                        "-i", str(raw), "-b:a", "64k", str(mp3)], check=True)
        raw.unlink()
        print(f"Готово: {mp3.name}", flush=True)


def guard(out_dir, chunks, refs):
    """Куски от другой книги или другого голоса нельзя смешивать: сверяем отпечаток запуска."""
    sig = hashlib.sha1(json.dumps(chunks).encode())
    for r in refs:
        sig.update(Path(r).expanduser().read_bytes())
    file = out_dir / "run.json"
    if file.exists() and json.loads(file.read_text())["sig"] != sig.hexdigest():
        sys.exit(f"В папке {out_dir} лежат куски от другого запуска (другая книга, голоса или разбор текста).\n"
                 "Удали папку или укажи другую через --out.")
    file.write_text(json.dumps({"sig": sig.hexdigest()}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path, nargs="?")
    ap.add_argument("--voices", type=int, metavar="N", help="озвучить образец фразы N случайными голосами и выбрать")
    ap.add_argument("--ref", help="WAV основного голоса (до 10 секунд); рядом должен лежать .txt с текстом записи")
    ap.add_argument("--ref2", help="WAV второго голоса: заголовки, оглавление, примечания (только EPUB)")
    ap.add_argument("--max-chars", type=int, default=400, help="длина куска, символов (по умолчанию 400)")
    ap.add_argument("--steps", type=int, default=16, help="шаги модели: 16 в два раза быстрее 32, 32 качественнее")
    ap.add_argument("--guidance", type=float, default=2.0, help="сила следования тексту; 0 отключает и ускоряет")
    ap.add_argument("--batch", type=int, default=1, help="сколько кусков озвучивать одновременно")
    ap.add_argument("--part", type=int, default=100, help="кусков в одном MP3 (по умолчанию 100)")
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
    items = [(r, clean(t, args.numbers)) for r, t in read_book(args.book)]
    chunks = chunk(items, args.max_chars)
    if not chunks:
        sys.exit("В файле нет текста (возможно, это скан)")
    side = [t for r, t in chunks if r == SIDE]
    print(f"Книга: {sum(len(t) for _, t in chunks)} символов, {len(chunks)} кусков "
          f"(второй голос: {len(side)} кусков, {sum(map(len, side))} символов)")
    if args.dry_run:
        for r, t in chunks[:2] + [c for c in chunks if c[0] == SIDE][2:5]:
            print(f"--- [{r}]", t[:160])
        return
    refs = [r for r in (args.ref, args.ref2) if r]
    if args.ref2 and not args.ref:
        sys.exit("--ref2 работает только вместе с --ref")
    for r in refs:
        ref_text_file(r)

    out_dir = args.out or args.book.with_name(args.book.stem + "_audio")
    out_dir.mkdir(exist_ok=True)
    guard(out_dir, chunks, refs)
    args.limit = args.limit or (3 if args.test else None)
    synthesize(chunks, out_dir, args.book.with_suffix(""), args)
    if not args.limit:
        print("Готово.")


if __name__ == "__main__":
    main()
