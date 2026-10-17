import librosa
import numpy as np
from .audio import AudioData


class BeatDetector:
    def detect(self, audio: AudioData) -> tuple[float | None, list[float]]:
        if audio.duration < 1 or np.max(np.abs(audio.samples)) < 1e-5:
            return None, []
        tempo, frames = librosa.beat.beat_track(
            y=audio.samples, sr=audio.sample_rate, hop_length=512, trim=False,
        )
        bpm = float(np.asarray(tempo).reshape(-1)[0])
        times = librosa.frames_to_time(frames, sr=audio.sample_rate, hop_length=512)
        beats = [float(t) for t in times if 0 <= t < audio.duration]
        return (bpm, beats) if bpm > 0 and len(beats) >= 2 else (None, [])
