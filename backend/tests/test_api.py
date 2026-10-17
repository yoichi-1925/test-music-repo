from dataclasses import replace
import io
import json
import math
from pathlib import Path
import struct
import threading
import time
from uuid import uuid4
import wave

from fastapi.testclient import TestClient
import pytest

from music_analyzer.api import create_app
from music_analyzer.editor import ChordEditor, analysis_from_dict
from music_analyzer.models import AnalysisResult, ChordSegment
from music_analyzer.storage import SongStore


@pytest.fixture
def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(22050)
        samples = [int(7000 * sum(math.sin(2 * math.pi * frequency * i / 22050)
                                  for frequency in (261.6256, 329.6276, 391.9954)) / 3)
                   for i in range(22050 * 2)]
        stream.writeframes(struct.pack(f'<{len(samples)}h', *samples))
    return buffer.getvalue()


def sample():
    return AnalysisResult(2, 120, [0, .5, 1, 1.5], 'C major', .2,
                          [ChordSegment(0, 1, 'C', .95), ChordSegment(1, 1, 'G', .9)])


def fake_analyzer(path, progress):
    assert path.exists()
    progress(70, 'コードを推定しています')
    return sample()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, analyzer=fake_analyzer)) as client:
        yield client


def upload(client, content, name='sample.wav'):
    response = client.post('/api/songs', files={'file': (name, content, 'audio/wav')})
    assert response.status_code == 201, response.text
    return response.json()['id']


def wait_for_analysis(client, song_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f'/api/songs/{song_id}/analysis')
        assert response.status_code == 200
        data = response.json()
        if data['status'] in ('completed', 'failed'):
            return data
        time.sleep(.025)
    pytest.fail('解析が時間内に完了しませんでした')


def analyzed(client, wav_bytes):
    song_id = upload(client, wav_bytes)
    response = client.post(f'/api/songs/{song_id}/analyze')
    assert response.status_code == 202
    assert wait_for_analysis(client, song_id)['status'] == 'completed'
    return song_id


def test_lifecycle_edit_invalidation_and_persistence(client, wav_bytes):
    song_id = analyzed(client, wav_bytes)
    url = f'/api/songs/{song_id}'
    original = client.get(url + '/analysis').json()
    assert original['progress'] == 100 and original['revision'] == 1
    assert original['original_analysis'] == original['analysis']
    assert client.get(url + '/tabs').status_code == 404
    generated = client.post(url + '/tabs', json={'revision': 1})
    assert generated.status_code == 201
    assert generated.json()['tab']['strokes'][0]['sounding_chord'] == 'C'
    assert client.get(url + '/tabs').json()['text'] == generated.json()['text']
    edited = client.put(url + '/chords', json={'revision': 1, 'chords': ['Dm', None]})
    assert edited.status_code == 200
    data = edited.json()
    assert data['revision'] == 2 and data['has_edits'] and not data['has_tab']
    assert data['original_analysis'] == original['original_analysis']
    assert data['analysis']['chords'][0]['source'] == 'manual'
    assert data['analysis']['chords'][1]['chord'] is None
    assert client.get(url + '/tabs').status_code == 404
    assert client.put(url + '/chords', json={'revision': 1, 'chords': ['C', 'G']}).status_code == 409
    assert client.post(url + '/tabs', json={'revision': 1}).status_code == 409
    regenerated = client.post(url + '/tabs', json={'revision': 2, 'bpm': 120}).json()
    assert regenerated['tab']['strokes'][0]['sounding_chord'] == 'Dm'
    assert regenerated['tab']['strokes'][2]['form'] is None
    assert regenerated['revision'] == 2
    store = SongStore(client.app.state.store.root)
    persisted = store.get(song_id)
    assert json.loads(persisted['original'])['chords'][0]['chord'] == 'C'
    assert json.loads(persisted['edited'])['chords'][0]['chord'] == 'Dm'
    assert persisted['tab_revision'] == 2
    restored = client.put(url + '/chords', json={'revision': 2, 'chords': ['C', 'G']}).json()
    assert all(segment['source'] == 'analysis' for segment in restored['analysis']['chords'])
    assert client.get('/api/songs').json()[0]['id'] == song_id
    assert 'path' not in client.get('/api/songs').json()[0]
    assert client.post(url + '/analyze').status_code == 409


def test_pending_and_duplicate_background_job(tmp_path, wav_bytes):
    started, release = threading.Event(), threading.Event()
    def slow(path, progress):
        progress(40, '拍を推定中')
        started.set()
        if not release.wait(10):
            raise RuntimeError('test worker timed out')
        return sample()
    with TestClient(create_app(tmp_path, analyzer=slow)) as client:
        song_id = upload(client, wav_bytes)
        try:
            assert client.post(f'/api/songs/{song_id}/analyze').status_code == 202
            assert started.wait(2)
            data = client.get(f'/api/songs/{song_id}/analysis').json()
            assert data['status'] == 'analyzing' and data['progress'] == 40
            assert client.get('/api/songs').status_code == 200
            assert client.post(f'/api/songs/{song_id}/analyze').status_code == 409
        finally:
            release.set()
        assert wait_for_analysis(client, song_id)['status'] == 'completed'


def test_worker_failure_and_retry(tmp_path, wav_bytes):
    attempts = 0
    def flaky(path, progress):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError('private-path must not leak')
        return sample()
    with TestClient(create_app(tmp_path, analyzer=flaky)) as client:
        song_id = upload(client, wav_bytes)
        url = f'/api/songs/{song_id}'
        client.post(url + '/analyze')
        data = wait_for_analysis(client, song_id)
        assert data['status'] == 'failed'
        assert 'private-path' not in data['error']
        assert client.post(url + '/analyze').status_code == 202
        assert wait_for_analysis(client, song_id)['status'] == 'completed'


@pytest.mark.parametrize('filename,content', [('a.txt', b'text'), ('a.wav', b''), ('a.mp3', b'bad'), ('a.wav', b'bad')])
def test_invalid_upload_cleanup(client, filename, content):
    assert client.post('/api/songs', files={'file': (filename, content)}).status_code == 422
    assert not list(client.app.state.store.uploads.iterdir())
    assert client.get('/api/songs').json() == []


def test_content_mismatch_and_safe_filename(client, wav_bytes):
    assert client.post('/api/songs', files={'file': ('fake.mp3', wav_bytes)}).status_code == 422
    song_id = upload(client, wav_bytes, '../../escape.wav')
    data = client.get(f'/api/songs/{song_id}/analysis').json()
    assert data['filename'] == 'escape.wav'
    files = list(client.app.state.store.uploads.iterdir())
    assert len(files) == 1 and files[0].name == song_id + '.wav'


def test_oversize_and_missing_file(client, wav_bytes, monkeypatch):
    monkeypatch.setattr('music_analyzer.api.MAX_BYTES', 100)
    assert client.post('/api/songs', files={'file': ('large.wav', wav_bytes)}).status_code == 413
    assert client.post('/api/songs', content=b'x', headers={'content-length': str(2 * 1024 * 1024)}).status_code == 413
    assert client.post('/api/songs').status_code == 422
    assert not list(client.app.state.store.uploads.iterdir())


def test_no_ffprobe(client, wav_bytes, monkeypatch):
    monkeypatch.setattr('music_analyzer.api.shutil.which', lambda _: None)
    assert client.post('/api/songs', files={'file': ('test.wav', wav_bytes)}).status_code == 503
    assert client.get('/api/songs').json() == []


def test_missing_song_and_not_ready(client, wav_bytes):
    url = f'/api/songs/{uuid4()}'
    assert client.get(url + '/analysis').status_code == 404
    assert client.post(url + '/analyze').status_code == 404
    assert client.get('/api/songs/not-an-id/analysis').status_code == 422
    song_id = upload(client, wav_bytes)
    url = f'/api/songs/{song_id}'
    assert client.get(url + '/tabs').status_code == 409
    assert client.post(url + '/tabs', json={'revision': 1}).status_code == 409
    assert client.put(url + '/chords', json={'revision': 1, 'chords': []}).status_code == 409


@pytest.mark.parametrize('body', [{'revision': 1, 'chords': ['C7','G']}, {'revision': 1, 'chords': ['C']},
                                  {'revision': 0, 'chords': []}, {'revision': 1, 'chords': [4,'G']},
                                  {'revision': 1, 'chords': ['C','G'], 'extra': True}])
def test_invalid_edits(client, wav_bytes, body):
    song_id = analyzed(client, wav_bytes)
    assert client.put(f'/api/songs/{song_id}/chords', json=body).status_code == 422
    assert client.get(f'/api/songs/{song_id}/analysis').json()['revision'] == 1


@pytest.mark.parametrize('bpm', [0, 301, 'NaN'])
def test_invalid_tab_tempo(client, wav_bytes, bpm):
    song_id = analyzed(client, wav_bytes)
    assert client.post(f'/api/songs/{song_id}/tabs', json={'revision': 1, 'bpm': bpm}).status_code == 422


def test_no_timing_requires_bpm(tmp_path, wav_bytes):
    with TestClient(create_app(tmp_path, analyzer=lambda *_: replace(sample(), bpm=None, beats=[]))) as client:
        song_id = analyzed(client, wav_bytes)
        url = f'/api/songs/{song_id}/tabs'
        assert client.post(url, json={'revision': 1}).status_code == 422
        assert client.post(url, json={'revision': 1, 'bpm': 120}).status_code == 201


def test_restart_persistence_and_interrupted_job(tmp_path, wav_bytes):
    with TestClient(create_app(tmp_path, analyzer=fake_analyzer)) as client:
        song_id = analyzed(client, wav_bytes)
        client.post(f'/api/songs/{song_id}/tabs', json={'revision': 1})
        pending = upload(client, wav_bytes)
        client.app.state.store.queue(pending)
    with TestClient(create_app(tmp_path, analyzer=fake_analyzer)) as client:
        assert client.get(f'/api/songs/{song_id}/analysis').json()['status'] == 'completed'
        assert client.get(f'/api/songs/{song_id}/tabs').status_code == 200
        interrupted = client.get(f'/api/songs/{pending}/analysis').json()
        assert interrupted['status'] == 'failed' and '再起動' in interrupted['error']


def test_editor_preserves_timing_and_confidence():
    original = sample()
    result = ChordEditor().update(original, ['Am', 'G'])
    assert result.chords[0].source == 'manual' and result.chords[1].source == 'analysis'
    assert result.chords[0].start == original.chords[0].start
    assert result.chords[0].confidence == original.chords[0].confidence
    assert analysis_from_dict(result.to_dict()) == result
    assert original.chords[0].chord == 'C'


def test_real_audio_through_api(tmp_path, wav_bytes):
    with TestClient(create_app(tmp_path)) as client:
        song_id = upload(client, wav_bytes)
        assert client.post(f'/api/songs/{song_id}/analyze').status_code == 202
        result = wait_for_analysis(client, song_id, timeout=120)
        assert result['status'] == 'completed', result['error']
        assert any(segment['chord'] == 'C' for segment in result['analysis']['chords'])
        response = client.post(f'/api/songs/{song_id}/tabs', json={'revision': 1, 'bpm': 120})
        assert response.status_code == 201
        assert response.json()['tab']['strokes'][0]['sounding_chord'] == 'C'


def test_audio_range_and_missing_file(client, wav_bytes):
    song_id = upload(client, wav_bytes)
    url = f'/api/songs/{song_id}/audio'
    response = client.get(url)
    assert response.status_code == 200 and response.content == wav_bytes
    assert response.headers['content-type'].startswith('audio/wav')
    partial = client.get(url, headers={'Range': 'bytes=0-43'})
    assert partial.status_code == 206 and partial.content == wav_bytes[:44]
    assert partial.headers['content-range'].startswith('bytes 0-43/')
    Path(client.app.state.store.get(song_id)['path']).unlink()
    assert client.get(url).status_code == 404


def test_melody_lifecycle_preserves_chords_and_tab(tmp_path, wav_bytes):
    expected = {'duration': 2, 'method': 'test', 'notes': [
        {'start': 0, 'duration': 1, 'midi': 60, 'confidence': .9, 'string': 2, 'fret': 1}]}
    with TestClient(create_app(tmp_path, analyzer=fake_analyzer, melody_analyzer=lambda *_: expected)) as client:
        song_id = analyzed(client, wav_bytes)
        url = f'/api/songs/{song_id}'
        client.put(url + '/chords', json={'revision': 1, 'chords': ['Dm', 'G']})
        client.post(url + '/tabs', json={'revision': 2})
        before = client.get(url + '/analysis').json()
        assert client.get(url + '/melody').json()['status'] == 'idle'
        assert client.post(url + '/melody').status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = client.get(url + '/melody').json()
            if state['status'] == 'completed':
                break
            time.sleep(.01)
        assert state['status'] == 'completed' and state['progress'] == 100
        assert state['result'] == {**expected, 'vocals_available':False}
        assert client.get(url + '/analysis').json() == before
        assert client.get(url + '/tabs').status_code == 200
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(url + '/melody').json()['result'] == {**expected, 'vocals_available':False}


def test_melody_pending_failure_and_retry(tmp_path, wav_bytes):
    started, release = threading.Event(), threading.Event()
    attempts = 0
    def extractor(path, progress):
        nonlocal attempts
        attempts += 1
        progress(40, 'estimating')
        started.set()
        if not release.wait(10):
            raise RuntimeError('timeout')
        if attempts == 1:
            raise RuntimeError('private path')
        return {'duration': 2, 'method': 'test', 'notes': []}
    with TestClient(create_app(tmp_path, analyzer=fake_analyzer, melody_analyzer=extractor)) as client:
        song_id = analyzed(client, wav_bytes)
        url = f'/api/songs/{song_id}/melody'
        try:
            assert client.post(url).status_code == 202
            assert started.wait(2)
            assert client.get(url).json()['progress'] == 40
            assert client.post(url).status_code == 409
        finally:
            release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and client.get(url).json()['status'] != 'failed':
            time.sleep(.01)
        state = client.get(url).json()
        assert state['status'] == 'failed' and 'private path' not in state['error']
        assert client.get(f'/api/songs/{song_id}/analysis').json()['status'] == 'completed'
        assert client.post(url).status_code == 202


def test_melody_during_analysis_and_restart(client, wav_bytes):
    song_id = upload(client, wav_bytes)
    url = f'/api/songs/{song_id}'
    client.app.state.store.queue(song_id)
    assert client.post(url + '/melody').status_code == 409
    assert client.get(f'/api/songs/{uuid4()}/melody').status_code == 404
    client.app.state.store.complete(song_id, sample().to_dict())
    client.app.state.store.queue_melody(song_id)
    client.app.state.store.initialize()
    assert client.get(url + '/melody').json()['status'] == 'failed'
    assert client.get(url + '/analysis').json()['status'] == 'completed'


def test_legacy_database_migration(tmp_path):
    store = SongStore(tmp_path)
    with store.connect() as db:
        db.execute('''CREATE TABLE songs (
            id TEXT PRIMARY KEY, filename TEXT, path TEXT, created_at TEXT,
            status TEXT, stage TEXT, progress INTEGER, error TEXT,
            original TEXT, edited TEXT, revision INTEGER, tab_json TEXT, tab_text TEXT, tab_revision INTEGER)''')
        db.execute("INSERT INTO songs(id,status,original,edited,revision,tab_text) VALUES(?,?,?,?,?,?)",
                   ('old', 'completed', 'original-json', 'edited-json', 5, 'saved-tab'))
    store.initialize()
    store.initialize()
    record = store.get('old')
    assert record['melody_status'] == 'idle' and record['melody'] is None
    assert record['original'] == 'original-json' and record['edited'] == 'edited-json'
    assert record['revision'] == 5 and record['tab_text'] == 'saved-tab'


def test_staff_without_chord_analysis_and_score_download(tmp_path, wav_bytes):
    result = {'duration':2, 'region_start':0, 'region_end':2, 'method':'pyin-solo-v2',
              'notes':[{'start':0,'duration':.5,'midi':60,'confidence':.9}], 'score':None, 'vocals_path':None}
    with TestClient(create_app(tmp_path, melody_analyzer=lambda *_: result)) as client:
        song_id = upload(client,wav_bytes)
        url = f'/api/songs/{song_id}'
        assert client.post(url+'/score',json={'bpm':120}).status_code == 409
        assert client.post(url+'/melody',json={'source':'solo','start':0,'end':2}).status_code == 202
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            if client.get(url+'/melody').json()['status']=='completed':
                break
            time.sleep(.01)
        assert client.get(url+'/score').status_code == 404
        revised = client.post(url+'/score',json={'bpm':120})
        assert revised.status_code == 200
        body = revised.json()['result']
        assert body['score']['bars'][0]['events'][0]['midi'] == 60
        assert 'vocals_path' not in body
        xml = client.get(url+'/score')
        assert xml.status_code == 200 and '<score-partwise' in xml.text
        assert 'melody.musicxml' in xml.headers['content-disposition']
        assert client.get(url+'/score?format=abc').text.startswith('X:1')
        assert client.get(url+'/score?format=pdf').status_code == 422
        assert client.get(url+'/vocals').status_code == 404
        assert client.get(url+'/analysis').json()['status'] == 'uploaded'


@pytest.mark.parametrize('options',[{'start':10,'end':5},{'source':'invalid'},{'bpm':0},{'start':-1}])
def test_invalid_melody_options(client,wav_bytes,options):
    song_id = upload(client,wav_bytes)
    assert client.post(f'/api/songs/{song_id}/melody',json=options).status_code == 422


def test_vocals_range_and_no_internal_path_leak(tmp_path,wav_bytes):
    vocals = tmp_path/'vocals.wav'
    vocals.write_bytes(wav_bytes)
    result = {'duration':20,'region_start':10,'region_end':12,'notes':[], 'vocals_path':str(vocals)}
    with TestClient(create_app(tmp_path/'data',melody_analyzer=lambda *_:result)) as client:
        song_id = upload(client,wav_bytes)
        url = f'/api/songs/{song_id}'
        client.post(url+'/melody')
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if client.get(url+'/melody').json()['status']=='completed':break
            time.sleep(.01)
        body=client.get(url+'/melody').json()['result']
        assert body['vocals_available'] and 'vocals_path' not in body
        response=client.get(url+'/vocals',headers={'Range':'bytes=0-43'})
        assert response.status_code==206 and response.content==wav_bytes[:44]
