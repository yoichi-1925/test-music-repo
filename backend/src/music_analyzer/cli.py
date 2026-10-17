import argparse
import json
from pathlib import Path
import sys
from .audio import AudioError
from .pipeline import analyze


def main() -> int:
    parser = argparse.ArgumentParser(description="MP3/WAVからBPM・拍・キー・コードを推定")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", "-o", type=Path, help="JSON保存先（省略時は標準出力）")
    args = parser.parse_args()
    try:
        if args.output and args.output.resolve() == args.audio.resolve():
            raise AudioError("出力先に入力ファイルと同じパスは指定できません")
        result = json.dumps(analyze(args.audio).to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            # 既存の解析結果や他のファイルを誤って上書きしない。
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(result + "\n")
        else:
            print(result)
    except (AudioError, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
