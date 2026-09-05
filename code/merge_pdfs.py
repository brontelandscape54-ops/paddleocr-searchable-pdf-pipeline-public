#!/usr/bin/env python3
from __future__ import annotations

"""ページ別検索可能PDFをページ順に結合する。

OCRテキスト層を壊さないことを優先し、画像の再描画や再OCRは行わない。
"""

import argparse
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def main() -> None:
    parser = argparse.ArgumentParser(description="ページ別検索可能PDFを結合する")
    parser.add_argument("pdf_dir")
    parser.add_argument("output_pdf")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir).expanduser().resolve()
    output_pdf = Path(args.output_pdf).expanduser().resolve()
    pdfs = sorted(pdf_dir.glob("page_*.pdf"), key=natural_key)
    if not pdfs:
        raise SystemExit(f"結合対象PDFがありません: {pdf_dir}")

    writer = PdfWriter()
    for pdf_path in pdfs:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            writer.add_page(page)
        print(f"[ADD] {pdf_path.name}", flush=True)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as file:
        writer.write(file)

    print(f"[OK] merged pages: {len(writer.pages)}", flush=True)
    print(f"[OK] output: {output_pdf}", flush=True)


if __name__ == "__main__":
    main()
