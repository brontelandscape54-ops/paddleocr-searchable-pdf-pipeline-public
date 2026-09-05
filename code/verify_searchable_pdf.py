#!/usr/bin/env python3
from __future__ import annotations

"""結合PDFのページ数と抽出可能文字数を検査する。

ファイルが生成されたという事実だけで成功とみなさず、検索可能なテキスト層が
実際に残っていることまで機械的に確認する。
"""

import argparse
from pathlib import Path

from pypdf import PdfReader


def main() -> None:
    parser = argparse.ArgumentParser(description="検索可能PDFのテキスト層を検査する")
    parser.add_argument("pdf_path")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).expanduser().resolve()
    reader = PdfReader(str(pdf_path))
    texts: list[str] = []

    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        compact = "".join(text.split())
        texts.append(text)
        print(f"[OK] page {index}: extracted chars={len(compact)}", flush=True)

    compact_all = "".join("\n".join(texts).split())
    print(f"[OK] pages: {len(reader.pages)}", flush=True)
    print(f"[OK] total extracted chars: {len(compact_all)}", flush=True)
    print(f"[OK] sample: {compact_all[:240]!r}", flush=True)
    if not compact_all:
        raise SystemExit("[ERROR] テキストレイヤーが空です")


if __name__ == "__main__":
    main()
