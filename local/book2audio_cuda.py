#!/usr/bin/env python3
"""Книга -> MP3 на бесплатной видеокарте NVIDIA (Google Colab, Kaggle). Тот же разбор книги,
голоса и части MP3, что в book2audio.py, но озвучка оригинальной OmniVoice пачками.

    python3 local/book2audio_cuda.py книга.epub --ref voice_05.wav --ref2 voice_06.wav
    python3 local/book2audio_cuda.py книга.epub --ref voice_05.wav --limit 8     # проверка скорости
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book2audio as b  # noqa: E402


def synthesize(chunks, out_dir, base, args):
    import numpy as np
    import torch
    from omnivoice import OmniVoice

    model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)

    def voice(ref):
        return model.create_voice_clone_prompt(ref_audio=str(Path(ref).expanduser()),
                                               ref_text=b.ref_text_file(ref).read_text(encoding="utf-8").strip())

    prompts = {b.MAIN: voice(args.ref)}
    prompts[b.SIDE] = voice(args.ref2) if args.ref2 else prompts[b.MAIN]
    fixes = b.load_fixes(args.fixes or args.book.with_name("fixes.txt"))
    spoken = [b.speak(t, fixes) for _, t in chunks]
    log_file = out_dir / "spoken.json"  # какой текст ушёл в модель для готовых кусков
    log = json.loads(log_file.read_text()) if log_file.exists() else {}
    redo = {int(i) for i in args.redo.split(",") if i} if args.redo else set()
    if args.redo_changed:  # у кусков, озвученных до поправок, в логе нет записи: считаем, что ушёл исходный текст
        redo |= {i for i in range(len(chunks)) if (out_dir / f"{i:05d}.wav").exists()
                 and log.get(str(i), b.text_hash(chunks[i][1])) != b.text_hash(spoken[i])}
    dirty_file = out_dir / "dirty_parts.json"  # части, которые надо собрать заново; старые MP3 лежат, пока не готова новая
    dirty = set(json.loads(dirty_file.read_text())) if dirty_file.exists() else set()
    for i in sorted(redo):
        (out_dir / f"{i:05d}.wav").unlink(missing_ok=True)
        dirty.add(i // args.part)
    dirty_file.write_text(json.dumps(sorted(dirty)))
    if redo:
        print(f"Переозвучить кусков: {len(redo)}")
    todo = [i for i in range(len(chunks)) if not (out_dir / f"{i:05d}.wav").exists()]
    if args.limit:
        todo = todo[:args.limit]
    for i in [i for i in todo if not re.search(r"[А-Яа-яЁё]", spoken[i])]:  # нечего читать (адрес, ссылка): тишина
        b.save_wav(out_dir / f"{i:05d}.wav", np.zeros(int(0.3 * model.sampling_rate), np.float32), model.sampling_rate)
        log[str(i)] = b.text_hash(spoken[i])
        todo.remove(i)
    opts = dict(language="ru", num_step=args.steps, guidance_scale=args.guidance)
    if args.speed:
        opts["speed"] = args.speed

    def generate(ids):
        try:
            return model.generate(text=[spoken[i] for i in ids],
                                  voice_clone_prompt=[prompts[chunks[i][0]] for i in ids], **opts)
        except RuntimeError as e:  # не хватило памяти видеокарты: делим пачку пополам
            if "out of memory" not in str(e) or len(ids) == 1:
                raise
            torch.cuda.empty_cache()
            half = len(ids) // 2
            return generate(ids[:half]) + generate(ids[half:])

    started = time.time()
    for g in range(0, len(todo), args.batch):
        ids = todo[g:g + args.batch]
        for i, audio in zip(ids, generate(ids)):
            b.save_wav(out_dir / f"{i:05d}.wav", np.asarray(audio, dtype=np.float32), model.sampling_rate)
            log[str(i)] = b.text_hash(spoken[i])
        log_file.write_text(json.dumps(log))
        done = g + len(ids)
        per = (time.time() - started) / done
        print(f"[{done}/{len(todo)}] кусок {ids[-1] + 1}/{len(chunks)}, {per:.1f} с на кусок, "
              f"осталось ~{per * (len(todo) - done) / 3600:.1f} ч", flush=True)
        if not args.limit:
            dirty -= set(b.join(out_dir, base, len(chunks), args.part, force=dirty))
            dirty_file.write_text(json.dumps(sorted(dirty)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("--ref", required=True, help="WAV основного голоса; рядом лежит .txt с текстом записи")
    ap.add_argument("--ref2", help="WAV второго голоса: заголовки, оглавление, примечания (только EPUB)")
    ap.add_argument("--out", type=Path, help="папка для кусков (по умолчанию <книга>_audio рядом с книгой)")
    ap.add_argument("--max-chars", type=int, default=400, help="длина куска, символов")
    ap.add_argument("--steps", type=int, default=32, help="шаги модели: 16 быстрее, 32 качественнее")
    ap.add_argument("--guidance", type=float, default=2.0)
    ap.add_argument("--speed", type=float, help="скорость речи: больше 1 быстрее, меньше 1 медленнее")
    ap.add_argument("--batch", type=int, default=8, help="сколько кусков озвучивать одновременно")
    ap.add_argument("--part", type=int, default=100, help="кусков в одном MP3")
    ap.add_argument("--numbers", action="store_true", help="цифры -> слова (нужен num2words)")
    ap.add_argument("--limit", type=int, help="озвучить только N кусков (без склейки в MP3)")
    ap.add_argument("--fixes", type=Path, help="файл поправок «слово = замена» (по умолчанию fixes.txt рядом с книгой)")
    ap.add_argument("--redo", help="номера кусков через запятую, которые переозвучить: 102,540")
    ap.add_argument("--redo-changed", action="store_true", help="переозвучить куски, текст которых для модели изменился")
    args = ap.parse_args()

    chunks = b.chunk([(r, b.clean(t, args.numbers)) for r, t in b.read_book(args.book)], args.max_chars)
    if not chunks:
        sys.exit("В файле нет текста (возможно, это скан)")
    print(f"Книга: {sum(len(t) for _, t in chunks)} символов, {len(chunks)} кусков")
    refs = [r for r in (args.ref, args.ref2) if r]
    for r in refs:
        b.ref_text_file(r)
    out_dir = args.out or args.book.with_name(args.book.stem + "_audio")
    out_dir.mkdir(parents=True, exist_ok=True)
    b.guard(out_dir, chunks, refs)
    synthesize(chunks, out_dir, args.book.with_suffix(""), args)
    if not args.limit:
        print("Готово.")


if __name__ == "__main__":
    main()
