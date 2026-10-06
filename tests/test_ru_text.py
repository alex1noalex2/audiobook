"""Проверки подготовки русского текста для озвучки: python3 -m unittest tests/test_ru_text.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "local"))
import book2audio as b  # noqa: E402
import ru_text as r  # noqa: E402


class RuText(unittest.TestCase):
    def test_roman_by_noun_and_name(self):
        self.assertEqual(r.normalize("Часть II. Раздел I. Ребенок"), "Часть вторая. Раздел первый. Ребенок")
        self.assertEqual(r.normalize("в Главе III, Части I"), "в Главе третьей, Части первой")
        self.assertEqual(r.normalize("Папа Лев XII; Папы Григория I"), "Папа Лев двенадцатый; Папы Григория первого")

    def test_years_and_durations(self):
        self.assertEqual(r.normalize("в 1853 году"), "в тысяча восемьсот пятьдесят третьем году")
        self.assertEqual(r.normalize("до 1846 г. до н. э."), "до тысяча восемьсот сорок шестого года до нашей эры")
        self.assertEqual(r.normalize("жил 502 года"), "жил пятьсот два года")  # срок, а не календарный год

    def test_verse_references(self):
        self.assertEqual(r.normalize("(Откр. 17:5)"), "(Откровение глава семнадцать, стих пять)")
        self.assertIn("стихи с двадцать шестого по двадцать восьмой", r.normalize("Иов 31:26-28"))
        self.assertTrue(r.normalize("1 Кор. 5:3").startswith("Первое Коринфянам"))

    def test_dates_abbreviations_slash(self):
        self.assertEqual(r.normalize("25 декабря"), "двадцать пятого декабря")
        self.assertEqual(r.normalize("т. е. и т. д."), "то есть и так далее")
        self.assertEqual(r.normalize("Нин/Нинус"), "Нин или Нинус")
        self.assertEqual(r.normalize("Рис. 11"), "Рисунок одиннадцать")

    def test_latin(self):
        self.assertEqual(r.normalize("Pontifex Maximus и Mars"), "Понтифекс Максимус и Марс")
        self.assertEqual(r.normalize("Конец. OVID Fasti."), "Конец. Фасти.")
        self.assertEqual(r.normalize("Box 1482, Jerusalem, Israel 91014"), "")  # читать нечего -> тишина

    def test_speak_borders_and_names(self):
        self.assertEqual(b.speak(', душа всякого существа, непостижимый'), "душа всякого существа, непостижимый,")
        self.assertEqual(b.speak("Он сказал:..."), "Он сказал:.")
        self.assertEqual(b.speak("ЙАУХУ пришёл", [("Йауху", "Иауэ")]), "Иауэ пришёл,")  # запятая: кусок без конечного знака
        self.assertEqual(b.speak("Как здесь (Brahm) и (PAUSANIAS, Attica) важно."), "Как здесь и важно.")


if __name__ == "__main__":
    unittest.main()
