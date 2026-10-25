"""Наведение порядка в папке Audiobook: python3 -m unittest tests/test_organize.py"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "local"))
import organize_drive as o  # noqa: E402


def touch(root, *names):
    for n in names:
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")


class Organize(unittest.TestCase):
    def tree(self, d):
        root = Path(d)
        touch(root, "babylon.epub", "generations.epub", "generations.drop.txt", "fixes.txt", "babylon_часть01.mp3",
              "babylon.mp3", "Dva_Vavilona.mp3", "timecodes.txt", "voice_05.wav", "voice_05.txt", "my_voice.mp3",
              "babylon_f5_book/00000.wav", "babylon_audio/00000.wav", "babylon_f5/questions_test.mp3",
              "bench/p1.mp3", "bench_B2/p1.mp3", "my_refs/ref_01.wav", "my_refs/ref_01.txt", "my_refs/ref_05.wav", "заметки.docx")
        return root

    def test_plan_then_apply(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.tree(d)
            plan = {str(s.relative_to(root)): str(t.relative_to(root)) for s, t, _ in o.plan(root, fixes_for="babylon")}
            self.assertEqual(plan["babylon.epub"], "books/babylon/babylon.epub")
            self.assertEqual(plan["generations.drop.txt"], "books/generations/generations.drop.txt")
            self.assertEqual(plan["babylon_f5_book"], "books/babylon/audio")
            self.assertEqual(plan["babylon_audio"], "_удалить/babylon_audio")        # старая озвучка другой моделью
            self.assertEqual(plan["babylon_часть01.mp3"], "books/babylon/babylon_часть01.mp3")
            self.assertEqual(plan["fixes.txt"], "books/babylon/babylon.fixes.txt")
            self.assertEqual(plan["bench_B2"], "_удалить/bench_B2")
            self.assertEqual(plan["Dva_Vavilona.mp3"], "_удалить/Dva_Vavilona.mp3")
            self.assertNotIn("заметки.docx", plan)                                    # незнакомое не трогаем
            self.assertTrue((root / "bench").exists())                               # план ничего не меняет
            o.apply(o.plan(root, fixes_for="babylon"))
            self.assertTrue((root / "books/babylon/audio/00000.wav").exists())
            self.assertTrue((root / "voices/Саша.wav").exists() and (root / "voices/образцы/ref_05.wav").exists())
            self.assertFalse((root / "bench").exists())
            self.assertTrue((root / "заметки.docx").exists())
            self.assertEqual(o.plan(root), [])                                        # повторно: делать нечего


if __name__ == "__main__":
    unittest.main()
