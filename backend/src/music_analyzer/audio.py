from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile

import librosa
import numpy as np
from numpy.typing import NDArray


class AudioError(ValueError):
    """Invalid, unsupported, or oversized input audio."""


@dataclass(frozen=True)
class AudioData:
    samples: NDArray[np.float32]
    sample_rate: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


class AudioProcessor:
    def __init__(self, max_bytes: int = 100 * 1024 * 1024,
                 max_duration: float = 600, sample_rate: int = 22050):
        self.max_bytes = max_bytes
        self.max_duration = max_duration
        self.sample_rate = sample_rate

    def load(self, path: Path) -> AudioData:
        path = Path(path)
        if path.suffix.lower() not in {".mp3", ".wav"}:
            raise AudioError("MP3またはWAVファイルを指定してください")
        if not path.is_file():
            raise AudioError("音声ファイルが見つかりません")
        if not 0 < path.stat().st_size <= self.max_bytes:
            raise AudioError("ファイルは空、またはサイズ上限を超えています")
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise AudioError("FFmpegが必要です。brew install ffmpeg を実行してください")
        # 入力をシェルに渡さず、上限より少し長く復号して長さ超過を検出する。
        with tempfile.TemporaryDirectory(prefix="music-analysis-") as directory:
            output = Path(directory) / "normalized.wav"
            try:
                subprocess.run([
                    ffmpeg, "-nostdin", "-v", "error", "-i", str(path.resolve()),
                    "-map", "0:a:0", "-vn", "-t", str(self.max_duration + 1),
                    "-ac", "1", "-ar", str(self.sample_rate), "-c:a", "pcm_s16le", str(output),
                ], check=True, capture_output=True, timeout=120)
                samples, sr = librosa.load(output, sr=self.sample_rate, mono=True)
            except (subprocess.SubprocessError, OSError, ValueError) as exc:
                raise AudioError("音声を復号できません。ファイル内容を確認してください") from exc
        if len(samples) == 0 or not np.all(np.isfinite(samples)):
            raise AudioError("有効な音声サンプルがありません")
        if len(samples) / sr > self.max_duration:
            raise AudioError(f"音声の長さは{self.max_duration:g}秒以内にしてください")
        return AudioData(samples, sr)
