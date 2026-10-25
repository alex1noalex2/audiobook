#!/usr/bin/env python3
"""Наводит порядок в папке Audiobook на Google Диске (или на компьютере): у каждой книги своя папка, голоса отдельно,
лишнее — в «_удалить». Ничего не стирает: старое только переносится, стирает владелец сам (папка «_удалить» → Корзина → Очистить).

    python3 local/organize_drive.py /content/drive/MyDrive/Audiobook                        # показать план, ничего не менять
    python3 local/organize_drive.py /content/drive/MyDrive/Audiobook --apply --fixes-for babylon

Порядок после наведения:
    voices/Саша.wav + Саша.txt            голос (копия образца --voice-from), остальные образцы в voices/образцы/
    books/<книга>/<книга>.epub            сама книга и <книга>.drop.txt, <книга>.fixes.txt
    books/<книга>/audio/                  куски 00000.wav…, report.json
    books/<книга>/<книга>.mp3, _частьNN.mp3, _таймкоды.txt, _проверить.txt
    _удалить/                             проба, старая озвучка, части прошлых запусков
Части и итоговый mp3 в «_удалить» не попадают: они лежат в папке книги, их пересобирает --assemble.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

BOOK_SUFFIXES = {".epub", ".pdf"}
TRASH = "_удалить"


def plan(root, voice_name="Саша", voice_from="ref_01", fixes_for=None):
    """-> [(откуда, куда, пояснение)] относительно root; ничего не меняет."""
    root = Path(root)
    moves, taken = [], set()

    def move(src, dst, why):
        if src.exists() and dst not in taken:
            taken.add(dst)
            moves.append((src, root / dst, why))

    top = sorted(root.iterdir())
    stems = sorted({p.stem for p in top if p.is_file() and p.suffix.lower() in BOOK_SUFFIXES and not p.name.startswith("_")})
    names = {p.name for p in top}

    for stem in stems:
        book = Path("books") / stem
        for p in top:
            n = p.name
            if p.is_file() and (p.stem == stem and p.suffix.lower() in BOOK_SUFFIXES or n in (f"{stem}.drop.txt", f"{stem}.fixes.txt")):
                move(p, book / n, "книга и её правила")
            elif p.is_file() and (re.fullmatch(rf"{re.escape(stem)}_часть\d+\.mp3", n) or n in (
                    f"{stem}.mp3", f"{stem}_таймкоды.txt", f"{stem}_проверить.txt", f"{stem}_список.txt")):
                move(p, book / n, "результат прошлого запуска: пересоберите «--assemble»")
        # куски: новая озвучка F5 (<книга>_f5_book) важнее старой (<книга>_audio)
        if f"{stem}_f5_book" in names:
            move(root / f"{stem}_f5_book", book / "audio", "куски озвучки")
            move(root / f"{stem}_audio", Path(TRASH) / f"{stem}_audio", "старая озвучка другой моделью")
        else:
            move(root / f"{stem}_audio", book / "audio", "куски озвучки")
        move(root / f"{stem}_f5", Path(TRASH) / f"{stem}_f5", "проба вопросов")
    if fixes_for in stems:
        move(root / "fixes.txt", Path("books") / fixes_for / f"{fixes_for}.fixes.txt", "общие поправки → поправки этой книги")

    for p in top:
        n = p.name
        if p.is_dir() and re.match(r"bench", n):
            move(p, Path(TRASH) / n, "пробы")
        elif p.is_file() and re.fullmatch(r"voice_\d+\.(wav|txt)", n):
            move(p, Path(TRASH) / n, "старые синтетические голоса")
        elif p.is_file() and n in ("Dva_Vavilona.mp3", "timecodes.txt", "list.txt"):
            move(p, Path(TRASH) / n, "итог прошлой озвучки")
        elif p.is_file() and n.lower() in ("my_voice.mp3",):
            move(p, Path("voices") / "исходные" / n, "исходная запись голоса")

    refs = root / "my_refs"
    if refs.is_dir():
        for ext in (".wav", ".txt"):
            src = refs / f"{voice_from}{ext}"
            if src.exists() and (root / "voices" / f"{voice_name}{ext}") not in [m[1] for m in moves]:
                moves.append((src, root / "voices" / f"{voice_name}{ext}", "голос, копия (копируется, не переносится)"))
        move(refs, Path("voices") / "образцы", "остальные образцы")
    return moves


def apply(moves):
    for src, dst, why in moves:
        if dst.exists():
            print(f"  пропускаю (уже есть): {dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if "копируется" in why:
            shutil.copy2(src, dst)
        else:
            shutil.move(str(src), str(dst))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path, help="папка Audiobook")
    ap.add_argument("--apply", action="store_true", help="выполнить (без него только показывает план)")
    ap.add_argument("--voice-name", default="Саша", help="имя голоса в voices/")
    ap.add_argument("--voice-from", default="ref_01", help="какой образец из my_refs стал голосом")
    ap.add_argument("--fixes-for", help="какой книге принадлежит общий fixes.txt (например babylon)")
    args = ap.parse_args()
    if not args.root.is_dir():
        sys.exit(f"Нет папки {args.root}")
    moves = plan(args.root, args.voice_name, args.voice_from, args.fixes_for)
    if not moves:
        print("Всё уже на своих местах или нет книг (.epub/.pdf) в папке.")
        return
    for src, dst, why in moves:
        print(f"{src.relative_to(args.root)}  →  {dst.relative_to(args.root)}   ({why})")
    known = {m[0] for m in moves}
    left = [p.name for p in sorted(args.root.iterdir()) if p not in known and p.name not in ("books", "voices", TRASH)]
    if left:
        print("\nНе трогаю (не знаю, что это):", ", ".join(left))
    if not args.apply:
        print("\nЭто только план. Чтобы выполнить, добавьте --apply.")
        return
    apply(moves)
    print(f"\nГотово. Папку «{TRASH}» проверьте и удалите сами (потом очистите Корзину Диска).")


if __name__ == "__main__":
    main()
