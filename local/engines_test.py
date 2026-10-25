#!/usr/bin/env python3
"""Сравнение движков озвучки на одном и том же отрывке книги вашим голосом. Для каждого движка — свой mp3 и строка
«сколько секунд на секунду звука» (меньше — быстрее). Сходство с текстом (--check) — подсказка, не замена слуху.

    python3 local/engines_test.py книга.epub --ref voices/Саша.wav --engine chatterbox --out пробы_движков
Движки: chatterbox (MIT, регулятор выразительности --exaggeration), voxcpm2 (Apache-2.0), qwen3 (Apache-2.0).
У них нет знака «+»: ударения можно пробовать знаком над гласной (--accent acute).
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book2audio as b  # noqa: E402
import ru_text  # noqa: E402
import verify  # noqa: E402
from bench import pick_passages  # noqa: E402


def ref_text(ref):
    return b.ref_text_file(ref).read_text(encoding="utf-8").strip()


def engine_chatterbox(args):
    import numpy as np
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    try:
        model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
    except TypeError:                                                  # более ранняя версия пакета
        model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")

    def generate(text):
        wav = model.generate(text, language_id="ru", audio_prompt_path=str(args.ref),
                             exaggeration=args.exaggeration, cfg_weight=args.cfg)
        return np.asarray(wav.squeeze().cpu(), dtype=np.float32), model.sr
    return generate


def engine_voxcpm2(args):
    import numpy as np
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
    text = ref_text(args.ref)

    def generate(t):
        wav = model.generate(text=t, prompt_wav_path=str(args.ref), prompt_text=text, reference_wav_path=str(args.ref),
                             cfg_value=2.0, inference_timesteps=10)
        return np.asarray(wav, dtype=np.float32), model.tts_model.sample_rate
    return generate


def engine_qwen3(args):
    import numpy as np
    import torch
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-Base", device_map="cuda:0",
                                          dtype=torch.float16, attn_implementation="sdpa")        # T4 не умеет bfloat16 быстро
    text = ref_text(args.ref)

    def generate(t):
        wavs, sr = model.generate_voice_clone(text=t, language="Russian", ref_audio=str(args.ref), ref_text=text)
        return np.asarray(wavs[0], dtype=np.float32), sr
    return generate


def engine_tone(args):
    """Для проверки самого скрипта: вместо речи синусоида."""
    import numpy as np

    def generate(t):
        sr = 24000
        return (0.2 * np.sin(2 * np.pi * 150 * np.arange(int(sr * len(t) / 14)) / sr)).astype(np.float32), sr
    return generate


ENGINES = {"chatterbox": engine_chatterbox, "voxcpm2": engine_voxcpm2, "qwen3": engine_qwen3, "tone": engine_tone}


def prepare(text, fixes, accent, accentor):
    t = b.speak(text, fixes)
    if accent == "acute" and re.search(r"[А-Яа-яЁё]", t):
        t = re.sub(r"\+([аеёиоуыэюяАЕЁИОУЫЭЮЯ])", "\\1\u0301", ru_text.plus_stress(accentor(t)))
    return re.sub(r"[,;:]+$", ".", t.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("--ref", required=True, type=Path, help="WAV голоса; рядом .txt с текстом записи")
    ap.add_argument("--engine", required=True, choices=sorted(ENGINES))
    ap.add_argument("--out", type=Path, default=Path("engines"))
    ap.add_argument("--at", type=float, nargs="+", default=[0.3, 0.7])
    ap.add_argument("--words", type=int, default=200)
    ap.add_argument("--max-chars", type=int, default=300)
    ap.add_argument("--accent", choices=["none", "acute"], default="none", help="acute: ударение знаком над гласной (Silero Stress)")
    ap.add_argument("--exaggeration", type=float, default=0.6, help="chatterbox: выразительность 0–1")
    ap.add_argument("--cfg", type=float, default=0.3, help="chatterbox: cfg_weight (меньше — живее и быстрее темп)")
    ap.add_argument("--check", action="store_true", help="сверить озвучку с текстом распознаванием речи (GigaAM)")
    ap.add_argument("--asr-model", default="gigaam-v3-e2e-rnnt")
    ap.add_argument("--fixes", type=Path)
    args = ap.parse_args()
    import numpy as np

    chunks, _ = b.book_chunks(args.book, args.max_chars)
    fixes = b.fixes_for(args.book, args.fixes)
    accentor = None
    if args.accent == "acute":
        from silero_stress import load_accentor
        accentor = load_accentor()
    transcribe = verify.load_asr(args.asr_model) if args.check else None
    generate = ENGINES[args.engine](args)
    args.out.mkdir(parents=True, exist_ok=True)

    for k, (s, e) in enumerate(pick_passages(chunks, args.at, args.words), 1):
        parts, spent, audio_s, scores = [], 0.0, 0.0, []
        for i in range(s, e):
            text = prepare(chunks[i][1], fixes, args.accent, accentor)
            if not re.search(r"[А-Яа-яЁё]", text):
                continue
            t0 = time.time()
            wav, sr = generate(text)
            spent += time.time() - t0
            audio_s += len(wav) / sr
            if transcribe:
                scores.append(verify.similarity(text, transcribe(wav, sr)))
            parts.append(b.tidy(wav, sr))
        name = args.out / f"{args.engine}_{args.accent}_p{k}"
        b.save_wav(name.with_suffix(".wav"), np.concatenate(parts), sr)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(name.with_suffix(".wav")), "-b:a", "96k",
                        str(name.with_suffix(".mp3"))], check=True)
        name.with_suffix(".wav").unlink()
        score = f", сходство с текстом {sum(scores) / len(scores):.2f}" if scores else ""
        print(f"{name.name}.mp3: {audio_s:.0f} с звука, на синтез ушло {spent:.0f} с (x{spent / max(audio_s, 1):.2f}){score}", flush=True)


if __name__ == "__main__":
    main()
