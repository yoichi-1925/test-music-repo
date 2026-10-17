import librosa
import numpy as np
from numpy.typing import NDArray
from .audio import AudioData
from .models import ChordSegment

NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
CHORD_NAMES = tuple(note + suffix for suffix in ("", "m") for note in NOTES)


def chord_templates() -> NDArray[np.float64]:
    templates = np.zeros((24, 12))
    for index in range(24):
        root = index % 12
        intervals = (0, 4, 7) if index < 12 else (0, 3, 7)
        templates[index, [(root + step) % 12 for step in intervals]] = 1 / np.sqrt(3)
    return templates


class ChordDetector:
    def __init__(self, switch_penalty: float = 0.18, minimum_similarity: float = 0.72,
                 minimum_margin: float = 0.06):
        self.switch_penalty = switch_penalty
        self.minimum_similarity = minimum_similarity
        self.minimum_margin = minimum_margin

    def detect(self, audio: AudioData, beats: list[float]) -> tuple[list[ChordSegment], str | None, float]:
        hop = 512
        chroma = librosa.feature.chroma_stft(y=audio.samples, sr=audio.sample_rate,
                                            n_fft=4096, hop_length=hop, tuning=0)
        # 拍が取れない場合は0.5秒ごとの区間を使用。冒頭・末尾も必ず含める。
        boundaries = np.unique([0.0, *(beats if beats else np.arange(0.5, audio.duration, 0.5)), audio.duration])
        times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=audio.sample_rate, hop_length=hop)
        vectors, quiet = [], []
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            mask = (times >= start) & (times < end)
            vector = chroma[:, mask].mean(axis=1) if mask.any() else np.zeros(12)
            vectors.append(vector / max(float(np.linalg.norm(vector)), 1e-12))
            samples = audio.samples[int(start * audio.sample_rate):int(end * audio.sample_rate)]
            quiet.append(len(samples) == 0 or float(np.sqrt(np.mean(samples ** 2))) < 1e-4)
        scores = np.asarray(vectors) @ chord_templates().T
        # Viterbiで切替コストを課し、一瞬の特徴量変化によるコードの乱立を抑える。
        dp = scores[0].copy()
        back = np.zeros(scores.shape, dtype=int)
        penalty = self.switch_penalty * (1 - np.eye(24))
        for i in range(1, len(scores)):
            candidates = dp[:, None] - penalty
            back[i] = candidates.argmax(axis=0)
            dp = scores[i] + candidates.max(axis=0)
        states = [int(dp.argmax())]
        for i in range(len(scores) - 1, 0, -1):
            states.append(int(back[i, states[-1]]))
        states.reverse()
        segments: list[ChordSegment] = []
        for i, state in enumerate(states):
            score = float(scores[i, state])
            other = float(np.max(np.delete(scores[i], state)))
            known = not quiet[i] and score >= self.minimum_similarity and score - other >= self.minimum_margin
            chord = CHORD_NAMES[state] if known else None
            confidence = max(0.0, min(1.0, score)) if not quiet[i] else 0.0
            start, end = float(boundaries[i]), float(boundaries[i + 1])
            if segments and segments[-1].chord == chord:
                previous = segments.pop()
                duration = end - previous.start
                confidence = (previous.confidence * previous.duration + confidence * (end - start)) / duration
                segments.append(ChordSegment(previous.start, duration, chord, confidence))
            else:
                segments.append(ChordSegment(start, end - start, chord, confidence))
        key, confidence = self.estimate_key(chroma) if not all(quiet) else (None, 0.0)
        return segments, key, confidence

    @staticmethod
    def estimate_key(chroma: NDArray) -> tuple[str | None, float]:
        # 調のプロファイルを全調に移調して照合。単一和音では調が曖昧になり得る。
        profiles = ([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
                    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        vector = chroma.mean(axis=1)
        vector = vector - vector.mean()
        if np.linalg.norm(vector) < 1e-8:
            return None, 0.0
        correlations = []
        for profile in profiles:
            for root in range(12):
                shifted = np.roll(profile, root)
                centered = shifted - shifted.mean()
                correlations.append(float(np.dot(vector, centered) / (np.linalg.norm(vector) * np.linalg.norm(centered))))
        order = np.argsort(correlations)
        best = int(order[-1])
        margin = correlations[best] - correlations[int(order[-2])]
        confidence = max(0.0, min(1.0, margin))
        key = NOTES[best % 12] + (" major" if best < 12 else " minor")
        return (key if correlations[best] >= 0.5 and margin >= 0.03 else None), confidence
