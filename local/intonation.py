"""Интонация вопроса: тон в конце куска поднимается плавно, остальная речь не меняется (Praat PSOLA, pip install praat-parselmouth)."""
import numpy as np


def raise_ending(a, sr, semitones, tail_s=0.5, floor=70, ceil=300):
    """Поднимает тон последних tail_s секунд озвученной речи: подъём нарастает от 0 до semitones. Паузы не трогает."""
    import parselmouth
    from parselmouth.praat import call

    a = np.asarray(a, dtype=np.float64)
    loud = np.flatnonzero(np.abs(a) > 0.03 * (np.abs(a).max() or 1.0))
    if semitones <= 0 or not len(loud):
        return a.astype(np.float32)
    end = loud[-1] / sr                                                  # конец речи (хвост тишины не считаем)
    snd = parselmouth.Sound(a, sampling_frequency=sr)
    manip = call(snd, "To Manipulation", 0.01, floor, ceil)
    tier = call(manip, "Extract pitch tier")
    start = max(end - tail_s, 0.0)
    points = []
    for k in range(1, call(tier, "Get number of points") + 1):
        t = call(tier, "Get time from index", k)
        if t > start:
            points.append((t, call(tier, "Get value at index", k)))
    if len(points) < 3:
        return a.astype(np.float32)
    start, last = points[0][0], points[-1][0]                           # подъём считаем по озвонченным точкам, а не по концу звука
    call(tier, "Remove points between", start, last + 0.01)
    for t, f in points:
        ramp = (t - start) / (last - start)
        call(tier, "Add point", t, f * 2 ** (semitones * ramp ** 1.5 / 12))   # плавно: к концу круче
    call([tier, manip], "Replace pitch tier")
    out = call(manip, "Get resynthesis (overlap-add)").values[0]
    return np.pad(out, (0, max(len(a) - len(out), 0)))[:len(a)].astype(np.float32)
