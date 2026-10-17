"""元の区間・信頼度を保ち、変更されたコードだけを手動修正として記録する。"""
from dataclasses import replace

from .guitar import CHORD_FORMS
from .models import AnalysisResult


class ChordEditor:
    def update(self, original: AnalysisResult, names: list[str | None]) -> AnalysisResult:
        if len(names) != len(original.chords):
            raise ValueError('コード数は元の解析結果と同じにしてください')
        if any(name is not None and name not in CHORD_FORMS for name in names):
            raise ValueError('未対応のコードが含まれています')
        chords = [replace(segment, chord=name, source='analysis' if name == segment.chord else 'manual')
                  for segment, name in zip(original.chords, names)]
        return replace(original, chords=chords)


def analysis_from_dict(data: dict) -> AnalysisResult:
    from .models import ChordSegment
    return AnalysisResult(**{**data, 'chords': [ChordSegment(**segment) for segment in data['chords']]})
