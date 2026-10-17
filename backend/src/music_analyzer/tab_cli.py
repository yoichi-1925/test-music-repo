"""保存した解析JSONからTABを生成するCLI。音声ライブラリは読み込まない。"""
import argparse
import json
from pathlib import Path
import sys

from .models import AnalysisResult, ChordSegment
from .tabs import GuitarTabGenerator, TabError


def load_analysis(path: Path) -> AnalysisResult:
    if path.stat().st_size > 5 * 1024 * 1024:
        raise TabError("解析JSONは5MiB以内にしてください")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise TabError("schema_version=1の解析JSONが必要です")
    if not isinstance(data.get("chords"), list) or not isinstance(data.get("beats"), list):
        raise TabError("chordsとbeatsには配列が必要です")
    try:
        chords = [ChordSegment(**item) for item in data["chords"]]
        if any(c.chord is not None and not isinstance(c.chord, str) for c in chords):
            raise TabError("コード名には文字列またはnullが必要です")
        return AnalysisResult(
            duration=data["duration"], bpm=data["bpm"], beats=data["beats"],
            key=data.get("key"), key_confidence=data.get("key_confidence", 0),
            chords=chords, time_signature=data.get("time_signature", "4/4"),
        )
    except (KeyError, TypeError) as exc:
        raise TabError("解析JSONのフィールドが不足しているか、形式が不正です") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="解析JSONからギター伴奏TABを生成")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--bpm", type=float, help="指定時は0秒から固定テンポで生成")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        tab = GuitarTabGenerator().generate(load_analysis(args.analysis), bpm=args.bpm)
        output = (tab.to_text() if args.format == "text" else
                  json.dumps(tab.to_dict(), ensure_ascii=False, indent=2, allow_nan=False))
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(output + "\n")
        else:
            print(output)
    except (OSError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
