# test-music-repo — 音楽解析MVP

MP3/WAVからBPM・拍位置・キー・コード進行を推定するローカルCLIです。
現在は **Phase 1のみ実装**しています。要件の原文は [project.md](project.md) です。

## 環境構築（macOS）

Python 3.10〜3.13とFFmpegが必要です（検証環境: Python 3.12.3）。有料APIや外部への音源送信は使用しません。

```sh
brew install ffmpeg
python3.12 -m venv .venv312
source .venv312/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[test]'
```

この環境の既存Python 3.10.4は標準モジュール`_lzma`が欠けており、librosaを読み込めませんでした。
以下で確認し、エラーになる場合は完全なPython（例: `brew install python@3.12`）を使用してください。

```sh
python3.12 -c "import lzma"
```

NumbaはPython 3.10/macOS向けのバイナリがある0.61系、NumPyはその互換範囲に制限しています。
初回の解析・テストはNumbaのコンパイルに時間がかかります。

## 起動・解析

Webサーバーはまだありません。以下のCLIを起動してください。

```sh
source .venv312/bin/activate
music-analyze /path/to/song.mp3
music-analyze /path/to/song.wav --output analysis.json
# モジュールからの起動も可能
python -m music_analyzer.cli /path/to/song.wav
```

標準出力、または指定ファイルへJSONを出力します。エラーは標準エラーに表示し終了コード1を返します。
既存の出力ファイルは上書きしません。入力音源は変更せず、一時変換ファイルは終了時に削除します。

結果例（構造の説明用）:

```json
{
  "duration": 2.0,
  "bpm": null,
  "beats": [],
  "key": null,
  "key_confidence": 0.0,
  "chords": [
    {"start": 0.0, "duration": 2.0, "chord": "C", "confidence": 0.94, "source": "analysis"}
  ],
  "time_signature": "4/4",
  "schema_version": 1
}
```

時間の単位は秒です。コード名はシャープ表記の12音×major/minor（C、C#、…、Bm）。
`chord: null`は無音・低信頼区間、`bpm: null`と空の拍リストは拍を推定できない場合です。
コードconfidenceはテンプレートとのコサイン類似度（確率ではありません）。
キーは長調・短調の音高プロファイル照合による推定で、`key_confidence`は上位2候補の相関差です。
差が小さい場合はキーもnullになります。

## 構成と設計

```text
backend/
  src/music_analyzer/
    audio.py       AudioProcessor: サイズ検証、FFmpeg復号、モノラル22,050Hz化
    beats.py       BeatDetector: BPM・拍位置の推定
    chords.py      ChordDetector: クロマ、和音照合、平滑化、キー推定
    models.py      楽器に依存しない解析結果とJSON変換
    pipeline.py    解析モジュールの組み合わせ
    cli.py         CLIとエラー表示
  tests/           合成音源・復号・CLIのテスト
pyproject.toml     依存関係、CLI登録、pytest設定
```

コード推定は[librosaのchroma_stft](https://librosa.org/doc/0.11.0/generated/librosa.feature.chroma_stft.html)で
算出したクロマを拍区間ごとに平均し、24種類の三和音テンプレートと照合します。
Viterbi法による切替コストで時間方向を平滑化し、類似度と他候補との差の両方で採用を判断します。
同じコードが続く区間は結合します。拍が取れない音源では0.5秒区間を使用します。

### 現時点の制約

- 入力は100MiB以下・10分以内のMP3/WAV。拡張子だけでなくFFmpegで復号を確認。
- 基本4/4を仮定。拍子・小節先頭の自動検出は行いません。
- BPMの倍テンポ・半テンポ、転調、複雑な和音、ボーカル・打楽器混在で誤推定があり得ます。
- 短い音源、無拍音源、単一コードではBPMやキーが不明になる場合があります。
- 信頼度しきい値は合成音源での基本動作向けで、実楽曲で校正した確率ではありません。
- 原音の長期保存・アップロード・編集保存・SQLite・Web API/UIはPhase 3で実装予定です。

### Phase 2以降の設計（未実装）

Phase 2では`GuitarTabGenerator`とコードフォーム辞書を追加し、共通の`ChordSegment`を入力にします。
実音コードと押さえ方（フォーム・カポ）を別のデータとして管理し、標準チューニング・毎小節4回の
ダウンストロークをテキストTABへ変換する予定です。

Phase 3では`backend/src`にFastAPIルーター・SQLite保存層・`ChordEditor`を追加し、
`frontend/`にReact + TypeScript + Viteを配置します。元の解析結果と手動修正を別に保存し、
修正で既存TABを無効化します。バックグラウンド解析の状態はSQLiteに保存し、画面からポーリングします。
予定APIはPOST songs、POST analyze、GET analysis、PUT chords、POST/GET tabs（`/api/songs/{id}/…`）です。
MIDI・ピアノ譜・MusicXML・PDF・YouTube入力などは現在の対象外です。

## テスト

```sh
source .venv312/bin/activate
pytest -q
```

FFmpegを含むローカル結合テストを実行します。外部音源のダウンロードは不要です。
24種類の合成三和音、C–Am–F–G進行、120BPMクリック、無音・曖昧な音源、
WAV/MP3復号、サイズ・長さ制限、不正入力、JSON変換、CLI出力と上書き防止を検証します。
実楽曲での精度は保証しません。APIとTABのテストは該当フェーズで追加します。

### 検証結果（2026-10-17）

Python 3.12.3 / librosa 0.11.0 / NumPy 2.2.6 / Numba 0.61.2で、
`python -m pytest -q -o faulthandler_timeout=30`を実行し **40 passed**（131.04秒）。
初回ライブラリ読み込みが30秒を超えたため診断用スタック出力がありましたが、全テストは完了しました。
`pip check`とCLIの`--help`も成功しています。
依存ライブラリaudioreadによる`aifc`・`audioop`・`sunau`の非推奨警告が3件あります。
