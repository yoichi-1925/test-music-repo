from pathlib import Path
from typing import Callable
from .audio import AudioProcessor
from .beats import BeatDetector
from .chords import ChordDetector
from .models import AnalysisResult


def analyze(path: Path, progress: Callable[[int, str], None] | None = None) -> AnalysisResult:
    report = progress or (lambda _percent, _stage: None)
    report(10, '音声を変換しています')
    audio = AudioProcessor().load(path)
    report(40, 'テンポと拍を調べています')
    bpm, beats = BeatDetector().detect(audio)
    report(70, 'キーとコードを推定しています')
    chords, key, confidence = ChordDetector().detect(audio, beats)
    report(95, '解析結果を保存しています')
    return AnalysisResult(audio.duration, bpm, beats, key, confidence, chords)
