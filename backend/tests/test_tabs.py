from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from music_analyzer.guitar import CHORD_FORMS, TUNING
from music_analyzer.models import AnalysisResult, ChordSegment
from music_analyzer.tab_cli import load_analysis
from music_analyzer.tabs import GuitarTabGenerator, TabError

ROOT = Path(__file__).resolve().parents[2]


def analysis():
    return load_analysis(ROOT / "examples/progression.json")


@pytest.mark.parametrize("name", CHORD_FORMS)
def test_forms_sound_correct_chord(name):
    notes = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    root = notes.index(name.removesuffix("m"))
    intervals = (0, 3, 7) if name.endswith("m") else (0, 4, 7)
    expected = {(root + interval) % 12 for interval in intervals}
    frets = CHORD_FORMS[name].frets
    assert len(frets) == 6
    actual = {(pitch + fret) % 12 for pitch, fret in zip(TUNING, frets) if fret is not None}
    assert actual == expected
    fingers = [f for f in frets if f is not None and f > 0]
    assert max(fingers) - min(fingers) <= 3


def test_four_strokes_per_bar_and_string_order():
    tab = GuitarTabGenerator().generate(analysis())
    assert len(tab.strokes) == 16
    assert [s.beat for s in tab.strokes] == [1, 2, 3, 4] * 4
    assert [s.sounding_chord for s in tab.strokes[::4]] == ["C", "Am", "F", "G"]
    assert all(s.direction == "down" for s in tab.strokes)
    assert tab.strokes[4].time == 2
    assert tab.strokes[0].form.frets == (None, 3, 2, 0, 1, 0)
    text = tab.to_text()
    assert text.index("   e ") < text.index("   E ")
    assert "   E |   -    |   -    |   -    |   -    |" in text
    assert "Bar 4" in text
    assert json.loads(json.dumps(tab.to_dict()))["strokes"][0]["form"]["frets"][0] is None


def test_detected_beats_and_override():
    result = replace(analysis(), duration=3, chords=[], beats=[0.2, 0.7, 1.25, 1.8], bpm=None)
    strokes = GuitarTabGenerator().generate(result).strokes
    assert [s.time for s in strokes] == pytest.approx([0.2, 0.7, 1.25, 1.8, 2.35, 2.9])
    assert [s.time for s in GuitarTabGenerator().generate(result, bpm=120).strokes] == [0, .5, 1, 1.5, 2, 2.5]
    assert strokes[-1].bar == 2 and strokes[-1].beat == 2


def test_unknown_gaps_and_chord_change_on_beat():
    result = replace(analysis(), duration=2, chords=[ChordSegment(.5, .5, "C", 1), ChordSegment(1, .5, None, 0)])
    strokes = GuitarTabGenerator().generate(result).strokes
    assert [s.sounding_chord for s in strokes] == [None, "C", None, None]
    assert all(s.form is None for s in (strokes[0], strokes[2], strokes[3]))
    assert "N.C." in GuitarTabGenerator().generate(result).to_text()


def test_regenerate_after_manual_correction():
    original = analysis()
    corrected = replace(original, chords=[replace(original.chords[0], chord="Dm", source="manual"), *original.chords[1:]])
    generator = GuitarTabGenerator()
    before, after = generator.generate(original), generator.generate(corrected)
    assert before.strokes[0].sounding_chord == "C"
    assert after.strokes[0].sounding_chord == "Dm"
    assert after.strokes[0].form.frets == CHORD_FORMS["Dm"].frets
    assert before.strokes[4:] == after.strokes[4:]


@pytest.mark.parametrize("changes", [
    {"bpm": None}, {"bpm": float("nan")}, {"bpm": 0}, {"duration": -1},
    {"duration": float("inf")}, {"time_signature": "3/4"}, {"beats": [1, .5]},
    {"beats": [0, 0.01]}, {"beats": [float("nan")]}, {"beats": [8]},
    {"chords": [ChordSegment(0, 2, "C7", 1)]},
    {"chords": [ChordSegment(0, -1, "C", 1)]},
    {"chords": [ChordSegment(7, 2, "C", 1)]},
    {"chords": [ChordSegment(0, 2, "C", 1), ChordSegment(1, 2, "G", 1)]},
])
def test_invalid_progression(changes):
    with pytest.raises(TabError):
        GuitarTabGenerator().generate(replace(analysis(), **changes))


@pytest.mark.parametrize("content", ['[]', '{', '{}', '{"schema_version":2}', '{"schema_version":1,"beats":[],"chords":[null]}'])
def test_invalid_json(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_analysis(path)


def test_cli_output_and_errors(tmp_path):
    output = tmp_path / "tab.txt"
    cmd = [sys.executable, "-m", "music_analyzer.tab_cli", str(ROOT / "examples/progression.json")]
    result = subprocess.run(cmd + ["-o", str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Bar 4" in output.read_text()
    assert subprocess.run(cmd + ["-o", str(output)], capture_output=True).returncode == 1
    result = subprocess.run(cmd + ["--format", "json"], capture_output=True, text=True)
    assert json.loads(result.stdout)["strokes"][0]["sounding_chord"] == "C"
    assert subprocess.run(cmd + ["--bpm", "nan"], capture_output=True).returncode == 1
    assert subprocess.run(cmd[:3] + [str(tmp_path / "missing.json")], capture_output=True).returncode == 1


def test_fast_tempo_float_rounding_and_midbeat_change():
    result = replace(analysis(), duration=1, beats=[0, .2, .4, .6], bpm=300,
                     chords=[ChordSegment(0, .3, "C", 1), ChordSegment(.3, .7, "G", 1)])
    strokes = GuitarTabGenerator().generate(result).strokes
    assert [s.time for s in strokes] == pytest.approx([0, .2, .4, .6, .8])
    assert [s.sounding_chord for s in strokes] == ["C", "C", "G", "G", "G"]
    assert strokes[-1].bar == 2 and strokes[-1].beat == 1
