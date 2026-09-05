#!/usr/bin/env python3
from __future__ import annotations

"""Validate a real supplementary-plane Jigmo character through the PDF stack.

This is a local release-validation helper. It discovers an actual U+10000+
code point from Jigmo2/Jigmo3 instead of hard-coding a character, renders it
through the production searchable-PDF renderer, verifies exact pypdf text
extraction, and asks Ghostscript to parse the generated PDF when `gs` exists.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from fontTools.ttLib import TTFont as FontToolsTTFont
from PIL import Image
from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paddle_json_to_searchable_pdf import make_pdf  # noqa: E402


def supplementary_codepoints(font_path: Path) -> set[int]:
    font = FontToolsTTFont(str(font_path), lazy=True)
    values: set[int] = set()
    try:
        for table in font["cmap"].tables:
            values.update(
                codepoint
                for codepoint in table.cmap.keys()
                if 0x10000 <= codepoint <= 0x10FFFF
            )
    finally:
        font.close()
    return values


def pick_character(font_paths: list[Path]) -> tuple[Path, int, str]:
    for font_path in font_paths:
        codepoints = supplementary_codepoints(font_path)
        if not codepoints:
            continue

        # Prefer CJK Extension B and later unified ideographs when available.
        cjk = sorted(
            codepoint
            for codepoint in codepoints
            if 0x20000 <= codepoint <= 0x323AF
        )
        codepoint = cjk[0] if cjk else min(codepoints)
        return font_path, codepoint, chr(codepoint)

    raise RuntimeError("Jigmo2/Jigmo3にU+10000以上のcmap文字が見つかりません")


def write_fixture(directory: Path, character: str) -> tuple[Path, Path]:
    image_path = directory / "supplementary.png"
    json_path = directory / "supplementary.json"

    Image.new("RGB", (600, 160), "white").save(image_path)
    payload = {
        "rec_texts": [character],
        "rec_scores": [1.0],
        "rec_boxes": [[30, 30, 570, 130]],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return image_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Jigmo補助面文字を検索可能PDFとして実地検証する"
    )
    parser.add_argument(
        "--font-dir",
        default=str(PROJECT_ROOT / "fonts"),
        help="Jigmo.ttf/Jigmo2.ttf/Jigmo3.ttfが入ったディレクトリ",
    )
    parser.add_argument(
        "--keep-output",
        help="指定した場合、生成PDFをこのパスへコピーして残す",
    )
    args = parser.parse_args()

    font_dir = Path(args.font_dir).expanduser().resolve()
    jigmo_paths = [font_dir / "Jigmo2.ttf", font_dir / "Jigmo3.ttf"]
    missing = [str(path) for path in jigmo_paths if not path.is_file()]
    if missing:
        raise SystemExit(f"Jigmoフォントがありません: {missing}")

    selected_font, codepoint, character = pick_character(jigmo_paths)
    name = unicodedata.name(character, "UNNAMED")
    print(
        f"[INFO] selected: {character!r} U+{codepoint:05X} {name} "
        f"from {selected_font.name}"
    )

    with tempfile.TemporaryDirectory(prefix="jigmo_supplementary_") as temp_name:
        temp_dir = Path(temp_name)
        image_path, json_path = write_fixture(temp_dir, character)
        output_path = temp_dir / "supplementary.pdf"

        # Use only the font that actually contains the discovered character.
        # This makes the test hermetic and prevents another fallback font from
        # masking a supplementary-plane rendering failure.
        make_pdf(
            image_path=image_path,
            json_path=json_path,
            output_path=output_path,
            debug_visible=False,
            font_paths=[selected_font],
        )

        reader = PdfReader(str(output_path))
        extracted = "".join(page.extract_text() or "" for page in reader.pages)
        print(f"[CHECK] extracted repr: {extracted!r}")
        print(
            "[CHECK] extracted codepoints: "
            + " ".join(f"U+{ord(value):05X}" for value in extracted)
        )
        if extracted != character:
            raise RuntimeError(
                "supplementary-plane extraction mismatch: "
                f"expected {character!r}, got {extracted!r}"
            )
        print("[OK] pypdf exact supplementary-plane extraction")

        gs = shutil.which("gs")
        if gs:
            result = subprocess.run(
                [gs, "-sDEVICE=nullpage", "-dNOPAUSE", "-dBATCH", str(output_path)],
                text=True,
                capture_output=True,
            )
            combined = (result.stdout or "") + (result.stderr or "")
            print(combined, end="" if combined.endswith("\n") else "\n")
            if result.returncode != 0:
                raise RuntimeError(
                    f"Ghostscript failed with exit code {result.returncode}"
                )
            lowered = combined.lower()
            if "cmap has too many code maps" in lowered:
                raise RuntimeError("Ghostscript reported the CMap block-limit warning")
            if "repaired or ignored" in lowered:
                raise RuntimeError("Ghostscript reported repaired/ignored PDF errors")
            print("[OK] Ghostscript parsed supplementary-plane PDF without CMap warning")
        else:
            print("[WARN] Ghostscript not found; skipped gs parsing check")

        if args.keep_output:
            keep_path = Path(args.keep_output).expanduser().resolve()
            keep_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output_path, keep_path)
            print(f"[OK] copied validation PDF: {keep_path}")

    print("[DONE] Jigmo supplementary-plane PDF validation passed")


if __name__ == "__main__":
    main()
