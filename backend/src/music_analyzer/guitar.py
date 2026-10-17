"""標準チューニングのコードフォーム。弦順は低音Eから高音e。"""
from dataclasses import dataclass

Frets = tuple[int | None, int | None, int | None, int | None, int | None, int | None]
TUNING = (40, 45, 50, 55, 59, 64)


@dataclass(frozen=True)
class GuitarForm:
    name: str
    frets: Frets


# Noneの弦は発音しない。開放コードを優先し、必要な調ではバレーコードを使う。
CHORD_FORMS = {
    name: GuitarForm(name, frets) for name, frets in {
        "C": (None, 3, 2, 0, 1, 0), "C#": (None, 4, 6, 6, 6, 4),
        "D": (None, None, 0, 2, 3, 2), "D#": (None, 6, 8, 8, 8, 6),
        "E": (0, 2, 2, 1, 0, 0), "F": (1, 3, 3, 2, 1, 1),
        "F#": (2, 4, 4, 3, 2, 2), "G": (3, 2, 0, 0, 0, 3),
        "G#": (4, 6, 6, 5, 4, 4), "A": (None, 0, 2, 2, 2, 0),
        "A#": (None, 1, 3, 3, 3, 1), "B": (None, 2, 4, 4, 4, 2),
        "Cm": (None, 3, 5, 5, 4, 3), "C#m": (None, 4, 6, 6, 5, 4),
        "Dm": (None, None, 0, 2, 3, 1), "D#m": (None, 6, 8, 8, 7, 6),
        "Em": (0, 2, 2, 0, 0, 0), "Fm": (1, 3, 3, 1, 1, 1),
        "F#m": (2, 4, 4, 2, 2, 2), "Gm": (3, 5, 5, 3, 3, 3),
        "G#m": (4, 6, 6, 4, 4, 4), "Am": (None, 0, 2, 2, 1, 0),
        "A#m": (None, 1, 3, 3, 2, 1), "Bm": (None, 2, 4, 4, 3, 2),
    }.items()
}
