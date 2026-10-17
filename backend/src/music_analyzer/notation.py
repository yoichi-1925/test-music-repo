"""時刻付き単音列を16分音符の格子へ整理し、五線譜用ABC/MusicXMLを作る。"""
import math
from xml.etree.ElementTree import Element, SubElement, tostring

PITCHES = (('C', 0), ('C', 1), ('D', 0), ('D', 1), ('E', 0), ('F', 0),
           ('F', 1), ('G', 0), ('G', 1), ('A', 0), ('A', 1), ('B', 0))
VALUES = ((16, 'whole', False), (12, 'half', True), (8, 'half', False), (6, 'quarter', True),
          (4, 'quarter', False), (3, 'eighth', True), (2, 'eighth', False), (1, '16th', False))


def abc_pitch(midi: int) -> str:
    step, sharp = PITCHES[midi % 12]
    octave = midi // 12 - 1
    name = step if octave <= 4 else step.lower()
    name += ',' * max(0, 4 - octave) + "'" * max(0, octave - 5)
    return ('^' if sharp else '=') + name


def make_score(notes: list[dict], bpm: float, start: float, end: float) -> dict:
    if not math.isfinite(bpm) or not 20 <= bpm <= 300 or not 0 <= start < end:
        raise ValueError('有効なBPM（20〜300）と開始・終了時刻が必要です')
    tick_seconds = 60 / bpm / 4
    total = max(1, math.ceil((end - start) / tick_seconds - 1e-8))
    spans, cursor, omitted = [], 0, 0
    for note in sorted(notes, key=lambda n: n['start']):
        if note['start'] >= end or note['start'] + note['duration'] <= start:
            continue
        a = max(0, round((note['start'] - start) / tick_seconds), cursor)
        b = min(total, round((note['start'] + note['duration'] - start) / tick_seconds))
        if b <= a:
            omitted += 1
            continue
        if a > cursor:
            spans.append({'tick': cursor, 'ticks': a - cursor, 'midi': None, 'source_start': start + cursor * tick_seconds})
        spans.append({'tick': a, 'ticks': b - a, 'midi': note['midi'], 'confidence': note.get('confidence', 0),
                      'source_start': note['start'], 'source_duration': note['duration']})
        cursor = b
    if cursor < total:
        spans.append({'tick': cursor, 'ticks': total - cursor, 'midi': None, 'source_start': start + cursor * tick_seconds})
    bars = [{'number': i + 1, 'events': []} for i in range(math.ceil(total / 16))]
    for span in spans:
        tick, remaining, parts = span['tick'], span['ticks'], []
        while remaining:
            available = min(remaining, 16 - tick % 16)
            # 拍頭から離れた位置では拍境界で分け、タイで結んでリズムを読みやすくする。
            if tick % 4:
                available = min(available, 4 - tick % 4)
            size, kind, dotted = next(value for value in VALUES if value[0] <= available)
            parts.append({**span, 'tick': tick, 'ticks': size, 'type': kind, 'dotted': dotted,
                          'start': start + tick * tick_seconds, 'duration': size * tick_seconds})
            tick += size
            remaining -= size
        for i, event in enumerate(parts):
            event['tie_start'] = event['midi'] is not None and i < len(parts) - 1
            event['tie_stop'] = event['midi'] is not None and i > 0
            bars[event['tick'] // 16]['events'].append(event)
    # 最終小節の空きも休符で埋め、常に4/4として解釈できる譜面にする。
    if total % 16:
        tick = total
        while tick % 16:
            available = 16 - tick % 16
            if tick % 4:
                available = min(available, 4 - tick % 4)
            size, kind, dotted = next(value for value in VALUES if value[0] <= available)
            bars[-1]['events'].append({'tick': tick, 'ticks': size, 'type': kind, 'dotted': dotted,
                                      'midi': None, 'start': start + tick * tick_seconds,
                                      'duration': size * tick_seconds, 'source_start': end,
                                      'tie_start': False, 'tie_stop': False})
            tick += size
    full_header = f'X:1\nT:Melody draft\nM:4/4\nL:1/16\nQ:1/4={bpm:g}\nK:C clef=treble\n'
    abc = full_header
    for index, bar in enumerate(bars):
        local = full_header.replace('T:Melody draft\n', '')
        for offset, event in enumerate(bar['events']):
            pitch = abc_pitch(event['midi']) if event['midi'] is not None else 'z'
            token = pitch + str(event['ticks']) + ('-' if event['tie_start'] else '')
            event['abc_start'] = len(local)
            event['abc_end'] = len(local) + len(token)
            event['full_abc_start'] = len(abc)
            local += token
            abc += token
            following = bar['events'][offset + 1] if offset + 1 < len(bar['events']) else None
            # ABCの空白は連桁を切るため、拍内の短音符は空白なしでまとめる。
            if following is None or following['tick'] % 4 == 0:
                local += ' '
                abc += ' '
        bar['abc'] = local + '|'
        abc += '|'
        abc += '\n' if (index + 1) % 4 == 0 or index == len(bars) - 1 else ' '
    score = {'bpm': bpm, 'origin': start, 'region_end': end, 'ticks_per_beat': 4, 'time_signature': '4/4',
             'bars': bars, 'abc': abc, 'omitted_short_notes': omitted}
    score['musicxml'] = musicxml(score)
    return score


def musicxml(score: dict) -> str:
    root = Element('score-partwise', version='4.0')
    work = SubElement(root, 'work')
    SubElement(work, 'work-title').text = 'Melody draft'
    part_list = SubElement(root, 'part-list')
    score_part = SubElement(part_list, 'score-part', id='P1')
    SubElement(score_part, 'part-name').text = 'Voice'
    part = SubElement(root, 'part', id='P1')
    for bar in score['bars']:
        measure = SubElement(part, 'measure', number=str(bar['number']))
        if bar['number'] == 1:
            attributes = SubElement(measure, 'attributes')
            SubElement(attributes, 'divisions').text = '4'
            key = SubElement(attributes, 'key')
            SubElement(key, 'fifths').text = '0'
            time = SubElement(attributes, 'time')
            SubElement(time, 'beats').text = '4'
            SubElement(time, 'beat-type').text = '4'
            clef = SubElement(attributes, 'clef')
            SubElement(clef, 'sign').text = 'G'
            SubElement(clef, 'line').text = '2'
            direction = SubElement(measure, 'direction')
            metronome = SubElement(SubElement(direction, 'direction-type'), 'metronome')
            SubElement(metronome, 'beat-unit').text = 'quarter'
            SubElement(metronome, 'per-minute').text = str(score['bpm'])
            SubElement(direction, 'sound', tempo=str(score['bpm']))
        for event in bar['events']:
            note = SubElement(measure, 'note')
            if event['midi'] is None:
                SubElement(note, 'rest')
            else:
                step, alter = PITCHES[event['midi'] % 12]
                pitch = SubElement(note, 'pitch')
                SubElement(pitch, 'step').text = step
                if alter:
                    SubElement(pitch, 'alter').text = str(alter)
                SubElement(pitch, 'octave').text = str(event['midi'] // 12 - 1)
            SubElement(note, 'duration').text = str(event['ticks'])
            for kind in ('stop', 'start'):
                if event[f'tie_{kind}']:
                    SubElement(note, 'tie', type=kind)
            SubElement(note, 'type').text = event['type']
            if event['dotted']:
                SubElement(note, 'dot')
            if event['midi'] is not None:
                SubElement(note, 'stem').text = 'up' if event['midi'] < 71 else 'down'
            if event['tie_start'] or event['tie_stop']:
                notations = SubElement(note, 'notations')
                for kind in ('stop', 'start'):
                    if event[f'tie_{kind}']:
                        SubElement(notations, 'tied', type=kind)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + tostring(root, encoding='unicode')
