# test-music-repo — 音楽解析MVP

MP3/WAVからBPM・拍位置・キー・コード進行を推定するローカルCLIです。
現在は **Phase 1・2を実装**しています。要件の原文は [project.md](project.md) です。

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
    cli.py         音声解析CLIとエラー表示
    guitar.py      24種類のギターコードフォーム辞書
    tabs.py        GuitarTabGeneratorとテキスト/JSON出力
    tab_cli.py     保存した解析JSONからTABを生成するCLI
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

### Phase 2：ギター伴奏TAB

```sh
source .venv312/bin/activate
# 既存のPhase 1環境では、新コマンドを登録するため再インストール
python -m pip install -e '.[test]'
music-tab examples/progression.json
music-tab analysis.json --output guitar-tab.txt
music-tab analysis.json --format json --output guitar-tab.json
# BPMが不明な場合や固定テンポを指定する場合
music-tab analysis.json --bpm 120
# 再インストールせずモジュールから実行することも可能
python -m music_analyzer.tab_cli examples/progression.json
```

`examples/progression.json`はC–Am–F–Gを各1小節、120BPMで鳴らす手入力サンプルです。
`music-analyze`で出力したJSONもそのまま入力できます。テキストTABは高音e弦から低音E弦の順で、
コード名・拍番号・秒数・弦ごとのフレット番号を小節単位に表示します。
`v`がダウンストローク、`-`は発音しない弦です。ミュート弦に打音を指示しません。
不明なコードや区間の隙間は`N.C.`として全弦を休みます。未対応のコード名はエラーにします。

- 標準チューニング・カポ0・4/4拍子。完全な小節では1拍に1回、計4回のダウンストローク。
- 2個以上の検出拍がある場合はその位置を使用し、末尾のみ最後の拍間隔で補完します。
  最初の検出拍より前にはストロークを追加しません。
- 検出拍が不足する場合はBPMで0秒から生成します。拍もBPMもない場合は`--bpm`が必要です。
  `--bpm`を指定すると検出拍の代わりに0秒からの固定テンポを使います（20〜300BPM）。
- 小節先頭は推定せず、生成の最初の拍を1小節目の1拍目と仮定します。
  末尾の不完全な小節は音源の長さで打ち切ります。曲の終了時刻ちょうどには発音しません。
- コード変更は各ストローク時点のコードを反映します。拍の途中の変更は次の拍から反映します。
- 開放コードを優先しますが、全調に対応するためFやC#mなどにはバレーコードを使います。
- JSONでは実音コード`sounding_chord`と`form`（名前・6弦分のフレット）を分離し、
  将来のカポ対応でそれぞれを管理できる構造にしています。フレット配列は低音E→高音e、nullはミュートです。
- 出力ファイルは上書きしません。JSONのコード名を修正して再実行すると修正内容で再生成します。
  Web上での編集・修正履歴保存・カポ提案は未実装です。

### Phase 3の設計（未実装）

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
TABでは24種類のフォームの構成音、拍・小節の割り当て、休符、ミュート弦、
コード修正後の再生成、不正JSON、CLIのテキスト/JSON出力も検証します。
実楽曲での精度は保証しません。APIテストはPhase 3で追加します。

### 検証結果（2026-10-17）

Python 3.12.3 / librosa 0.11.0 / NumPy 2.2.6 / Numba 0.61.2で、
`python -m pytest -q -o faulthandler_timeout=30`を実行し **40 passed**（131.04秒）。
初回ライブラリ読み込みが30秒を超えたため診断用スタック出力がありましたが、全テストは完了しました。
`pip check`とCLIの`--help`も成功しています。
依存ライブラリaudioreadによる`aifc`・`audioop`・`sunau`の非推奨警告が3件あります。

### Phase 2の検証結果

既存の音声解析を含む全体テストは **88 passed**（83.93秒、従来と同じ依存ライブラリの警告3件）。
その後、300BPM付近の浮動小数点誤差と拍途中のコード変更に対するテストを追加し、
TAB関連を再検証して **49 passed**（3.64秒）を確認しました。現在のテスト総数は89件です。
`music-tab examples/progression.json`で生成したサンプル出力は
[examples/progression.tab.txt](examples/progression.tab.txt)に保存しています。
