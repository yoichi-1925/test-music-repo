"""SQLiteの各更新を短いトランザクションで実行する。"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Iterator


class ConflictError(ValueError):
    pass


class SongStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir(exist_ok=True)
        self.database = self.root / "songs.sqlite3"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS songs (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                status TEXT NOT NULL DEFAULT 'uploaded', stage TEXT NOT NULL DEFAULT 'アップロード完了',
                progress INTEGER NOT NULL DEFAULT 0, error TEXT,
                original TEXT, edited TEXT, revision INTEGER NOT NULL DEFAULT 0,
                tab_json TEXT, tab_text TEXT, tab_revision INTEGER
            )""")
            columns = {row['name'] for row in db.execute('PRAGMA table_info(songs)')}
            for name, definition in {
                'melody': 'TEXT', 'melody_status': "TEXT NOT NULL DEFAULT 'idle'",
                'melody_progress': 'INTEGER NOT NULL DEFAULT 0', 'melody_error': 'TEXT',
            }.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE songs ADD COLUMN {name} {definition}')
            db.execute("""UPDATE songs SET melody_status='failed',
                melody_error='サーバーが再起動しました。メロディ推定を再実行してください。'
                WHERE melody_status IN ('queued','analyzing')""")
            # 前回の終了時に中断したジョブを、永久に解析中として残さない。
            db.execute("""UPDATE songs SET status='failed', stage='解析が中断されました',
                error='サーバーが再起動しました。解析を再実行してください。'
                WHERE status IN ('queued','analyzing')""")

    def create(self, song_id: str, filename: str, path: Path) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO songs(id,filename,path) VALUES(?,?,?)", (song_id, filename, str(path)))

    def get(self, song_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone()
        if row is None:
            raise KeyError(song_id)
        return dict(row)

    def list(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT id,filename,created_at,status,progress,stage,revision,melody_status,melody_progress
                FROM songs ORDER BY created_at DESC, id DESC""").fetchall()
        return [dict(row) for row in rows]

    def queue(self, song_id: str) -> None:
        with self.connect() as db:
            cursor = db.execute("""UPDATE songs SET status='queued', stage='解析待ち', progress=0,error=NULL
                WHERE id=? AND status IN ('uploaded','failed')""", (song_id,))
            if cursor.rowcount != 1:
                raise ConflictError('この音源は解析済み、または解析中です')

    def progress(self, song_id: str, progress: int, stage: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE songs SET status='analyzing',progress=?,stage=? WHERE id=?", (progress, stage, song_id))

    def complete(self, song_id: str, result: dict) -> None:
        with self.connect() as db:
            db.execute("""UPDATE songs SET status='completed',progress=100,stage='解析完了',
                original=?,edited=NULL,revision=1,error=NULL,tab_json=NULL,tab_text=NULL,tab_revision=NULL WHERE id=?""",
                       (json.dumps(result, allow_nan=False), song_id))

    def fail(self, song_id: str, error: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE songs SET status='failed',stage='解析に失敗しました',error=? WHERE id=?", (error, song_id))

    def edit(self, song_id: str, revision: int, result: dict) -> None:
        with self.connect() as db:
            cursor = db.execute("""UPDATE songs SET edited=?,revision=revision+1,
                tab_json=NULL,tab_text=NULL,tab_revision=NULL
                WHERE id=? AND status='completed' AND revision=?""",
                (json.dumps(result, allow_nan=False), song_id, revision))
            if cursor.rowcount != 1:
                raise ConflictError('別の画面で更新されています。最新の結果を読み込んでください')

    def save_tab(self, song_id: str, revision: int, tab: dict, text: str) -> None:
        with self.connect() as db:
            cursor = db.execute("""UPDATE songs SET tab_json=?,tab_text=?,tab_revision=?
                WHERE id=? AND status='completed' AND revision=?""",
                (json.dumps(tab, allow_nan=False), text, revision, song_id, revision))
            if cursor.rowcount != 1:
                raise ConflictError('コードが更新されました。TABを再生成してください')

    def queue_melody(self, song_id: str) -> None:
        with self.connect() as db:
            cursor = db.execute("""UPDATE songs SET melody_status='queued',melody_progress=0,melody_error=NULL
                WHERE id=? AND status NOT IN ('queued','analyzing') AND melody_status NOT IN ('queued','analyzing')""", (song_id,))
            if cursor.rowcount != 1:
                raise ConflictError('メロディ推定中、または別の解析を実行中です')

    def melody_progress(self, song_id: str, percent: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE songs SET melody_status='analyzing',melody_progress=? WHERE id=?", (percent, song_id))

    def complete_melody(self, song_id: str, result: dict) -> None:
        with self.connect() as db:
            db.execute("""UPDATE songs SET melody=?,melody_status='completed',melody_progress=100,
                melody_error=NULL WHERE id=?""", (json.dumps(result, allow_nan=False), song_id))

    def fail_melody(self, song_id: str, message: str = 'メロディを推定できませんでした。サーバーログを確認し再実行してください。') -> None:
        with self.connect() as db:
            db.execute("""UPDATE songs SET melody_status='failed',
                melody_error=? WHERE id=?""", (message, song_id))

    def update_score(self, song_id: str, previous: str, result: dict) -> None:
        with self.connect() as db:
            cursor = db.execute("UPDATE songs SET melody=? WHERE id=? AND melody=? AND melody_status='completed'",
                                (json.dumps(result, allow_nan=False), song_id, previous))
            if cursor.rowcount != 1:
                raise ConflictError('メロディが更新されました。最新の結果を読み込んでください')
