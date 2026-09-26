#!/usr/bin/env python3
from __future__ import annotations

"""Ghostscriptで検索可能PDFの軽量版を作り、テキスト層も検証する。

通常版PDFは常に残す。圧縮は補助工程だが、ファイルが生成されたことだけでは
成功とみなさない。圧縮前後の抽出文字数を比較し、Unicodeテキストが失われた
圧縮版を利用者へ残さない。
"""

import argparse
import shutil
import subprocess
from pathlib import Path

from pypdf import PdfReader


def find_ghostscript() -> str | None:
    """Locate a console Ghostscript executable on macOS/Linux or Windows.

    Keep the historical 'gs' command as the first choice; Windows releases
    typically provide gswin64c.exe or gswin32c.exe instead.
    """
    for name in ("gs", "gswin64c.exe", "gswin32c.exe"):
        executable = shutil.which(name)
        if executable is not None:
            return executable
    return None


def extracted_character_count(path: Path) -> int:
    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return len("".join(text.split()))


def main() -> None:
    parser = argparse.ArgumentParser(description="検索可能PDFを150dpi目安で圧縮する")
    parser.add_argument("input_pdf")
    parser.add_argument("output_pdf")
    parser.add_argument(
        "--require-ghostscript",
        action="store_true",
        help="Fail instead of skipping when Ghostscript is unavailable",
    )
    parser.add_argument(
        "--minimum-text-ratio",
        type=float,
        default=0.90,
        help="圧縮前に対する抽出文字数の最低比率。既定0.90",
    )
    args = parser.parse_args()

    source = Path(args.input_pdf).expanduser().resolve()
    output = Path(args.output_pdf).expanduser().resolve()
    ghostscript = find_ghostscript()

    if not source.is_file():
        raise SystemExit(f"入力PDFがありません: {source}")
    if not 0.0 <= args.minimum_text_ratio <= 1.0:
        raise SystemExit("--minimum-text-ratio は0から1で指定してください")
    if ghostscript is None:
        if args.require_ghostscript:
            raise SystemExit(
                "[ERROR] 150dpi版PDFを要求しましたが、"
                "Ghostscriptが見つかりません"
            )
        print("[SKIP] Ghostscriptがないため圧縮版を生成しません", flush=True)
        return

    source_characters = extracted_character_count(source)
    if source_characters == 0:
        raise SystemExit("[ERROR] 圧縮元PDFのテキストレイヤーが空です")

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ghostscript,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.6",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        "-dAutoRotatePages=/None",
        "-dDetectDuplicateImages=true",
        "-dCompressPages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dAutoFilterColorImages=false",
        "-dColorImageFilter=/DCTEncode",
        "-dDownsampleColorImages=true",
        "-dColorImageResolution=150",
        "-dColorImageDownsampleType=/Bicubic",
        "-dAutoFilterGrayImages=false",
        "-dGrayImageFilter=/DCTEncode",
        "-dDownsampleGrayImages=true",
        "-dGrayImageResolution=150",
        "-dGrayImageDownsampleType=/Bicubic",
        "-dDownsampleMonoImages=true",
        "-dMonoImageResolution=300",
        f"-sOutputFile={output}",
        str(source),
    ]
    subprocess.run(command, check=True)

    output_characters = extracted_character_count(output)
    ratio = output_characters / source_characters
    print(f"[CHECK] source extracted chars: {source_characters}", flush=True)
    print(f"[CHECK] compressed extracted chars: {output_characters}", flush=True)
    print(f"[CHECK] retained text ratio: {ratio:.3f}", flush=True)

    if output_characters == 0 or ratio < args.minimum_text_ratio:
        try:
            output.unlink()
        except OSError:
            pass
        raise SystemExit(
            "[ERROR] 圧縮後にテキスト層が失われたため、圧縮版を削除しました"
        )

    print(f"[OK] compressed searchable PDF: {output}", flush=True)


if __name__ == "__main__":
    main()
