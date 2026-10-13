import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "local"))
import verify  # noqa: E402


class Similarity(unittest.TestCase):
    def test_same_and_noise(self):
        t = 'Мать первого Бахуса была известна под именем Прозерпина (от которой богиня отличалась).'
        self.assertEqual(verify.similarity(t, "мать первого бахуса была известна под именем прозерпина от которой богиня отличалась"), 1.0)
        self.assertLess(verify.similarity(t, "мать первого бахуса была известна под именем брагерпре ль которой вавилонская"), 0.8)

    def test_similar_name_counts_and_repeat_hurts(self):
        self.assertGreater(verify.similarity("Он сказал Паусания и ушёл", "он сказал Павсания и ушел"), 0.95)   # имя не в конце слова: не штрафуем
        self.assertLess(verify.similarity("он сказал хорошо", "он сказал сказал сказал сказал хорошо хорошо"), 0.7)

    def test_eaten_last_letters_are_penalised(self):
        full = "с нимродом так сурово расправились"
        self.assertGreater(verify.similarity("С Нимродом так сурово расправились.", full), 0.99)
        self.assertLess(verify.similarity("С Нимродом так сурово расправились.", "с нимродом так сурово расправили"), 0.9)

    def test_yo_and_plus_ignored(self):
        self.assertEqual(verify.similarity("почётной жен+ой", "почетной женой"), 1.0)


class BestOf(unittest.TestCase):
    def test_regenerates_only_bad_chunks_and_keeps_best(self):
        calls = []

        def generate(texts, vps, steps, speed):
            calls.append(list(texts))
            return [(t + ("!" if len(calls) > 1 else ""), 24000) for t in texts]   # "аудио" — это просто строка

        heard = {"плохо": ["мусор", "плохо"], "хорошо": ["хорошо"]}

        def transcribe(audio, sr):
            return audio.rstrip("!") if audio.endswith("!") or audio == "хорошо" else "мусор"

        seeds = []
        results, info = verify.best_of(generate, ["плохо", "хорошо"], [None, None], 16, None, transcribe, 3, 0.9, seeds.append)
        self.assertEqual(calls, [["плохо", "хорошо"], ["плохо"]])        # во второй раз только плохой кусок
        self.assertEqual(seeds, [1])
        self.assertEqual(results[0][0], "плохо!")
        self.assertEqual(info, [(1.0, 2), (1.0, 1)])


class PitchRise(unittest.TestCase):
    def test_question_rises_statement_falls(self):
        import numpy as np
        sr = 24000

        def tone(f0, f1, sec):
            f = np.linspace(f0, f1, int(sr * sec))
            return (0.3 * np.sin(2 * np.pi * np.cumsum(f) / sr)).astype(np.float32)

        question = np.concatenate([tone(120, 120, 1.5), tone(120, 170, 0.4)])
        statement = np.concatenate([tone(130, 130, 1.5), tone(130, 95, 0.4)])
        self.assertGreater(verify.pitch_rise(question, sr), 3)
        self.assertLess(verify.pitch_rise(statement, sr), 1)
        self.assertEqual(verify.pitch_rise(np.zeros(sr, np.float32), sr), 0.0)


if __name__ == "__main__":
    unittest.main()
