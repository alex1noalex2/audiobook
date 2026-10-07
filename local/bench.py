#!/usr/bin/env python3
"""Стенд для проб: несколько коротких отрывков книги в разных вариантах озвучки.
На Mac (MLX) или на видеокарте (Colab); движок выбирается сам, или --engine mlx / cuda.

    python3 local/bench.py книга.epub --ref voice_05.wav --ref2 voice_06.wav --out bench \\
        --at 0.25 0.5 0.75 --words 200 --variants base caps caps+capsref base+gaps1.4 base+phone

Отрывки: для каждой доли книги (--at) выбирается окно кусков примерно на --words слов, где больше всего имён и есть
примечание. Каждый отрывок озвучивается всеми вариантами (--variants), результат: p1_base.mp3, p1_caps.mp3 …
и оценка.md с текстом, ссылками на файлы и пустой таблицей для оценки.

Вариант — слова через «+»:
  base      как сейчас
  caps      ударные гласные по Silero Stress, заглавными (pip install silero-stress)
  capsref   то же и в записи образца голоса (включает caps)
  gapsX     паузы между словами в X раз длиннее (gaps1.4)
  stepsN    N шагов модели (steps32)
  speedX    скорость речи (speed0.95)
  phone     примечания тем же голосом, что основной текст, с эффектом телефона
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book2audio as b  # noqa: E402
import ru_text  # noqa: E402


def parse_variant(spec):
    v = dict(spec=spec, caps=False, capsref=False, gaps=1.0, steps=None, speed=None, phone=False)
    for tok in spec.split("+"):
        if tok == "base":
            continue
        elif tok == "caps":
            v["caps"] = True
        elif tok == "capsref":
            v["caps"] = v["capsref"] = True
        elif tok == "phone":
            v["phone"] = True
        elif re.fullmatch(r"gaps[\d.]+", tok):
            v["gaps"] = float(tok[4:])
        elif re.fullmatch(r"steps\d+", tok):
            v["steps"] = int(tok[5:])
        elif re.fullmatch(r"speed[\d.]+", tok):
            v["speed"] = float(tok[5:])
        else:
            sys.exit(f"Неизвестная часть варианта «{tok}» в «{spec}». См. python3 local/bench.py --help")
    return v


def pick_passages(chunks, fractions, n_words):
    """Для каждой доли книги: окно подряд идущих кусков на ~n_words слов с наибольшим числом разных имён
    (слов с заглавной буквы); в окне должен быть основной текст, примечание или заголовок поощряются."""
    found, taken = [], set()
    for f in fractions:
        centre, best = int(f * len(chunks)), None
        for s in range(max(0, centre - 40), min(len(chunks), centre + 40)):
            e, w = s, 0
            while e < len(chunks) and w < n_words:
                w += len(chunks[e][1].split())
                e += 1
            if w < n_words * 0.8 or taken & set(range(s, e)):
                continue
            text = " ".join(t for _, t in chunks[s:e])
            sides = sum(r == b.SIDE for r, _ in chunks[s:e])
            if e - s - sides < 2:
                continue                                        # нужен и основной текст, не одни примечания
            score = len(set(re.findall(r"\b[А-ЯЁ][а-яё]{3,}\b", text))) + (5 if sides else 0)
            if best is None or score > best[0]:
                best = (score, s, e)
        if best is None:
            sys.exit(f"Не нашлось отрывка около {f:.0%} книги")
        taken |= set(range(best[1], best[2]))
        found.append((best[1], best[2]))
    return found


def engine_cuda(args, accentor):
    """OmniVoice на видеокарте NVIDIA: пачками. Возвращает (voice, generate)."""
    import torch
    from omnivoice import OmniVoice

    model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)
    cache = {}

    def voice(ref, marked):
        if (ref, marked) not in cache:
            text = b.ref_text_file(ref).read_text(encoding="utf-8").strip()
            cache[(ref, marked)] = model.create_voice_clone_prompt(
                ref_audio=str(Path(ref).expanduser()), ref_text=ru_text.caps_stress(accentor(text)) if marked else text)
        return cache[(ref, marked)]

    def run(texts, vps, **opts):
        try:
            return model.generate(text=texts, voice_clone_prompt=vps, **opts)
        except RuntimeError as e:  # не хватило памяти видеокарты: делим пачку пополам
            if "out of memory" not in str(e) or len(texts) == 1:
                raise
            torch.cuda.empty_cache()
            half = len(texts) // 2
            return run(texts[:half], vps[:half], **opts) + run(texts[half:], vps[half:], **opts)

    def generate(texts, vps, steps, speed):
        opts = dict(language="ru", num_step=steps, guidance_scale=args.guidance)
        if speed:
            opts["speed"] = speed
        return [(a, model.sampling_rate) for a in run(texts, vps, **opts)]

    return voice, generate


def engine_mlx(args, accentor):
    """OmniVoice на Mac (mlx-audio). Возвращает (voice, generate)."""
    import numpy as np
    from mlx_audio.tts.models.omnivoice.utils import create_voice_clone_prompt
    from mlx_audio.tts.utils import load_model

    model = load_model(b.MODEL)
    cache = {}

    def voice(ref, marked):
        if (ref, marked) not in cache:
            text = b.ref_text_file(ref).read_text(encoding="utf-8").strip()
            tokens = create_voice_clone_prompt(str(Path(ref).expanduser()), tokenizer=model.audio_tokenizer,
                                               max_duration_s=10.0)
            cache[(ref, marked)] = (tokens, ru_text.caps_stress(accentor(text)) if marked else text)
        return cache[(ref, marked)]

    def generate(texts, vps, steps, speed):
        cps = args.chars_per_sec * (speed or 1)
        common = dict(language="ru", num_steps=steps, guidance_scale=args.guidance)
        out = []
        for g in range(0, len(texts), args.batch):
            t, v = texts[g:g + args.batch], vps[g:g + args.batch]
            dur = [len(x) / cps for x in t]
            if len(t) == 1:
                results = [next(model.generate(text=t[0], duration_s=dur[0], ref_tokens=v[0][0], ref_text=v[0][1], **common))]
            else:
                results = model.generate_batch(text=t, duration_s=dur, max_batch_size=len(t), ref_tokens=[x[0] for x in v],
                                               ref_text=[x[1] for x in v], **common)
            out += [(np.array(r.audio), r.sample_rate) for r in results]
        try:
            import mlx.core as mx
            mx.clear_cache()                                        # на 16 ГБ память иначе копится, и macOS убивает процесс
        except (ImportError, AttributeError):
            pass
        return out

    return voice, generate


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("--ref", required=True, help="WAV основного голоса; рядом лежит .txt с текстом записи")
    ap.add_argument("--ref2", help="WAV второго голоса (заголовки и примечания)")
    ap.add_argument("--out", type=Path, default=Path("bench"))
    ap.add_argument("--at", type=float, nargs="+", default=[0.25, 0.5, 0.75], help="доли книги, где брать отрывки")
    ap.add_argument("--words", type=int, default=200, help="слов в отрывке")
    ap.add_argument("--variants", nargs="+", default=["base", "caps", "caps+capsref", "base+gaps1.4", "base+phone"])
    ap.add_argument("--max-chars", type=int, default=400)
    ap.add_argument("--steps", type=int, default=16)
    ap.add_argument("--guidance", type=float, default=2.0)
    ap.add_argument("--engine", choices=["mlx", "cuda"], default="mlx" if sys.platform == "darwin" else "cuda")
    ap.add_argument("--batch", type=int, default=2, help="сколько кусков озвучивать одновременно (на Mac)")
    ap.add_argument("--chars-per-sec", type=float, default=13, help="сколько символов в секунду произносит голос (Mac)")
    ap.add_argument("--fixes", type=Path, help="файл поправок (по умолчанию fixes.txt рядом с книгой)")
    args = ap.parse_args()

    import numpy as np

    variants = [parse_variant(s) for s in args.variants]
    accentor = None
    if any(v["caps"] for v in variants):
        try:
            from silero_stress import load_accentor
        except ImportError:
            sys.exit("Нужен Silero Stress: pip install silero-stress")
        accentor = load_accentor()

    chunks = b.chunk([(r, b.clean(t, False)) for r, t in b.read_book(args.book)], args.max_chars)
    fixes = b.load_fixes(args.fixes or args.book.with_name("fixes.txt"))
    passages = pick_passages(chunks, args.at, args.words)
    args.out.mkdir(parents=True, exist_ok=True)

    voice, generate = (engine_mlx if args.engine == "mlx" else engine_cuda)(args, accentor)

    sheet = ["# Оценка проб\n", f"Книга: {args.book.name}. Варианты: {', '.join(args.variants)}.\n"]
    for k, (s, e) in enumerate(passages, 1):
        ids = list(range(s, e))
        sheet.append(f"\n## Отрывок {k}: куски {s}–{e - 1}, около {s / len(chunks):.0%} книги\n")
        sheet.append("\n".join(f"> {'(примечание) ' if chunks[i][0] == b.SIDE else ''}{chunks[i][1]}" for i in ids))
        sheet.append("\n| Вариант | Файл | Оценка 1–10 | Ошибки (минута, слово, что не так) |\n|---|---|---|---|")
        for v in variants:
            name = f"p{k}_{v['spec'].replace('+', '_')}"
            if (args.out / f"{name}.mp3").exists():                 # прогон оборвался: готовые варианты не пересчитываем
                print(f"Уже есть: {name}.mp3", flush=True)
                sheet.append(f"| {v['spec']} | {name}.mp3 |  |  |")
                continue
            texts = []
            for i in ids:
                t = b.speak(chunks[i][1], fixes)
                texts.append(ru_text.caps_stress(accentor(t)) if v["caps"] and re.search(r"[А-Яа-яЁё]", t) else t)
            vps = []
            for i in ids:
                ref = args.ref2 if chunks[i][0] == b.SIDE and args.ref2 and not v["phone"] else args.ref
                vps.append(voice(ref, v["capsref"]))
            parts = []
            for i, (audio, sr) in zip(ids, generate(texts, vps, v["steps"] or args.steps, v["speed"])):
                a = b.tidy(np.asarray(audio, dtype=np.float32), sr)
                a = b.widen_gaps(a, sr, v["gaps"])
                if v["phone"] and chunks[i][0] == b.SIDE:
                    a = b.phone_effect(a, sr)
                parts.append(a)
            b.save_wav(args.out / f"{name}.wav", np.concatenate(parts), sr)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(args.out / f"{name}.wav"),
                            "-b:a", "96k", str(args.out / f"{name}.mp3")], check=True)
            (args.out / f"{name}.wav").unlink()
            (args.out / f"{name}.txt").write_text("\n\n".join(texts), encoding="utf-8")
            print(f"Готово: {name}.mp3", flush=True)
            sheet.append(f"| {v['spec']} | {name}.mp3 |  |  |")
    (args.out / "оценка.md").write_text("\n".join(sheet) + "\n", encoding="utf-8")
    print(f"\nГотово: {len(passages)} отрывков × {len(variants)} вариантов в {args.out}")
    if sys.platform == "darwin":
        subprocess.run(["open", str(args.out)])


if __name__ == "__main__":
    main()
