"""歌声分離後の主旋律推定と五線譜化。pYINは単独音源用にも保持する。"""
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import librosa
import numpy as np
from scipy.ndimage import median_filter

from .audio import AudioData, AudioProcessor
from .guitar import TUNING


@dataclass(frozen=True)
class MelodyNote:
    start: float
    duration: float
    midi: int
    confidence: float


@dataclass(frozen=True)
class MelodyResult:
    duration: float
    notes: list[MelodyNote]
    method: str = 'pyin-monophonic-v1'

    def to_dict(self) -> dict:
        return asdict(self)


def guitar_notes(notes: list[dict]) -> list[dict]:
    """実音を移調せずフレットへ割り当てる。音域外は押さえ方を未設定にする。"""
    result = []
    previous_fret, previous_string = 3, 1
    for note in notes:
        candidates = [(6 - index, note['midi'] - pitch) for index, pitch in enumerate(TUNING)
                      if 0 <= note['midi'] - pitch <= 20]
        string, fret = (None, None)
        if candidates:
            string, fret = min(candidates, key=lambda pair: abs(pair[1] - previous_fret) * .3
                               + abs(pair[0] - previous_string) * .2 + pair[1] * .05)
            previous_fret, previous_string = fret, string
        result.append({**note, 'string': string, 'fret': fret})
    return result


class MelodyDetector:
    def __init__(self, fmin_midi: int = 36, voicing_threshold: float = .6, minimum_duration: float = .09):
        self.fmin_midi = fmin_midi
        self.voicing_threshold = voicing_threshold
        self.minimum_duration = minimum_duration

    def detect(self, audio: AudioData, progress: Callable[[int, str], None] | None = None) -> MelodyResult:
        sr, hop = 11025, 256
        samples = librosa.resample(audio.samples, orig_sr=audio.sample_rate, target_sr=sr)
        notes: list[MelodyNote] = []
        chunk_size, context = sr * 10, 2048
        # 長い音源でpYINの作業メモリが増え続けないよう、前後の文脈付きで10秒ずつ処理する。
        for core_start in range(0, len(samples), chunk_size):
            core_end = min(core_start + chunk_size, len(samples))
            start, end = max(0, core_start - context), min(len(samples), core_end + context)
            block = samples[start:end]
            if np.max(np.abs(block)) < 1e-4:
                if progress:
                    progress(int(10 + 85 * core_end / len(samples)), 'メロディを推定しています')
                continue
            f0, voiced, probability = librosa.pyin(
                block, fmin=librosa.midi_to_hz(self.fmin_midi), fmax=librosa.note_to_hz('C6'), sr=sr,
                frame_length=1024, hop_length=hop, resolution=.2, n_thresholds=32,
            )
            energy = librosa.feature.rms(y=block, frame_length=1024, hop_length=hop)[0]
            valid = voiced & np.isfinite(f0) & (probability >= self.voicing_threshold) & (energy >= 1e-4)
            pitches = np.round(librosa.hz_to_midi(np.where(valid, f0, 440))).astype(int)
            # 一瞬の半音ぶれのみ平滑化し、無声・低信頼フレームを勝手に音符で埋めない。
            pitches = median_filter(pitches, size=3)
            times = start / sr + np.arange(len(f0)) * hop / sr
            selection = (times >= core_start / sr) & (times < core_end / sr)
            indices = np.flatnonzero(selection)
            run: list[int] = []
            for frame in indices:
                if run and (not valid[frame] or pitches[frame] != pitches[run[-1]]):
                    self._append(notes, run, times, pitches, probability, hop / sr, core_end / sr)
                    run = []
                if valid[frame]:
                    run.append(int(frame))
            if run:
                self._append(notes, run, times, pitches, probability, hop / sr, core_end / sr)
            if progress:
                progress(int(10 + 85 * core_end / len(samples)), 'メロディを推定しています')
        # 同音がチャンク境界を跨いだ場合のみ結合する。短い不安定な断片は表示しない。
        merged: list[MelodyNote] = []
        for note in notes:
            if merged and merged[-1].midi == note.midi and abs(note.start - merged[-1].start - merged[-1].duration) < 1e-6:
                old = merged.pop()
                duration = note.start + note.duration - old.start
                confidence = (old.confidence * old.duration + note.confidence * note.duration) / (old.duration + note.duration)
                merged.append(MelodyNote(old.start, duration, note.midi, confidence))
            else:
                merged.append(note)
        return MelodyResult(audio.duration, [note for note in merged if note.duration >= self.minimum_duration])

    @staticmethod
    def _append(notes, run, times, pitches, probability, step, duration):
        start = float(times[run[0]])
        end = min(float(times[run[-1]]) + step, duration)
        if end > start:
            notes.append(MelodyNote(start, end - start, int(pitches[run[0]]), float(probability[run].mean())))


def analyze_melody(path: Path, progress: Callable[[int, str], None], *, cache_dir: Path | None = None,
                   source: str = 'mix', start: float = 0, end: float | None = None, bpm: float | None = None) -> dict:
    from .beats import BeatDetector
    from .notation import make_score
    from .separation import MelodyError, VocalSeparator
    progress(3, '元音源の区間を確認しています')
    original = AudioProcessor().load(path)
    end = min(end if end is not None else original.duration, original.duration)
    if start >= end:
        raise MelodyError('開始時刻は音源の終了時刻より前にしてください')
    region = AudioData(original.samples[int(start * original.sample_rate):int(end * original.sample_rate)], original.sample_rate)
    vocals = None
    if source == 'mix':
        progress(10, '歌声を伴奏から分離しています（CPUでは時間がかかります）')
        vocals = VocalSeparator(cache_dir or Path('data/stems')).separate(path, start, end, full_duration=original.duration)
    else:
        audio = region
    progress(55, '歌声の音高と発音位置を調べています')
    if vocals:
        detected = neural_notes(vocals).to_dict()
    else:
        detected = MelodyDetector(fmin_midi=36, voicing_threshold=.45, minimum_duration=.08).detect(audio).to_dict()
    notes = [{**note, 'start': note['start'] + start} for note in detected['notes']]
    progress(90, '音符のリズムを整理しています')
    estimated_bpm, _ = BeatDetector().detect(region)
    tempo = bpm if bpm is not None else estimated_bpm
    if tempo is not None and not 20 <= tempo <= 300:
        tempo = None
    score = make_score(notes, tempo, start, end) if tempo else None
    return {'duration': original.duration, 'region_start': start, 'region_end': end,
            'method': 'demucs-htdemucs-crepe-v3' if vocals else 'pyin-solo-v2',
            'notes': notes, 'bpm': tempo, 'estimated_bpm': estimated_bpm,
            'vocals_path': str(vocals) if vocals else None, 'score': score}


def contour_notes(f0: list[float], confidence: list[float], step: float, duration: float) -> MelodyResult:
    """CREPEの連続音高を半音へ整理。短い揺れを抑え、無声区間は保持する。"""
    f0, certainty = np.asarray(f0), np.asarray(confidence)
    valid = np.isfinite(f0) & (f0 > 0) & (certainty >= .35)
    midi = median_filter(librosa.hz_to_midi(np.where(valid, f0, 440)), size=5)
    pitches = np.rint(midi).astype(int)
    # 30ms以下の同音間の脱落だけを補う。息継ぎや長い休符は結合しない。
    for i in range(1, len(valid) - 1):
        if valid[i] or not valid[i-1]:
            continue
        j = i
        while j < len(valid) and not valid[j] and (j - i) * step < .031:
            j += 1
        if j < len(valid) and valid[j] and (j - i) * step <= .031 and pitches[i-1] == pitches[j]:
            valid[i:j], pitches[i:j] = True, pitches[j]
    notes, begin = [], None
    for index in range(len(f0) + 1):
        if begin is not None and (index == len(f0) or not valid[index] or pitches[index] != pitches[begin]):
            start, end = begin * step, min(index * step, duration)
            if end - start + 1e-9 >= .07:
                notes.append(MelodyNote(start, end - start, int(pitches[begin]), float(certainty[begin:index].mean())))
            begin = None
        if index < len(f0) and valid[index] and begin is None:
            begin = index
    return MelodyResult(duration, notes, method='crepe-full-viterbi')


def neural_notes(vocals: Path) -> MelodyResult:
    import json
    import os
    import subprocess
    from .separation import MelodyError
    root = Path(__file__).resolve().parents[3]
    python = Path(os.environ.get('MUSIC_VOCALS_PYTHON', str(root / '.venv-vocals/bin/python')))
    output = vocals.parent / 'pitch-crepe-v2.json'
    if not output.is_file():
        temporary = output.with_suffix('.tmp.json')
        try:
            with (vocals.parent / 'pitch.log').open('w') as log:
                subprocess.run([str(python), str(root / 'scripts/vocal_pitch.py'), str(vocals), str(temporary)],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)
            temporary.replace(output)
        except (OSError, subprocess.SubprocessError) as exc:
            raise MelodyError('音高推定に失敗しました。ボーカル分離環境を更新し、pitch.logを確認してください。') from exc
    data = json.loads(output.read_text())
    return contour_notes(data['f0'], data['confidence'], data['step'], data['duration'])
