"""ローカル単一プロセス用のFastAPIアプリケーション。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Annotated, Callable, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .editor import ChordEditor, analysis_from_dict
from .models import AnalysisResult
from .storage import ConflictError, SongStore
from .tabs import GuitarTabGenerator, TabError

Analyzer = Callable[[Path, Callable[[int, str], None]], AnalysisResult]
MAX_BYTES = 100 * 1024 * 1024
LOGGER = logging.getLogger(__name__)


class ChordUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1, strict=True)
    chords: list[str | None] = Field(max_length=10000)


class TabRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1, strict=True)
    bpm: float | None = Field(default=None, ge=20, le=300, allow_inf_nan=False)


class MelodyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: Literal['mix', 'solo'] = 'mix'
    start: float = Field(default=0, ge=0, le=600, allow_inf_nan=False)
    end: float | None = Field(default=None, gt=0, le=600, allow_inf_nan=False)
    bpm: float | None = Field(default=None, ge=20, le=300, allow_inf_nan=False)


class ScoreRequest(BaseModel):
    bpm: float = Field(ge=20, le=300, allow_inf_nan=False)


def probe_audio(path: Path) -> None:
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise HTTPException(503, 'FFmpeg（ffprobe）がインストールされていません')
    try:
        probe = subprocess.run([
            ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
            'stream=codec_name:format=duration,format_name', '-of', 'json', str(path),
        ], capture_output=True, text=True, check=True, timeout=20)
        data = json.loads(probe.stdout)
        duration = float(data.get('format', {}).get('duration', 'nan'))
        containers = set(data.get('format', {}).get('format_name', '').split(','))
        expected = 'mp3' if path.suffix == '.mp3' else 'wav'
        if not data.get('streams') or expected not in containers or not 0 < duration <= 600:
            raise ValueError('invalid audio')
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise HTTPException(422, '有効なMP3/WAV音源（10分以内）を選んでください') from exc


def default_analyzer(path: Path, progress: Callable[[int, str], None]) -> AnalysisResult:
    # 重い音声ライブラリの読み込みもワーカースレッド側で行う。
    from .pipeline import analyze
    return analyze(path, progress)


def create_app(data_dir: Path | None = None, analyzer: Analyzer = default_analyzer,
               melody_analyzer: Callable | None = None) -> FastAPI:
    root = data_dir or Path(os.environ.get('MUSIC_DATA_DIR', 'data'))
    store = SongStore(root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        app.state.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='music-analysis')
        try:
            yield
        finally:
            app.state.executor.shutdown(wait=True)

    app = FastAPI(title='Melody Room API', version='0.4.0', lifespan=lifespan)
    app.state.store = store

    @app.middleware('http')
    async def limit_upload(request, call_next):
        if request.method == 'POST' and request.url.path == '/api/songs':
            try:
                length = int(request.headers.get('content-length', '0'))
            except ValueError:
                return JSONResponse(
                    {'detail': 'Content-Lengthが不正です'}, status_code=400)
            if length > MAX_BYTES + 1024 * 1024:
                return JSONResponse({'detail': 'ファイルは100MiB以内にしてください'}, status_code=413)
        return await call_next(request)

    def get_song(song_id: UUID) -> dict:
        try:
            return store.get(str(song_id))
        except KeyError as exc:
            raise HTTPException(404, '音源が見つかりません') from exc

    def require_analysis(song: dict) -> None:
        if song['status'] != 'completed':
            raise HTTPException(409, '解析が完了していません')

    def response(song: dict) -> dict:
        original = json.loads(song['original']) if song['original'] else None
        edited = json.loads(song['edited']) if song['edited'] else None
        return {key: song[key] for key in ('id', 'filename', 'created_at', 'status', 'stage', 'progress', 'error', 'revision')} | {
            'analysis': edited or original, 'original_analysis': original,
            'has_edits': edited is not None,
            'has_tab': song['tab_revision'] == song['revision'] and song['tab_json'] is not None,
        }

    def job(song_id: str, path: Path) -> None:
        try:
            store.progress(song_id, 5, '音声ライブラリを準備しています')
            result = analyzer(path, lambda percent, stage: store.progress(song_id, percent, stage))
            store.complete(song_id, result.to_dict())
        except Exception as exc:
            LOGGER.exception('Analysis failed for %s', song_id)
            from .audio import AudioError
            message = str(exc) if isinstance(exc, AudioError) else '解析中にエラーが発生しました。サーバーのログを確認してください。'
            store.fail(song_id, message)

    @app.get('/api/songs')
    def list_songs():
        return store.list()

    @app.post('/api/songs', status_code=201)
    async def upload(file: Annotated[UploadFile, File()]):
        filename = Path((file.filename or '').replace('\\', '/')).name
        suffix = Path(filename).suffix.lower()
        if suffix not in {'.mp3', '.wav'}:
            await file.close()
            raise HTTPException(422, 'MP3またはWAVファイルを選んでください')
        song_id = str(uuid4())
        path = store.uploads / (song_id + suffix)
        size = 0
        try:
            with path.open('xb') as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, 'ファイルは100MiB以内にしてください')
                    stream.write(chunk)
            if size == 0:
                raise HTTPException(422, '音声ファイルが空です')
            await run_in_threadpool(probe_audio, path)
            store.create(song_id, filename[:255], path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return response(store.get(song_id))

    @app.post('/api/songs/{song_id}/analyze', status_code=202)
    def start_analysis(song_id: UUID):
        song = get_song(song_id)
        try:
            store.queue(str(song_id))
            app.state.executor.submit(job, str(song_id), Path(song['path']))
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            store.fail(str(song_id), '解析ワーカーを開始できませんでした')
            raise HTTPException(503, '解析ワーカーを開始できませんでした') from exc
        return {'id': str(song_id), 'status': 'queued'}

    @app.get('/api/songs/{song_id}/audio')
    def get_audio(song_id: UUID):
        song = get_song(song_id)
        path = Path(song['path'])
        if not path.is_file():
            raise HTTPException(404, '元の音源ファイルが見つかりません')
        return FileResponse(path, media_type='audio/mpeg' if path.suffix == '.mp3' else 'audio/wav')

    def melody_response(song: dict) -> dict:
        result = json.loads(song['melody']) if song['melody'] else None
        if result:
            result['vocals_available'] = bool(result.pop('vocals_path', None))
        return {'status': song['melody_status'], 'progress': song['melody_progress'],
                'error': song['melody_error'],
                'result': result}

    def melody_job(song_id: str, path: Path, options: dict) -> None:
        try:
            store.melody_progress(song_id, 1)
            report = lambda percent, _stage: store.melody_progress(song_id, percent)
            if melody_analyzer:
                result = melody_analyzer(path, report)
            else:
                from .melody import analyze_melody
                result = analyze_melody(path, report, cache_dir=store.root / 'stems', **options)
            store.complete_melody(song_id, result)
        except Exception as exc:
            LOGGER.exception('Melody analysis failed for %s', song_id)
            from .separation import MelodyError
            store.fail_melody(song_id, str(exc)) if isinstance(exc, MelodyError) else store.fail_melody(song_id)

    @app.post('/api/songs/{song_id}/melody', status_code=202)
    def start_melody(song_id: UUID, body: MelodyRequest | None = None):
        song = get_song(song_id)
        options = (body or MelodyRequest()).model_dump()
        if options['end'] is not None and options['end'] <= options['start']:
            raise HTTPException(422, '終了時刻は開始時刻より後にしてください')
        try:
            store.queue_melody(str(song_id))
            app.state.executor.submit(melody_job, str(song_id), Path(song['path']), options)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            store.fail_melody(str(song_id))
            raise HTTPException(503, '解析ワーカーを開始できませんでした') from exc
        return {'status': 'queued'}

    @app.get('/api/songs/{song_id}/melody')
    def get_melody(song_id: UUID):
        return melody_response(get_song(song_id))

    @app.get('/api/songs/{song_id}/vocals')
    def get_vocals(song_id: UUID):
        song = get_song(song_id)
        result = json.loads(song['melody']) if song['melody'] else {}
        path = Path(result.get('vocals_path') or '')
        if not path.is_file():
            raise HTTPException(404, '分離した歌声がありません')
        return FileResponse(path, media_type='audio/wav')

    @app.post('/api/songs/{song_id}/score')
    def update_score(song_id: UUID, body: ScoreRequest):
        song = get_song(song_id)
        if song['melody_status'] != 'completed' or not song['melody']:
            raise HTTPException(409, '先にメロディを解析してください')
        from .notation import make_score
        result = json.loads(song['melody'])
        result['bpm'] = body.bpm
        result['score'] = make_score(result['notes'], body.bpm, result.get('region_start', 0), result.get('region_end', result['duration']))
        try:
            store.update_score(str(song_id), song['melody'], result)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        return melody_response(get_song(song_id))

    @app.get('/api/songs/{song_id}/score')
    def download_score(song_id: UUID, format: Literal['abc','musicxml'] = 'musicxml'):
        song = get_song(song_id)
        score = json.loads(song['melody']).get('score') if song['melody'] else None
        if not score:
            raise HTTPException(404, '五線譜は未生成です。BPMを指定してリズムを整理してください')
        return Response(score[format], media_type='application/vnd.recordare.musicxml+xml' if format == 'musicxml' else 'text/plain',
                        headers={'Content-Disposition': f'attachment; filename="melody.{format}"'})

    @app.get('/api/songs/{song_id}/analysis')
    def get_analysis(song_id: UUID):
        return response(get_song(song_id))

    @app.put('/api/songs/{song_id}/chords')
    def edit_chords(song_id: UUID, body: ChordUpdate):
        song = get_song(song_id)
        require_analysis(song)
        try:
            result = ChordEditor().update(analysis_from_dict(json.loads(song['original'])), body.chords)
            store.edit(str(song_id), body.revision, result.to_dict())
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return response(get_song(song_id))

    @app.post('/api/songs/{song_id}/tabs', status_code=201)
    def generate_tab(song_id: UUID, body: TabRequest):
        song = get_song(song_id)
        require_analysis(song)
        if song['revision'] != body.revision:
            raise HTTPException(409, '最新のコード進行を読み込んでください')
        try:
            result = analysis_from_dict(json.loads(song['edited'] or song['original']))
            tab = GuitarTabGenerator().generate(result, bpm=body.bpm)
            store.save_tab(str(song_id), body.revision, tab.to_dict(), tab.to_text())
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except TabError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {'revision': body.revision, 'tab': tab.to_dict(), 'text': tab.to_text()}

    @app.get('/api/songs/{song_id}/tabs')
    def get_tab(song_id: UUID):
        song = get_song(song_id)
        require_analysis(song)
        if song['tab_json'] is None or song['tab_revision'] != song['revision']:
            raise HTTPException(404, 'TABは未生成です。現在のコード進行から生成してください')
        return {'revision': song['tab_revision'], 'tab': json.loads(song['tab_json']), 'text': song['tab_text']}

    # ビルド済みUIがある場合は同一オリジンで配信。開発時はViteの/apiプロキシを使う。
    dist = Path(__file__).resolve().parents[3] / 'frontend' / 'dist'
    if dist.is_dir():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

        @app.get('/', include_in_schema=False)
        def index():
            return FileResponse(dist / 'index.html')

    return app


app = create_app()
