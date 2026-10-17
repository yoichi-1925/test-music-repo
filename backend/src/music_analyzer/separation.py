"""歌声分離は、既存のNumPy環境と分けたDemucsワーカーで実行する。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


class MelodyError(ValueError):
    pass


def cache_key(source: Path, start: float, end: float) -> str:
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return hashlib.sha256(f'{digest.hexdigest()}:{start:.4f}:{end:.4f}:htdemucs-v2'.encode()).hexdigest()[:24]


class VocalSeparator:
    def __init__(self, cache: Path):
        self.cache = cache.resolve()

    def separate(self, source: Path, start: float, end: float, full_duration: float | None = None) -> Path:
        root = Path(__file__).resolve().parents[3]
        python = Path(os.environ.get('MUSIC_VOCALS_PYTHON', str(root / '.venv-vocals/bin/python')))
        if not python.is_file():
            raise MelodyError('歌声分離用の環境がありません。READMEの「ボーカル分離環境」を設定してください。')
        key = cache_key(source, start, end)
        work = self.cache / key
        vocals = work / 'separated/htdemucs/mix/vocals.wav'
        done = work / 'complete.json'
        if done.is_file() and vocals.is_file() and vocals.stat().st_size > 44:
            return vocals
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            raise MelodyError('FFmpegが必要です')
        work.mkdir(parents=True, exist_ok=True)
        try:
            full = self.cache / cache_key(source, 0, full_duration) if full_duration else None
            full_vocals = full / 'separated/htdemucs/mix/vocals.wav' if full else None
            if full and full != work and (full / 'complete.json').is_file() and full_vocals.is_file():
                vocals.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-ss', str(start), '-i', str(full_vocals),
                                '-t', str(end - start), '-c:a', 'pcm_s16le', str(vocals)],
                               check=True, capture_output=True, timeout=120)
                done.write_text(json.dumps({'model': 'htdemucs', 'start': start, 'end': end}), encoding='utf-8')
                return vocals
            subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-ss', str(start), '-i', str(source.resolve()),
                            '-t', str(end - start), '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le', str(work / 'mix.wav')],
                           check=True, capture_output=True, timeout=120)
            environment = {**os.environ, 'TORCH_HOME': str(self.cache.parent / 'models'),
                           'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2'}
            # ログをメモリに溜めず、失敗時にローカルで確認できる形で保存する。
            with (work / 'separation.log').open('w') as log:
                subprocess.run([str(python), '-m', 'demucs.separate', '-n', 'htdemucs', '--two-stems', 'vocals',
                                '--device', 'cpu', '--shifts', '0', '--overlap', '0.25', '--segment', '7',
                                '--out', str(work / 'separated'), str(work / 'mix.wav')],
                               env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)
            if not vocals.is_file() or vocals.stat().st_size <= 44:
                raise MelodyError('歌声分離結果が見つかりません')
            done.write_text(json.dumps({'model': 'htdemucs', 'start': start, 'end': end}), encoding='utf-8')
        except (subprocess.SubprocessError, OSError) as exc:
            raise MelodyError('歌声分離に失敗しました。ボーカル分離環境・モデルの取得状況とseparation.logを確認してください。') from exc
        return vocals
