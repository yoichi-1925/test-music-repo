import numpy as np
import pytest

from music_analyzer.audio import AudioData
from music_analyzer.melody import MelodyDetector, guitar_notes

SR = 11025


def tone(midi, seconds):
    t = np.arange(round(SR * seconds)) / SR
    return (.5 * np.sin(2 * np.pi * 440 * 2 ** ((midi - 69) / 12) * t)).astype(np.float32)


def test_synthetic_melody_and_silence():
    audio = AudioData(np.concatenate([tone(60, .7), np.zeros(round(SR * .3)), tone(64, .7), tone(67, .7)]).astype(np.float32), SR)
    result = MelodyDetector().detect(audio)
    assert [note.midi for note in result.notes] == [60, 64, 67]
    assert result.notes[0].start < .1
    assert result.notes[1].start == pytest.approx(1, abs=.12)
    assert result.notes[1].start > result.notes[0].start + result.notes[0].duration + .1
    assert all(.6 <= note.confidence <= 1 for note in result.notes)
    assert all(note.start + note.duration <= audio.duration + 1e-9 for note in result.notes)
    assert all(a.start + a.duration <= b.start + 1e-9 for a, b in zip(result.notes, result.notes[1:]))


def test_silence_unknown_and_progress():
    updates = []
    result = MelodyDetector().detect(AudioData(np.zeros(SR, dtype=np.float32), SR), lambda p, _: updates.append(p))
    assert result.notes == []
    assert updates[-1] == 95


def test_chunk_boundary_merges_same_note():
    audio = AudioData(tone(69, 10.5), SR)
    result = MelodyDetector().detect(audio)
    assert len(result.notes) == 1
    assert result.notes[0].midi == 69
    assert result.notes[0].duration > 10
    assert result.notes[0].start + result.notes[0].duration <= audio.duration


def test_guitar_mapping_and_out_of_range():
    source = [{'start': i, 'duration': 1, 'midi': midi, 'confidence': .9}
              for i, midi in enumerate([40, 60, 64, 67, 84, 100, 30])]
    result = guitar_notes(source)
    tuning = {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40}
    for note in result[:5]:
        assert tuning[note['string']] + note['fret'] == note['midi']
        assert 0 <= note['fret'] <= 20
    assert all(note['string'] is None and note['fret'] is None for note in result[-2:])
    assert 'fret' not in source[0]


def test_neural_contour_silence_glitch_and_pitch_change():
    from music_analyzer.melody import contour_notes
    hz = lambda n: float(440 * 2 ** ((n-69)/12))
    f0 = [hz(60)] * 30 + [hz(64)] * 30 + [hz(67)] * 20
    confidence = [.9] * 60 + [0] * 20
    confidence[10:12] = [0, 0]
    result = contour_notes(f0, confidence, .01, .8)
    assert [n.midi for n in result.notes] == [60, 64]
    assert result.notes[0].duration == pytest.approx(.3)
    assert result.notes[-1].start + result.notes[-1].duration == pytest.approx(.6)
    assert contour_notes([440] * 100, [0] * 100, .01, 1).notes == []


def test_missing_vocal_environment_is_actionable(tmp_path, monkeypatch):
    from music_analyzer.separation import VocalSeparator, MelodyError
    monkeypatch.setenv('MUSIC_VOCALS_PYTHON', str(tmp_path / 'missing'))
    with pytest.raises(MelodyError, match='README'):
        VocalSeparator(tmp_path).separate(tmp_path / 'anything.mp3', 0, 10)


def test_vocal_cache_reuses_same_content_and_crops_full_stem(tmp_path, monkeypatch):
    import soundfile as sf
    from music_analyzer.separation import VocalSeparator, cache_key
    source = tmp_path / 'source.mp3'
    copy = tmp_path / 'copy.mp3'
    source.write_bytes(b'test content')
    copy.write_bytes(source.read_bytes())
    assert cache_key(source,0,2) == cache_key(copy,0,2)
    python = tmp_path / 'python'
    python.touch()
    monkeypatch.setenv('MUSIC_VOCALS_PYTHON', str(python))
    cache = tmp_path / 'stems'
    full = cache / cache_key(source,0,2)
    stem = full / 'separated/htdemucs/mix/vocals.wav'
    stem.parent.mkdir(parents=True)
    sf.write(stem, tone(60,2), SR)
    (full / 'complete.json').write_text('{}')
    output = VocalSeparator(cache).separate(copy,.5,1,full_duration=2)
    y, sr = sf.read(output)
    assert len(y) / sr == pytest.approx(.5, abs=.001)
    # 分離ワーカー用のpythonは空ファイルなので、再分離せず切り出したことも確認できる。
    assert output.is_file()


def test_neural_minimum_duration_rounding():
    from music_analyzer.melody import contour_notes
    f0 = [440.] * 30
    confidence = [0.] * 30
    confidence[10:17] = [.9] * 7
    result = contour_notes(f0, confidence, .01, .3)
    assert len(result.notes) == 1
    assert result.notes[0].duration == pytest.approx(.07)
