from pathlib import Path
from .audio import AudioProcessor
from .beats import BeatDetector
from .chords import ChordDetector
from .models import AnalysisResult


def analyze(path: Path) -> AnalysisResult:
    audio = AudioProcessor().load(path)
    bpm, beats = BeatDetector().detect(audio)
    chords, key, confidence = ChordDetector().detect(audio, beats)
    return AnalysisResult(audio.duration, bpm, beats, key, confidence, chords)
