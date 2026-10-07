"""Русский текст для озвучки: сокращения, римские и арабские числа, ссылки на стихи, латиница.

Модель читает цифры и латиницу как попало, поэтому до отправки в неё всё превращается в слова.
Требуется num2words (pip install num2words); без него числа остаются цифрами.
"""
import re

try:
    from num2words import num2words
except ImportError:
    num2words = None

CYR = r"[А-Яа-яЁё]"

# ---------- сокращения ----------
ABBR = [
    (r"\bт\.\s?е\.", "то есть"),
    (r"\bи т\.\s?д\.", "и так далее"),
    (r"\bи т\.\s?п\.", "и тому подобное"),
    (r"\bт\.\s?к\.", "так как"),
    (r"\bн\.\s?э\.", "нашей эры"),
    (r"\bприм\.\s*", "примечание "),
    (r"\bСм\.\s", "Смотри "),
    (r"\bсм\.\s", "смотри "),
    (r"\bстр\.\s*(?=\d)", "страница "),
    (r"\bгл\.\s*(?=\d)", "глава "),
    (r"\bРис\.\s*", "Рисунок "),
    (r"\bрис\.\s*", "рисунок "),
]
BIBLE = {  # сокращения названий книг в ссылках на стихи
    "Откр.": "Откровение", "Кор.": "Коринфянам", "Рим.": "Римлянам", "Тим.": "Тимофею", "Ис.": "Исаия",
    "Фесс.": "Фессалоникийцам", "Гал.": "Галатам", "Матф.": "Матфея", "Мф.": "Матфея", "Ин.": "Иоанна",
    "Быт.": "Бытие", "Исх.": "Исход", "Иер.": "Иеремия", "Дан.": "Даниила", "Пс.": "Псалом",
}

# ---------- числительные ----------
_HARD = {("n", "nom"): "ое", ("m", "gen"): "ого", ("m", "dat"): "ому", ("m", "prep"): "ом", ("m", "ins"): "ым",
         ("f", "nom"): "ая", ("f", "acc"): "ую", ("f", "gen"): "ой", ("f", "dat"): "ой", ("f", "prep"): "ой", ("f", "ins"): "ой"}
_SOFT = {("n", "nom"): "ье", ("m", "gen"): "ьего", ("m", "dat"): "ьему", ("m", "prep"): "ьем", ("m", "ins"): "ьим",
         ("f", "nom"): "ья", ("f", "acc"): "ью", ("f", "gen"): "ьей", ("f", "dat"): "ьей", ("f", "prep"): "ьей", ("f", "ins"): "ьей"}


def cardinal(n):
    return num2words(int(n), lang="ru") if num2words else str(n)


def ordinal(n, gender="m", case="nom"):
    """Порядковое числительное: ordinal(1853, 'm', 'prep') -> «тысяча восемьсот пятьдесят третьем»."""
    if not num2words:
        return str(n)
    phrase = num2words(int(n), lang="ru", to="ordinal")
    head, _, last = phrase.rpartition(" ")
    table = _SOFT if last.endswith("ий") else _HARD
    ending = table.get((gender, case))
    if ending is not None:
        last = last[:-2] + ending
    return f"{head} {last}".strip()


def roman(s):
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total = 0
    for ch, nxt in zip(s, s[1:] + " "):
        v = values[ch]
        total += -v if values.get(nxt, 0) > v else v
    return total


_FEM = {"глава": "nom", "главу": "acc", "главы": "gen", "главе": "prep", "главой": "ins",
        "часть": "nom", "части": "gen", "частью": "ins", "книга": "nom", "книгу": "acc", "книги": "gen", "книге": "prep"}
_MASC = {"раздел": "nom", "раздела": "gen", "разделу": "dat", "разделе": "prep", "разделом": "ins",
         "том": "nom", "тома": "gen", "томе": "prep", "пункт": "nom", "пункта": "gen", "пункте": "prep"}


def _structure_number(m, to_words):
    """«Глава II», «Часть 3», «в Главе III»: род и падеж по слову перед числом."""
    word, num = m.group(1), m.group(2)
    n = roman(num) if to_words == "roman" else int(num)
    key = word.lower()
    if key in _FEM:
        return f"{word} {ordinal(n, 'f', _FEM[key])}"
    return f"{word} {ordinal(n, 'm', _MASC[key])}"


def _name_number(m):
    """«Лев XII», «Григория I»: мужской род, падеж по окончанию имени."""
    name, num = m.group(1), m.group(2)
    low = name.lower()
    case = ("gen" if low.endswith(("а", "я")) else "dat" if low.endswith(("у", "ю")) else
            "ins" if low.endswith(("ом", "ем")) else "prep" if low.endswith("е") else "nom")
    return f"{name} {ordinal(roman(num), 'm', case)}"


# ---------- латиница ----------
LATIN = {  # латинские термины книги: как их читать по-русски; остальная латиница вырезается
    "gradivus": "градивус", "pontifex": "понтифекс", "maximus": "максимус", "fasti": "фасти",
    "purpureus": "пурпуреус", "purpura": "пурпура", "domina": "домина", "mars": "марс", "quirinus": "квиринус",
    "deus": "деус", "dea": "деа", "divus": "дивус", "mater": "матер", "venus": "венус", "idaia": "идая",
    "matuta": "матута", "lateinos": "латейнос", "taurus": "таурус", "turannus": "турраннус",
    "pontificale": "понтификале", "romanum": "романум", "pantheon": "пантеон", "principium": "принципиум",
    "miserere": "мизерере",
}
_DROP = "\x00"


def _latin(t):
    def repl(m):
        w = m.group(0).rstrip(".")
        dot = "." if m.group(0).endswith(".") else ""
        low = w.lower()
        if low in LATIN:
            r = LATIN[low]
            return (r.capitalize() if w[0].isupper() else r) + dot
        return _DROP
    t = re.sub(r"\b[A-Za-z][A-Za-z'’\-]*\.?", repl, t)
    t = re.sub(rf"[\"«„“]\s*{_DROP}[\s{_DROP},.;:]*[\"»”“]", "", t)       # пустые кавычки после вырезания
    t = re.sub(rf"\(\s*{_DROP}[\s{_DROP},.;:]*\)", "", t)                 # пустые скобки
    t = re.sub(rf"(?:\s*{_DROP})+[,.;:]*", " ", t)
    return t


# ---------- главная функция ----------
def normalize(t):
    for pattern, repl in ABBR:
        t = re.sub(pattern, repl, t)
    for short, full in BIBLE.items():
        t = re.sub(rf"(?<!\w){re.escape(short)}", full, t)
    t = re.sub(r"(?<!\w)([1-3])\s+(?=(?:Коринфянам|Фессалоникийцам|Тимофею|Иоанна|Петра))",
               lambda m: ordinal(int(m.group(1)), "n", "nom").capitalize() + " ", t)  # 1 Кор. -> Первое Коринфянам

    nouns = "|".join(["Глава", "Главу", "Главы", "Главе", "Главой", "Часть", "Части", "Частью", "Книга", "Книгу", "Книги",
                      "Книге", "Раздел", "Раздела", "Разделу", "Разделе", "Разделом", "Том", "Тома", "Томе", "Пункт",
                      "Пункта", "Пункте"])
    t = re.sub(rf"\b((?i:{nouns}))\s+([IVXL]+)\b", lambda m: _structure_number(m, "roman"), t)
    t = re.sub(rf"\b((?i:{nouns}))\s+(\d+)\b", lambda m: _structure_number(m, "arabic"), t)
    t = re.sub(r"\b([А-ЯЁ][а-яё]+)\s+([IVX]{1,5})\b(?![.\w]*[IVX])", _name_number, t)   # Лев XII

    t = re.sub(r"\b[A-Z]{3,}(?:['’][A-Za-z]+)?\b\.?", _DROP, t)      # фамилии авторов в ссылках: OVID, BRYANT., DAVIES'S
    t = _latin(t)
    if not re.search(CYR, t):
        return ""                                                   # читать нечего (адрес, ссылка)

    prep = {"в": "prep", "во": "prep", "на": "prep", "при": "prep", "о": "prep", "об": "prep",
            "к": "dat", "по": "dat", "до": "gen", "с": "gen", "от": "gen", "после": "gen", "около": "gen",
            "из": "gen", "для": "gen", "без": "gen", "за": "gen"}
    year_noun = {"nom": "год", "gen": "года", "prep": "году", "dat": "году"}

    def year(m):
        before, num, abbr = m.group(1), m.group(2), m.group(3)
        case = prep.get(before.lower(), "gen" if abbr == "г." else None)
        if case is None:
            return m.group(0)                                        # «жил 502 года» — это срок, а не год
        return f"{before} {ordinal(int(num), 'm', case)} {year_noun[case]}"
    t = re.sub(r"\b([А-Яа-яЁё]+)\s+(\d{3,4})\s*(году|года|год|г\.)(?!\w)", year, t)

    def verse(m):
        ch, v1, v2 = m.group(1), m.group(2), m.group(4)
        if v2:
            return f"глава {cardinal(ch)}, стихи с {ordinal(int(v1), 'm', 'gen')} по {ordinal(int(v2))}"
        return f"глава {cardinal(ch)}, стих {cardinal(v1)}"
    months = "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
    t = re.sub(rf"\b(\d{{1,2}})\s+({months})\b", lambda m: f"{ordinal(int(m.group(1)), 'm', 'gen')} {m.group(2)}", t)
    t = re.sub(r"\b(\d+)\s*:\s*(\d+)(\s*[-–]\s*(\d+))?\b", verse, t)
    t = re.sub(r"\b(\d+)\s*[-–]\s*(\d+)\b", lambda m: f"{cardinal(m.group(1))} — {cardinal(m.group(2))}", t)
    t = re.sub(r"\b\d+\b", lambda m: cardinal(m.group(0)), t)

    t = re.sub(rf"(?<={CYR})/(?={CYR})", " или ", t)               # традиция/предание -> «традиция или предание»
    t = t.replace("[", "(").replace("]", ")").replace(_DROP, " ")
    t = re.sub(r"\s{2,}", " ", t)
    return re.sub(r"\s+([,.;:!?])", r"\1", t).strip()


def caps_stress(marked):
    """Результат Silero Stress -> ударная гласная заглавной: Мен+я зов+ут -> МенЯ зовУт (ё и так ударная)."""
    return re.sub(r"\+([аеёиоуыэюяАЕЁИОУЫЭЮЯ])", lambda m: m.group(1) if m.group(1) in "ёЁ" else m.group(1).upper(), marked)
