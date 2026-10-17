import json
from pathlib import Path
import shutil
import subprocess
import wave

import librosa
import numpy as np
import pytest

from music_analyzer.audio import AudioData, AudioError, AudioProcessor
from music_analyzer.beats import BeatDetector
from music_analyzer.chords import ChordDetector, chord_templates
from music_analyzer.models import AnalysisResult, ChordSegment
from music_analyzer.pipeline import analyze

SR = 22050


def tone(notes, duration=2.0):
    t = np.arange(int(SR * duration)) / SR
    sound = sum(np.sin(2 * np.pi * librosa.midi_to_hz(note) * t) for note in notes)
    return (sound / len(notes) * 0.6).astype(np.float32)


def write_wav(path, samples):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SR)
        stream.writeframes((samples * 32767).astype("<i2").tobytes())


@pytest.mark.parametrize("name,content", [("audio.txt", b"hello"), ("audio.wav", b""), ("audio.mp3", b"not audio")])
def test_invalid_audio(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(AudioError):
        AudioProcessor().load(path)


def test_missing_and_size_limit(tmp_path):
    with pytest.raises(AudioError):
        AudioProcessor().load(tmp_path / "missing.wav")
    path = tmp_path / "large.wav"
    path.write_bytes(b"12345")
    with pytest.raises(AudioError):
        AudioProcessor(max_bytes=4).load(path)


def test_wav_and_duration_limit(tmp_path):
    path = tmp_path / "tone.WAV"
    write_wav(path, tone([60, 64, 67]))
    audio = AudioProcessor().load(path)
    assert audio.sample_rate == SR
    assert audio.duration == pytest.approx(2, abs=0.01)
    with pytest.raises(AudioError):
        AudioProcessor(max_duration=1).load(path)


def test_mp3_decode(tmp_path):
    wav, mp3 = tmp_path / "source.wav", tmp_path / "source.mp3"
    write_wav(wav, tone([60, 64, 67]))
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), str(mp3)], check=True)
    assert AudioProcessor().load(mp3).duration == pytest.approx(2, abs=0.1)


def test_missing_ffmpeg(tmp_path, monkeypatch):
    path = tmp_path / "tone.wav"
    path.write_bytes(b"placeholder")
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(AudioError, match="FFmpeg"):
        AudioProcessor().load(path)


def test_click_tempo_and_beats():
    expected = np.arange(0.5, 12, 0.5)
    clicks = librosa.clicks(times=expected, sr=SR, length=SR * 12)
    bpm, beats = BeatDetector().detect(AudioData(clicks, SR))
    assert bpm == pytest.approx(120, abs=4)
    assert len(beats) >= 18
    assert np.median([min(abs(t - expected)) for t in beats]) < 0.06
    assert all(a < b for a, b in zip(beats, beats[1:]))


@pytest.mark.parametrize("index", range(24))
def test_all_major_minor_chords(index):
    root = 60 + index % 12
    third = 4 if index < 12 else 3
    audio = AudioData(tone([root, root + third, root + 7]), SR)
    chords, _, _ = ChordDetector().detect(audio, [])
    from music_analyzer.chords import CHORD_NAMES
    assert sum(s.duration for s in chords if s.chord == CHORD_NAMES[index]) > 1.5


def test_progression_and_json(tmp_path):
    path = tmp_path / "progression.wav"
    write_wav(path, np.concatenate([tone(notes) for notes in ([60, 64, 67], [57, 60, 64], [53, 57, 60], [55, 59, 62])]))
    result = analyze(path)
    encoded = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert encoded["schema_version"] == 1
    assert encoded["time_signature"] == "4/4"
    assert [c.chord for c in result.chords if c.chord] == ["C", "Am", "F", "G"]
    assert result.chords[0].start == 0
    assert sum(c.duration for c in result.chords) == pytest.approx(result.duration)
    assert all(c.source == "analysis" and c.duration > 0 for c in result.chords)
    assert all(a.start + a.duration == pytest.approx(b.start) for a, b in zip(result.chords, result.chords[1:]))


def test_silence_and_short_audio():
    audio = AudioData(np.zeros(SR, dtype=np.float32), SR)
    assert BeatDetector().detect(audio) == (None, [])
    chords, key, confidence = ChordDetector().detect(audio, [])
    assert len(chords) == 1 and chords[0].chord is None
    assert key is None and confidence == 0
    assert BeatDetector().detect(AudioData(np.ones(100, dtype=np.float32), SR)) == (None, [])


def test_ambiguous_chroma():
    assert ChordDetector.estimate_key(np.ones((12, 8))) == (None, 0.0)
    audio = AudioData(tone(list(range(60, 72))), SR)
    chords, _, _ = ChordDetector().detect(audio, [])
    assert all(c.chord is None for c in chords)


def test_key_profile():
    profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    key, confidence = ChordDetector.estimate_key(np.tile(profile[:, None], (1, 10)))
    assert key == "C major" and confidence > 0


def test_serialization():
    result = AnalysisResult(1, None, [], None, 0, [ChordSegment(0, 1, None, 0)])
    assert result.to_dict()["chords"][0]["chord"] is None
    assert chord_templates().shape == (24, 12)


def test_cli(tmp_path):
    path = tmp_path / "chord.wav"
    write_wav(path, tone([60, 64, 67]))
    import os
    import sys
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    output = tmp_path / "result.json"
    command = [sys.executable, "-m", "music_analyzer.cli", str(path), "-o", str(output)]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["chords"][0]["chord"] == "C"
    assert subprocess.run(command, env=env, capture_output=True).returncode == 1
    assert subprocess.run(command[:-1] + [str(path)], env=env, capture_output=True).returncode == 1
    assert subprocess.run(command[:3] + [str(tmp_path / "missing.wav")], env=env, capture_output=True).returncode == 1


def test_temporal_smoothing(monkeypatch):
    # 中間の1区間だけ別和音寄りでも、切替コストで前後のCを維持する。
    templates = chord_templates()
    vectors = np.tile(templates[0, :, None], (1, 5))
    vectors[:, 2] = 0.45 * templates[0] + 0.55 * templates[9]
    monkeypatch.setattr(librosa.feature, "chroma_stft", lambda **_: vectors)
    audio = AudioData(np.ones(512 * 5, dtype=np.float32) * 0.1, SR)
    boundaries = [512 * i / SR for i in range(1, 5)]
    raw, _, _ = ChordDetector(switch_penalty=0, minimum_margin=0).detect(audio, boundaries)
    smooth, _, _ = ChordDetector(switch_penalty=0.18, minimum_margin=0).detect(audio, boundaries)
    assert any(c.chord == "A" for c in raw)
    assert not any(c.chord == "A" for c in smooth)


def test_stereo_resampling(tmp_path):
    path = tmp_path / "stereo.wav"
    t = np.arange(44100) / 44100
    stereo = np.column_stack((np.sin(2 * np.pi * 261.63 * t), np.sin(2 * np.pi * 329.63 * t)))
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(44100)
        stream.writeframes((stereo * 16000).astype("<i2").tobytes())
    audio = AudioProcessor().load(path)
    assert audio.samples.ndim == 1
    assert audio.sample_rate == 22050
    assert len(audio.samples) == 22050
