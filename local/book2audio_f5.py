#!/usr/bin/env python3
"""Книга -> MP3 голосом F5-TTS Russian (Misha24-10, CC-BY-NC-4.0, только некоммерческое использование) на видеокарте
(Colab, Kaggle). Вариант, выбранный на пробах: ударения «+» (Silero Stress) в тексте и в записи образца, 32 шага,
скорость 1.0, примечания и заголовки тем же голосом с эффектом телефона. Вопрос заканчивает кусок, и тон его
последних 0.5 с поднимается на --q-boost полутонов (модель сама вопрос не интонирует). Проверка речью — GigaAM.

    python3 local/book2audio_f5.py книга.epub --ref my_refs/ref_01.wav
    python3 local/book2audio_f5.py книга.epub --ref ... --questions 8     # проба: только вопросы
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book2audio as b  # noqa: E402
import bench  # noqa: E402
import intonation  # noqa: E402
import ru_text  # noqa: E402
import verify  # noqa: E402


def finalize(chunks, base, out_dir, part, threshold=0.9):
    """Склеивает части в <книга>.mp3, пишет <книга>_таймкоды.txt и <книга>_проверить.txt (куски с худшей проверкой речи, по времени)."""
    full = b.concat_parts(base)
    if not full:
        return
    import timecodes
    lines, total, starts = timecodes.timecode_lines(chunks, base, out_dir, part)
    base.with_name(f"{base.name}_таймкоды.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Итоговый файл: {full} ({timecodes.stamp(total)}), таймкоды: {len(lines)} заголовков")
    report_file = out_dir / "report.json"
    if report_file.exists():
        report = json.loads(report_file.read_text())
        weak = sorted((v["score"], int(i)) for i, v in report.items() if v["score"] < threshold and int(i) in starts)
        rows = [f"{timecodes.stamp(starts[i])}  {sc:.2f}  {chunks[i][1][:140]}" for sc, i in weak[:100]]
        base.with_name(f"{base.name}_проверить.txt").write_text(
            f"Куски с худшей проверкой речи ({len(weak)} ниже {threshold}); показаны 100 худших: время, оценка, начало текста\n"
            + "\n".join(rows) + "\n", encoding="utf-8")
        print(f"Список для прослушивания: {base.name}_проверить.txt ({len(weak)} кусков ниже порога)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("--ref", required=True, help="WAV основного голоса; рядом .txt с текстом записи")
    ap.add_argument("--out", type=Path, help="папка для кусков (по умолчанию <книга>_audio рядом с книгой)")
    ap.add_argument("--max-chars", type=int, default=400)
    ap.add_argument("--steps", type=int, default=32)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--phone", type=float, default=0.4, help="сила эффекта телефона у примечаний и заголовков (0 — выключить)")
    ap.add_argument("--part", type=int, default=100, help="кусков в одном MP3")
    ap.add_argument("--tries", type=int, default=2, help="сколько раз озвучивать кусок с плохой проверкой речью")
    ap.add_argument("--threshold", type=float, default=0.9, help="сходство с текстом, ниже которого кусок озвучивается заново")
    ap.add_argument("--q-boost", type=float, default=4.0, help="на сколько полутонов поднять тон в конце вопроса (0 — не поднимать)")
    ap.add_argument("--asr-model", default="gigaam-v3-e2e-rnnt")
    ap.add_argument("--f5-repo", default="Misha24-10/F5-TTS_RUSSIAN")
    ap.add_argument("--f5-model", default="F5TTS_v1_Base_v2/model_last_inference.safetensors")
    ap.add_argument("--f5-vocab", default="F5TTS_v1_Base/vocab.txt")
    ap.add_argument("--fixes", type=Path, help="файл поправок (по умолчанию fixes.txt рядом с книгой)")
    ap.add_argument("--limit", type=int, help="озвучить только N кусков (без склейки в MP3)")
    ap.add_argument("--questions", type=int, help="проба: озвучить N вопросов, склеить в questions_test.mp3")
    ap.add_argument("--redo-weak", action="store_true",
                    help="переозвучить куски с плохой проверкой речи и куски со ссылками на стихи (хвост текста спасает последнее слово, до --tries попыток)")
    ap.add_argument("--assemble", action="store_true",
                    help="ничего не озвучивать: заново собрать все части MP3 из готовых кусков, склеить книгу и посчитать таймкоды (видеокарта не нужна)")
    args = ap.parse_args()
    if args.redo_weak:
        args.tries = max(args.tries, 4)
    import numpy as np

    chunks, dropped = b.book_chunks(args.book, args.max_chars)
    if not chunks:
        sys.exit("В файле нет текста (возможно, это скан)")
    print(f"Книга: {sum(len(t) for _, t in chunks)} символов, {len(chunks)} кусков"
          + (f" (убрана повторная копия раздела: {dropped} кусков)" if dropped else ""))
    refs = [args.ref]
    b.ref_text_file(args.ref)
    out_dir = args.out or args.book.with_name(args.book.stem + "_audio")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.questions:                                                # проба вопросов ничего не оставляет, кроме mp3
        b.guard(out_dir, chunks, refs)
    base = args.book.with_suffix("")
    if args.assemble:
        missing = [i for i in range(len(chunks)) if not (out_dir / f"{i:05d}.wav").exists()]
        if missing:
            sys.exit(f"Не хватает {len(missing)} кусков (первый: {missing[0]:05d}.wav): сначала допишите озвучку без --assemble")
        b.join(out_dir, base, len(chunks), args.part, force=range((len(chunks) + args.part - 1) // args.part))
        return finalize(chunks, base, out_dir, args.part, args.threshold)

    try:
        from silero_stress import load_accentor
    except ImportError:
        sys.exit("Нужен Silero Stress: pip install silero-stress")
    accentor = load_accentor()
    fixes = b.fixes_for(args.book, args.fixes)
    texts = []
    for _, t in chunks:
        s = b.speak(t, fixes)
        texts.append(ru_text.plus_stress(accentor(s)) if re.search(r"[А-Яа-яЁё]", s) else s)
    is_q = [r == b.MAIN and t.rstrip().endswith("?") for r, t in chunks]

    voice, generate, reseed = bench.engine_f5(SimpleNamespace(f5_repo=args.f5_repo, f5_model=args.f5_model,
                                                              f5_vocab=args.f5_vocab), accentor)
    main_vp = voice(args.ref, "plus")
    transcribe = verify.load_asr(args.asr_model) if args.tries > 1 else None
    bench.RUN["seed"], bench.RUN["tail"] = None, args.redo_weak

    def voice_chunk(i):
        """Озвучивает кусок; при плохой проверке речи (сходство ниже порога) повторяет с другим seed, берёт лучшее."""
        best = None
        for n in range(args.tries):
            reseed(n)
            audio, sr = generate([texts[i]], [main_vp], args.steps, args.speed)[0]
            score = verify.similarity(texts[i], transcribe(audio, sr)) if transcribe else 1.0
            if best is None or score > best[0]:
                best = (score, audio, sr, n + 1)
            if score >= args.threshold:
                break
        score, audio, sr, used = best
        if is_q[i] and args.q_boost:
            audio = intonation.raise_ending(audio, sr, args.q_boost)
        if chunks[i][0] == b.SIDE and args.phone:
            audio = b.phone_effect(audio, sr, args.phone)
        return audio, sr, {"score": round(score, 2), "tries": used}

    report_file = out_dir / "report.json"
    report = json.loads(report_file.read_text()) if report_file.exists() else {}

    if args.questions:
        ask = [i for i in range(len(chunks)) if is_q[i] and 40 <= len(chunks[i][1]) <= 300]
        picked = [ask[j * len(ask) // args.questions] for j in range(args.questions)]
        parts = []
        for i in picked:
            audio, sr, info = voice_chunk(i)
            parts += [b.tidy(audio, sr), np.zeros(sr, np.float32)]
            print(f"кусок {i}: попыток {info['tries']}, сходство {info['score']}  ...{chunks[i][1][-70:]}", flush=True)
        b.save_wav(out_dir / "questions_test.wav", np.concatenate(parts), sr)
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_dir / "questions_test.wav"), "-b:a", "96k",
                        str(out_dir / "questions_test.mp3")], check=True)
        (out_dir / "questions_test.wav").unlink()
        print(f"Готово: {out_dir / 'questions_test.mp3'} (порядок как в списке выше)")
        return

    if args.redo_weak:
        redo_file = out_dir / "redo.json"
        if redo_file.exists():
            redo = set(json.loads(redo_file.read_text()))
        else:
            weak = {int(i) for i, v in report.items() if v["score"] < args.threshold}
            verses = {i for i, (_, t) in enumerate(chunks) if re.search(r"\d\s*:\s*\d", t)}   # ссылки на стихи прочитаются иначе
            redo = weak | verses
            redo_file.write_text(json.dumps(sorted(redo)))
        pending = [i for i in sorted(redo) if not report.get(str(i), {}).get("redo")]
        for i in pending:
            (out_dir / f"{i:05d}.wav").unlink(missing_ok=True)
        print(f"Переозвучить кусков: {len(pending)} из {len(redo)} (остальные уже сделаны)", flush=True)
    todo = [i for i in range(len(chunks)) if not (out_dir / f"{i:05d}.wav").exists()]
    if args.limit:
        todo = todo[:args.limit]
    started = time.time()
    for n, i in enumerate(todo, 1):
        if not re.search(r"[А-Яа-яЁё]", texts[i]):                       # нечего читать (адрес, ссылка): тишина
            b.save_wav(out_dir / f"{i:05d}.wav", np.zeros(int(0.3 * 24000), np.float32), 24000)
            continue
        audio, sr, info = voice_chunk(i)
        b.save_wav(out_dir / f"{i:05d}.wav", audio, sr)
        report[str(i)] = info | ({"redo": True} if args.redo_weak else {})
        if n % 10 == 0 or n == len(todo):
            report_file.write_text(json.dumps(report))
            per = (time.time() - started) / n
            print(f"[{n}/{len(todo)}] кусок {i + 1}/{len(chunks)}, {per:.1f} с на кусок, "
                  f"осталось ~{per * (len(todo) - n) / 3600:.1f} ч", flush=True)
            if not args.limit:
                b.join(out_dir, base, len(chunks), args.part)
    if not args.limit:
        report_file.write_text(json.dumps(report))
        b.join(out_dir, base, len(chunks), args.part,
               force=range((len(chunks) + args.part - 1) // args.part) if args.redo_weak else ())
        (out_dir / "redo.json").unlink(missing_ok=True)
        weak = [i for i, v in report.items() if v["score"] < args.threshold]
        finalize(chunks, base, out_dir, args.part, args.threshold)
        print(f"Кусков, где проверка речи не дошла до порога: {len(weak)} (см. report.json).")


if __name__ == "__main__":
    main()
