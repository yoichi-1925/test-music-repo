# Melody Room — 音源の主旋律を五線譜へ

現在の優先機能は、歌声のあるMP3/WAVを**ボーカル分離 → 音高推定 → 五線譜**へ変換するローカルWebアプリです。
TAB生成から主旋律の採譜へ方針を変更しました。旧コード解析・TABのデータ、CLI、APIは保持しています。
要件の初期資料は[project.md](project.md)です。現在の画面は主旋律の確認に集中しています。

## 環境構築

macOS、Python 3.12、Node.js 22.12以上、FFmpegが必要です。音源はPC内で処理し、外部に送信しません。
学習済みモデル・依存パッケージの取得時のみネット接続が必要です。

```sh
brew install ffmpeg
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -e '.[test]'
npm --prefix frontend ci
```

### ボーカル分離環境

Torchと既存アプリのNumPy依存を分けるため、リポジトリ直下に専用環境を作ります。
このPC（Intel Mac、Python 3.12）ではTorch 2.2.2を使用します。

```sh
python3.12 -m venv .venv-vocals
.venv-vocals/bin/python -m pip install -r requirements-vocals.txt
```

Demucsの初回実行時に約80MBのモデルを取得します。CREPEの音高推定モデルはtorchcrepeパッケージに含まれます。
別の場所へ環境を作った場合は`MUSIC_VOCALS_PYTHON=/absolute/path/bin/python`をサーバー起動時に指定します。
モデル・分離音・推定結果は`data/`内へキャッシュし、同じ内容のファイル・区間の再解析では再利用します。全曲の分離結果がある場合、短い区間はそこから切り出します。
CPUでの処理には数分かかることがあります。まず歌声のある20〜30秒を指定してください。

## 起動

リポジトリ直下で実行します。

```sh
npm --prefix frontend run build
.venv312/bin/python -m uvicorn music_analyzer.api:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

[http://127.0.0.1:8000](http://127.0.0.1:8000)を開きます。画面変更後は再ビルド、Python変更後はサーバー再起動が必要です。
Ctrl+Cで停止します。既存サーバーが起動中なら、そのターミナルで停止してから起動してください。
開発時はAPIを`--reload`付きで起動し、別ターミナルで`npm --prefix frontend run dev`を実行します。
Viteの[http://127.0.0.1:5173](http://127.0.0.1:5173)はAPIを8000番へ転送します。

## 操作

1. MP3/WAVを追加、または保存済み音源を選びます（最大100MiB・10分）。
2. 歌声がある区間の開始・終了秒を指定します。歌＋伴奏なら「ボーカル分離」、独奏なら「独奏」を選びます。
3. 「主旋律を解析」を押します。コード解析の実行は不要です。
4. 原音と分離した歌声を切り替え、五線譜と比較します。0.5/0.75倍の再生、音符クリックによるシーク、自動追従に対応します。
5. BPMが半分・倍などにずれていれば、BPMを入力して「BPMで譜面を再整理」を押します。音高を再推定せずリズムだけ整理します。
6. MusicXMLを保存できます。楽譜編集ソフトへ読み込んで修正できます。

緑の音符が再生位置、茶色の音符が低信頼の推定です。分離した歌声は指定区間のみですが、時刻は原音に合わせて表示します。
再生するのは原音または歌声です。譜面を合成して鳴らす機能はありません。

## 推定方式と現在の制約

歌＋伴奏では[Demucs htdemucs](https://github.com/facebookresearch/demucs)で歌声を分離し、
[torchcrepe](https://github.com/maxrmorrison/torchcrepe)のCREPE fullモデル・Viterbi復号で約10msごとに音高を推定します。
無音・低信頼フレームを除外し、短い音高の揺れを平滑化して半音単位の音符へ整理します。
独奏モードでは[librosa pYIN](https://librosa.org/doc/0.11.0/generated/librosa.pyin.html)を使用します。
五線譜はABC形式をabcjsで描画し、同じデータからMusicXMLを生成します。

- 完成した歌入り音源の**主に歌声の旋律**を対象とします。ハモリと主旋律の分離、楽器の主旋律の選別は未対応です。
- 自動採譜は下書きです。実曲の正解譜との照合による精度評価は未実施です。モデル変更だけで正確さを保証しません。
- 4/4、固定BPM、16分音符の格子を使用します。小節頭は解析区間の先頭を仮定します。
- 休符・付点・タイを表示します。最後の小節の余りは休符で埋めます。三連符・変拍子・テンポ変化・弱起の自動判定は未対応です。
- 調号は自動推定せず、シャープとナチュラルで実音を表示します。異名同音の綴りは簡易的です。
- ビブラート・しゃくり・ラップ・残った伴奏・ハモリで誤推定があります。同音の再発音が一音に結合する場合があります。
- 信頼度は音高の周期性などを示すモデル指標で、正解率ではありません。短すぎる音符は格子化時に省略されます。
- 画面での音符の個別編集、MIDI/PDF出力、YouTube URL入力は未実装です。

## 保存・API

音源・SQLite・分離音・モデルは`data/`に保存します（Git管理対象外）。`MUSIC_DATA_DIR`で保存先を変更できます。
元の解析・コード修正・TABは保持し、メロディ結果は別に保存します。
旧形式のメロディ結果は、再解析すると現在の五線譜形式になります。
再起動で中断したジョブは失敗状態に戻り、再実行できます。終了時は処理完了を待ちます。
単一プロセス・ローカル単一ユーザー向けです。複数Uvicorn workerには対応していません。

| メソッド | パス | 用途 |
| --- | --- | --- |
| GET/POST | `/api/songs` | 一覧／multipartの`file`でアップロード |
| GET | `/api/songs/{id}/analysis` | 音源情報・旧コード解析結果 |
| GET | `/api/songs/{id}/audio` | 元音源（Range対応） |
| POST | `/api/songs/{id}/melody` | 主旋律解析を開始（202） |
| GET | `/api/songs/{id}/melody` | 状態・進捗・音符・五線譜 |
| GET | `/api/songs/{id}/vocals` | 指定区間の分離した歌声（Range対応） |
| POST | `/api/songs/{id}/score` | 指定BPMでリズムを再整理 |
| GET | `/api/songs/{id}/score?format=musicxml` | 五線譜をダウンロード（`abc`も可） |

解析リクエストの例:

```json
{"source":"mix","start":42,"end":62,"bpm":null}
```

`source`は`mix`または`solo`、BPMは20〜300。終了秒は実際の末尾へ制限します。
BPM再整理の例は`{"bpm": 120}`です。音符の`start`/`duration`は秒、`midi`は実音のMIDI番号。
結果には`region_start/end`、`bpm`、`estimated_bpm`、`vocals_available`、`score`を含みます。
分離ファイルの内部パスはAPIへ返しません。
主なエラーは404（未生成）、409（処理中・更新競合）、413（サイズ超過）、422（入力不正）です。
開始後の処理失敗は`melody_status`相当の`status: failed`と`error`で返します。
APIの詳細は[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

旧API `/analyze`、`/chords`、`/tabs` は引き続き利用可能です。CLIも保持しています。

```sh
PYTHONPATH=backend/src .venv312/bin/python -m music_analyzer.cli /path/to/song.mp3
PYTHONPATH=backend/src .venv312/bin/python -m music_analyzer.tab_cli examples/progression.json
```

## テスト

```sh
PYTHONPATH=backend/src .venv312/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
.venv312/bin/python -m pip check
.venv-vocals/bin/python -m pip check
```

合成音源の音高・休符・境界、五線譜の小節長・タイ・音価・MusicXML、APIの保存・再整理・配信・競合、
既存コード/TAB処理を検証します。通常のテストは大型モデルをダウンロードしません。
このPCではeditableインストール用`.pth`の隠し属性による読み込み問題があるため、テストでは`PYTHONPATH`、起動では`--app-dir`を明示しています。

### 今回の実音源の試作

提供された音源の全曲ボーカル分離を実行し、42〜50秒の主旋律20音を試作として保存しました。
`data/review-paradigm/melody-42-50.musicxml`、同名のJSON/ABCがあります。
既存の同じ音源にもこの区間の結果を保存しました。以前のメロディJSONは`previous-melody.json`に退避しています。
テンポ推定95.7 BPMでは短い音が5音省略されたため、試作譜面は倍テンポの191.4 BPMを仮指定しています（省略0音）。
これは正しい拍・小節位置を確定したことを意味しません。全曲の採譜はまだ行っていません。

バックエンド全体138件、およびその後追加した最短音価の丸め境界の回帰テストが通過しました。
フロントエンドの時刻判定4件、型チェック・本番ビルド、両Python環境の依存関係チェックも成功しています。
実際のCREPEワーカーを用いた合成C4→E4→G4と前後の休符の復元を確認しました。
ブラウザで実音源の解析・五線譜・音符クリック・音源切替・低速再生・BPM再整理・保存後の再読込・MusicXML保存を確認しています。
ビルドにはabcjsのチャンクサイズ警告、Pythonテストには依存ライブラリの非推奨警告が残っています。
