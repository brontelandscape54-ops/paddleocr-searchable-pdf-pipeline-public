#!/usr/bin/env python3
from __future__ import annotations

"""PDF・画像・画像フォルダを、順序の明確なページPNGへ変換する。

この工程をOCR本体から分離するのは、入力の差異をここで吸収し、
PaddleOCRには常に同じ命名規則のPNGだけを渡すためである。
中間PNGを残すことで、OCR精度の確認や失敗ページだけの再処理も容易になる。
"""

import argparse
import re
from pathlib import Path

import fitz
from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}


def natural_key(path: Path) -> list[object]:
    """page_2 が page_10 より前になる、人間の感覚に近い順序を返す。"""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def save_image_as_png(source: Path, destination: Path) -> None:
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.save(destination, format="PNG", optimize=False)
    print(f"[OK] {destination}", flush=True)


def render_pdf(source: Path, output_dir: Path, dpi: int, grayscale: bool) -> int:
    document = fitz.open(source)
    try:
        colorspace = fitz.csGRAY if grayscale else fitz.csRGB
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(dpi=dpi, colorspace=colorspace, alpha=False)
            destination = output_dir / f"page_{index:04d}.png"
            pixmap.save(destination)
            print(
                f"[OK] page {index}/{len(document)}: {destination.name} "
                f"({pixmap.width}x{pixmap.height})",
                flush=True,
            )
        return len(document)
    finally:
        document.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PDF・画像・画像フォルダを page_XXXX.png へ変換する"
    )
    parser.add_argument("input_path")
    parser.add_argument("output_dir")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--grayscale", action="store_true")
    args = parser.parse_args()

    source = Path(args.input_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.dpi <= 0:
        raise SystemExit("--dpi は正の整数で指定してください")

    if source.is_file() and source.suffix.lower() == ".pdf":
        page_count = render_pdf(source, output_dir, args.dpi, args.grayscale)
    elif source.is_file() and source.suffix.lower() in IMAGE_EXTENSIONS:
        save_image_as_png(source, output_dir / "page_0001.png")
        page_count = 1
    elif source.is_dir():
        images = sorted(
            [
                path
                for path in source.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            ],
            key=natural_key,
        )
        if not images:
            raise SystemExit(f"画像ファイルがありません: {source}")
        for index, image_path in enumerate(images, start=1):
            save_image_as_png(image_path, output_dir / f"page_{index:04d}.png")
        page_count = len(images)
    else:
        raise SystemExit(f"未対応の入力です: {source}")

    print(f"[DONE] page count: {page_count}", flush=True)


if __name__ == "__main__":
    main()
