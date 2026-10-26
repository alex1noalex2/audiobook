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
        self.assertEqual(r.normalize("(Откр. 17:5)"), "(Откровение, глава семнадцатая, стих пятый)")
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
        self.assertEqual(b.speak('известна как "Чистая И Непорочная"'), 'известна как "Чистая И Непорочная",')  # после кавычки без знака тоже пауза
        self.assertEqual(b.speak('Он сказал "хорошо."'), 'Он сказал "хорошо."')
        self.assertEqual(r.caps_stress("Мен+я зов+ут +Чистая"), "МенЯ зовУт Чистая")
        self.assertEqual(r.plus_stress("Р+ог и Св+ятой +Он д+евой +ёж"), "Рог и Св+ятой Он д+евой ёж")  # одна гласная и «ё» без плюса
        self.assertEqual(b.speak("Как здесь (Brahm) и (PAUSANIAS, Attica) важно."), "Как здесь и важно.")

    def test_split_long_no_dangling_tail(self):
        sent = ("Когда он пришёл в город, где жили люди, которые поклонялись многим богам, "
                "он сказал им, что есть только один Бог, создавший небо и землю, и всё.")
        parts = b.split_long(sent, 100)
        self.assertTrue(all(25 <= len(p) <= 100 for p in parts))
        self.assertEqual(" ".join(parts), sent)
        self.assertTrue(parts[0].endswith(","))

    def test_question_ends_chunk_and_repeats_dropped(self):
        items = [(b.MAIN, "Он пришёл. Кто ты такой? Я не знаю. Иди прочь.")]
        self.assertEqual([t for _, t in b.chunk(items, 400, end_on_question=True)], ["Он пришёл. Кто ты такой?", "Я не знаю. Иди прочь."])
        self.assertEqual(len(b.chunk(items, 400)), 1)
        block = [(b.MAIN, f"Это достаточно длинное предложение номер {i} для проверки повторов в книге.") for i in range(12)]
        kept, dropped = b.drop_repeats(block + [(b.MAIN, "Другой абзац, который идёт между копиями раздела.")] + block)
        self.assertEqual((len(kept), dropped), (13, 12))
        kept, dropped = b.drop_repeats(block[:3] + block[:3])                   # короткий повтор остаётся
        self.assertEqual(dropped, 0)

    def test_bible_reference_reads_as_separate_phrase(self):
        self.assertEqual(b.speak("Как сказано (Откр. 17:5), Вавилон."),
                         "Как сказано (Откровение, глава семнадцатая, стих пятый), Вавилон.")
        self.assertIn("Третья книга Царств, глава одиннадцатая, стих седьмой", b.speak("(3 Царств 11:7)"))
        self.assertIn("стихи с восьмого по десятый", b.speak("Быт. 10:8-10."))
        self.assertEqual(b.speak("Было в 12:30 утра."), "Было в двенадцать тридцать утра.")

    def test_tidy_keeps_quiet_ending(self):
        import numpy as np
        sr = 24000
        a = np.concatenate([np.zeros(sr // 2), 0.3 * np.ones(sr), 0.006 * np.ones(int(0.04 * sr)), np.zeros(sr)]).astype(np.float32)
        out = b.tidy(a, sr)
        tail_kept = (np.abs(out) > 0.004).sum() / sr
        self.assertGreater(tail_kept, 1.03)                                  # тихие 40 мс после речи остались

    def test_join_soft_hyphens_and_drop_rules(self):
        text = "Книга, которую вы держите в руках, помогает; вы дер-жите книгу, а кто-то и из-за этого читает."
        items, n = b.join_soft_hyphens([(b.MAIN, text)], min_count=1)
        if n:                                                                 # при pymorphy3 и без него склеиваются только разрывы слов
            self.assertIn("вы держите книгу", items[0][1])
            self.assertIn("кто-то", items[0][1])
            self.assertIn("из-за", items[0][1])
        self.assertEqual(b.join_soft_hyphens([(b.MAIN, text)])[1], 0)       # разрывов меньше порога: книга не меняется
        chunks = [(b.SIDE, "Оглавление."), (b.MAIN, "Все права защищены. Издание 2022."), (b.MAIN, "Текст книги.")]
        kept, dropped = b.drop_matching(chunks, ["Все права защищены", "=Оглавление."])
        self.assertEqual((kept, dropped), ([(b.MAIN, "Текст книги.")], 2))
        self.assertEqual(b.drop_matching(chunks, ["=Все права"])[1], 0)       # «=» — кусок целиком, не часть

    def test_latin_fixes_apply_before_latin_is_dropped(self):
        fx = [("Zoom", "Зум"), ("Цсб", "Цэ-Эс-Бэ")]
        self.assertEqual(b.speak("Мы провели Zoom в ЦСБ, Сдвиг № 2.", fx), "Мы провели Зум в Цэ-Эс-Бэ, Сдвиг номер два.")
        self.assertEqual(b.speak("Мы провели Zoom.", []), "Мы провели,")                  # без поправки латиница выбрасывается

    def test_join_rebuilds_stale_part(self):
        import os
        import tempfile
        import time
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "audio"
            out.mkdir()
            for i in range(2):
                b.save_wav(out / f"{i:05d}.wav", (0.3 * np.sin(np.arange(24000) / 20)).astype(np.float32), 24000)
            base = Path(d) / "kniga"
            self.assertEqual(b.join(out, base, 2, 2), [0])
            self.assertEqual(b.join(out, base, 2, 2), [])                       # свежая часть не пересобирается
            old = time.time() - 3600
            os.utime(base.with_name("kniga_часть01.mp3"), (old, old))            # часть от прошлой озвучки: старее кусков
            self.assertEqual(b.join(out, base, 2, 2), [0])

    def test_speakers_switch_at_author_marks(self):
        items = [(b.MAIN, "Вступление."), (b.SIDE, "Лия"), (b.MAIN, "Я услышала."), (b.SIDE, "ГЛАВА 2"), (b.MAIN, "Мы поехали."),
                 (b.SIDE, "Хао"), (b.MAIN, "Я решил.")]
        rules = {"Лия": b.LIA, "Хао": b.MAIN}
        out = [r for r, _ in b.assign_speakers(items, rules)]
        self.assertEqual(out, [b.MAIN, b.SIDE, b.LIA, b.SIDE, b.LIA, b.SIDE, b.MAIN])      # заголовки и метки — диктор, главу не сбрасывает
        self.assertEqual(b.assign_speakers(items, {}), items)                               # без правил книга не меняется
        chunks = b.chunk([(b.LIA, "Кто здесь? Я иду.")], 400, end_on_question=True)
        self.assertEqual([t for _, t in chunks], ["Кто здесь?", "Я иду."])                  # вопрос заканчивает кусок и у второго голоса


if __name__ == "__main__":
    unittest.main()

