from dataclasses import asdict, dataclass
import math

from .guitar import CHORD_FORMS, GuitarForm
from .models import AnalysisResult


class TabError(ValueError):
    """Invalid progression or missing timing information."""


@dataclass(frozen=True)
class TabStroke:
    time: float
    bar: int
    beat: int
    sounding_chord: str | None
    form: GuitarForm | None
    direction: str = "down"


@dataclass(frozen=True)
class GuitarTab:
    strokes: list[TabStroke]
    capo: int = 0
    tuning: tuple[str, ...] = ("E2", "A2", "D3", "G3", "B3", "E4")
    time_signature: str = "4/4"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_text(self) -> str:
        lines = ["Guitar TAB | Standard tuning E A D G B E | Capo 0",
                 "4/4 | v = downstroke | - = do not play | N.C. = unknown/rest", ""]
        for offset in range(0, len(self.strokes), 4):
            strokes = self.strokes[offset:offset + 4]
            width = max(8, *(len(s.sounding_chord or "N.C.") + 2 for s in strokes))
            row = lambda values: "|" + "|".join(str(v).center(width) for v in values) + "|"
            lines.extend([
                f"Bar {strokes[0].bar} (start {strokes[0].time:.3f}s)",
                "beat " + row(s.beat for s in strokes),
                "time " + row(f"{s.time:.3f}" for s in strokes),
                "chord" + row(s.sounding_chord or "N.C." for s in strokes),
                "     " + row("v" if s.form else "-" for s in strokes),
            ])
            # TABの表示は高音弦を上にする。ミュート弦にxの打音指示は出さない。
            for index, name in reversed(list(enumerate(("E", "A", "D", "G", "B", "e")))):
                lines.append(f"{name:>4} " + row(
                    s.form.frets[index] if s.form and s.form.frets[index] is not None else "-"
                    for s in strokes))
            lines.append("")
        return "\n".join(lines)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class GuitarTabGenerator:
    def generate(self, result: AnalysisResult, bpm: float | None = None) -> GuitarTab:
        if result.time_signature != "4/4":
            raise TabError("現在は4/4拍子のみ対応しています")
        if not _finite(result.duration) or not 0 < result.duration <= 600:
            raise TabError("音源の長さは0秒超・600秒以内で指定してください")
        previous_end = 0.0
        for chord in result.chords:
            if (not _finite(chord.start) or not _finite(chord.duration)
                    or chord.start < previous_end - 1e-8 or chord.duration <= 0
                    or chord.start + chord.duration > result.duration + 1e-8):
                raise TabError("コード区間は時間順で重複せず、音源の範囲内にしてください")
            if chord.chord is not None and chord.chord not in CHORD_FORMS:
                raise TabError(f"未対応のコードです: {chord.chord}")
            previous_end = chord.start + chord.duration
        beats = result.beats
        if any(not _finite(t) or not 0 <= t < result.duration for t in beats):
            raise TabError("拍位置が不正です")
        if any(b - a < 0.2 - 1e-8 for a, b in zip(beats, beats[1:])):
            raise TabError("拍位置は昇順かつ0.2秒以上の間隔で指定してください")
        tempo = bpm if bpm is not None else result.bpm
        if tempo is not None and (not _finite(tempo) or not 20 <= tempo <= 300):
            raise TabError("BPMは20〜300の範囲で指定してください")
        if bpm is None and len(beats) >= 2:
            times = list(beats)
            # 検出拍を尊重し、末尾の未検出部分のみ最後の拍間隔で補う。
            step = beats[-1] - beats[-2]
            if step < 0.2 - 1e-8:
                raise TabError("拍間隔は0.2秒以上にしてください")
            t = times[-1] + step
            while t < result.duration - 1e-8:
                times.append(t)
                t += step
        else:
            if tempo is None:
                raise TabError("拍またはBPMが必要です。--bpmでテンポを指定してください")
            step = 60 / tempo
            times = [i * step for i in range(math.ceil(result.duration / step))
                     if i * step < result.duration - 1e-8]
        strokes = []
        cursor = 0
        for i, time in enumerate(times):
            while cursor < len(result.chords) and time >= result.chords[cursor].start + result.chords[cursor].duration - 1e-8:
                cursor += 1
            segment = result.chords[cursor] if cursor < len(result.chords) else None
            name = segment.chord if segment and time >= segment.start - 1e-8 else None
            strokes.append(TabStroke(time, i // 4 + 1, i % 4 + 1, name, CHORD_FORMS.get(name)))
        return GuitarTab(strokes)
