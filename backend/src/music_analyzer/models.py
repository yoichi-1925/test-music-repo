from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ChordSegment:
    start: float
    duration: float
    chord: str | None
    confidence: float
    source: str = "analysis"


@dataclass(frozen=True)
class AnalysisResult:
    duration: float
    bpm: float | None
    beats: list[float]
    key: str | None
    key_confidence: float
    chords: list[ChordSegment]
    time_signature: str = "4/4"
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
