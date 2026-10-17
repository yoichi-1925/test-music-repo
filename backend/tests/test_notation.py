import xml.etree.ElementTree as ET

import pytest

from music_analyzer.notation import abc_pitch, make_score


def n(start, duration, midi):
    return {'start':start,'duration':duration,'midi':midi,'confidence':.9}


def test_notes_rests_accidentals_and_absolute_origin():
    score = make_score([n(30,.5,60), n(31,.5,63)],120,30,32)
    events = score['bars'][0]['events']
    assert [e['midi'] for e in events] == [60,None,63,None]
    assert [e['ticks'] for e in events] == [4,4,4,4]
    assert events[0]['start'] == 30
    assert '^D4' in score['abc']
    for event in events:
        token = abc_pitch(event['midi']) if event['midi'] is not None else 'z'
        assert score['abc'][event['full_abc_start']:].startswith(token)
    root = ET.fromstring(score['musicxml'])
    assert root.find('.//divisions').text == '4'
    assert root.find('.//pitch/step').text == 'C'
    assert root.find('.//pitch/alter').text == '1'


def test_ties_across_bars_and_measure_durations():
    score = make_score([n(0,5,60)],120,0,6.125)
    events = [e for bar in score['bars'] for e in bar['events']]
    pitched = [event for event in events if event['midi'] is not None]
    assert [event['ticks'] for event in pitched] == [16,16,8]
    assert pitched[0]['tie_start'] and not pitched[0]['tie_stop']
    assert pitched[1]['tie_start'] and pitched[1]['tie_stop']
    assert pitched[2]['tie_stop'] and not pitched[2]['tie_start']
    assert all(sum(e['ticks'] for e in bar['events']) == 16 for bar in score['bars'])
    xml = ET.fromstring(score['musicxml'])
    assert all(sum(int(n.find('duration').text) for n in measure.findall('note')) == 16 for measure in xml.findall('.//measure'))
    assert len(xml.findall('.//tie[@type="start"]')) == len(xml.findall('.//tie[@type="stop"]'))


def test_bpm_changes_rhythm_without_changing_detected_pitch():
    notes = [n(0,.5,69)]
    slow = make_score(notes,60,0,2)
    fast = make_score(notes,120,0,2)
    assert slow['bars'][0]['events'][0]['ticks'] == 2
    assert fast['bars'][0]['events'][0]['ticks'] == 4
    assert slow['bars'][0]['events'][0]['midi'] == fast['bars'][0]['events'][0]['midi'] == 69
    assert notes == [n(0,.5,69)]


def test_silence_and_short_events():
    score = make_score([n(.01,.01,60)],120,0,1)
    assert score['omitted_short_notes'] == 1
    assert all(e['midi'] is None for bar in score['bars'] for e in bar['events'])
    assert sum(e['ticks'] for e in score['bars'][0]['events']) == 16


@pytest.mark.parametrize('bpm',[0,301,float('nan')])
def test_invalid_tempo(bpm):
    with pytest.raises(ValueError):
        make_score([],bpm,0,1)


def test_abc_octaves():
    assert abc_pitch(48) == '=C,'
    assert abc_pitch(60) == '=C'
    assert abc_pitch(72) == '=c'
    assert abc_pitch(84) == "=c'"
