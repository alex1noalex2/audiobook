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
    return score


def load_asr(model_name):
    """Возвращает transcribe(audio, sr) -> текст. Whisper через transformers (в Colab он уже есть)."""
    import numpy as np
    import torch
    from transformers import pipeline

    cuda = torch.cuda.is_available()
    asr = pipeline("automatic-speech-recognition", model=model_name, device=0 if cuda else -1,
                   torch_dtype=torch.float16 if cuda else torch.float32)

    def transcribe(audio, sr):
        a = np.asarray(audio, dtype=np.float32)
        if sr != 16000:                                             # Whisper ждёт 16 кГц
            a = np.interp(np.linspace(0, len(a) - 1, int(len(a) * 16000 / sr)), np.arange(len(a)), a).astype(np.float32)
        out = asr({"raw": a, "sampling_rate": 16000}, chunk_length_s=30, generate_kwargs={"language": "russian"})
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
