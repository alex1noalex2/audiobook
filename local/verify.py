"""Проверка озвучки распознаванием речи: кусок прослушивается Whisper, результат сверяется с текстом,
плохо прочитанные куски (повторы, пропуски, «брагерпре») озвучиваются заново с другим случайным числом.
Ударения проверка не ловит: чётко произнесённое слово с неверным ударением она засчитает как верное."""
import difflib
import re


def words(text):
    return re.findall(r"[а-яa-z0-9]+", text.lower().replace("ё", "е").replace("+", ""))


def similarity(expected, heard):
    """Доля совпавших слов 0–1. Похожие слова (имена, на которых Whisper ошибается) считаются совпавшими,
    но съеденный конец последнего слова («расправилис» вместо «расправились») снижает оценку на 0.15."""
    want, got_raw = words(expected), words(heard)
    if not want:
        return 1.0
    known = set(want)
    got = [(difflib.get_close_matches(w, known, n=1, cutoff=0.75) or [w])[0] for w in got_raw]
    score = difflib.SequenceMatcher(None, want, got, autojunk=False).ratio()
    last = want[-1]
    if len(last) >= 4 and (not got_raw or difflib.SequenceMatcher(None, last, got_raw[-1]).ratio() < 0.97):
        score -= 0.15
    return max(score, 0.0)


def load_asr(model_name):
    """Возвращает transcribe(audio, sr) -> текст.
    «gigaam-v3-e2e-rnnt» (и другие gigaam-…): русский GigaAM через onnx-asr (pip install onnx-asr[hub]), на процессоре,
    у автора обзора на Хабре WER 3.3% против 7.9% у Whisper turbo; иначе Whisper через transformers."""
    import numpy as np

    def to16k(audio, sr):
        a = np.asarray(audio, dtype=np.float32)
        if sr != 16000:                                             # модели ждут 16 кГц
            a = np.interp(np.linspace(0, len(a) - 1, int(len(a) * 16000 / sr)), np.arange(len(a)), a).astype(np.float32)
        return a

    if model_name.startswith("gigaam"):
        import onnx_asr
        model = onnx_asr.load_model(model_name)

        def transcribe(audio, sr):
            a = to16k(audio, sr)                                    # строго float32, иначе пустой ответ
            step = 24 * 16000                                       # GigaAM принимает до 25 с
            return " ".join(model.recognize(a[i:i + step], sample_rate=16000) for i in range(0, len(a), step))

        return transcribe

    import torch
    from transformers import pipeline

    cuda = torch.cuda.is_available()
    asr = pipeline("automatic-speech-recognition", model=model_name, device=0 if cuda else -1,
                   torch_dtype=torch.float16 if cuda else torch.float32)

    def transcribe(audio, sr):
        out = asr({"raw": to16k(audio, sr), "sampling_rate": 16000}, chunk_length_s=30, generate_kwargs={"language": "russian"})
        return out["text"]

    return transcribe


def best_of(generate, texts, vps, steps, speed, transcribe, tries, threshold, reseed):
    """Озвучивает куски и перезапускает те, у которых сходство с текстом ниже threshold, до tries попыток.
    Возвращает (результаты [(audio, sr)], сведения [(сходство, попыток)])."""
    results = generate(texts, vps, steps, speed)
    scores = [similarity(t, transcribe(*r)) for t, r in zip(texts, results)]
    used = [1] * len(texts)
    for attempt in range(1, tries):
        bad = [i for i, s in enumerate(scores) if s < threshold]
        if not bad:
            break
        reseed(attempt)
        new = generate([texts[i] for i in bad], [vps[i] for i in bad], steps, speed)
        for i, r in zip(bad, new):
            used[i] += 1
            score = similarity(texts[i], transcribe(*r))
            if score > scores[i]:
                results[i], scores[i] = r, score
    return results, list(zip(scores, used))


def pitch_rise(audio, sr, tail_s=0.4, before_s=1.0):
    """Подъём тона к концу куска в полутонах: у вопроса высота в конце выше, чем в речи перед ним, у
    повествования падает. Тон по автокорреляции кадров 40 мс (мужской голос 70–300 Гц). 0 — тон не найден."""
    import numpy as np
    a = np.asarray(audio, dtype=np.float32)
    win, hop = int(sr * 0.04), int(sr * 0.01)
    lo, hi = int(sr / 300), int(sr / 70)
    peak = float(np.abs(a).max()) or 1.0
    f0 = []
    for k in range(0, len(a) - win, hop):
        x = a[k:k + win] - a[k:k + win].mean()
        if np.sqrt((x ** 2).mean()) < 0.03 * peak:
            f0.append(np.nan)
            continue
        ac = np.fft.irfft(np.abs(np.fft.rfft(x, 2 * win)) ** 2)[:hi + 1]
        lag = lo + int(np.argmax(ac[lo:hi + 1]))
        f0.append(sr / lag if ac[lag] > 0.5 * ac[0] else np.nan)
    f0 = np.array(f0)
    voiced = np.flatnonzero(~np.isnan(f0))
    if len(voiced) < 20:
        return 0.0
    end = voiced[-1]
    tail = f0[max(end - int(tail_s * 100), 0):end + 1]
    before = f0[max(end - int((tail_s + before_s) * 100), 0):max(end - int(tail_s * 100), 0)]
    tail, before = tail[~np.isnan(tail)], before[~np.isnan(before)]
    if len(tail) < 5 or len(before) < 10:
        return 0.0
    return float(12 * np.log2(np.percentile(tail, 90) / np.median(before)))
