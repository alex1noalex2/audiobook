"""Помощники страницы озвучки: python3 -m unittest tests/test_app.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "local"))
import app  # noqa: E402


class App(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(app.safe_name("Два Вавилона.epub"), "Два Вавилона")
        self.assertEqual(app.safe_name("../../etc/passwd.txt"), "passwd")

    def test_progress_line(self):
        m = app.PROGRESS.search("[120/2664] кусок 121/2664, 6.4 с на кусок, осталось ~4.5 ч")
        self.assertEqual((m[1], m[2], m[3]), ("120", "2664", "4.5"))

    def test_colab_cell_keeps_names_in_quotes(self):
        cell = app.colab_cell("Моя книга", "Моя книга.epub", "Саша")
        self.assertIn('"{FOLDER}/Моя книга.epub" --ref "{FOLDER}/Саша.wav"', cell)


if __name__ == "__main__":
    unittest.main()
