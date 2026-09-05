#!/usr/bin/env python3
from __future__ import annotations

"""巨大なPDFページだけを、OCRで安全に画像化できる表示サイズへ縮小する。

元PDFを最初から全面的に画像化し直すのではなく、上限を超えるページだけを
PDFページとして再配置する。画質を不必要に落とさず、巨大画像によるメモリ不足を
防ぐことが目的である。通常サイズのページは変更しない。
"""

import argparse
from pathlib import Path

import fitz


def estimated_dimensions(page: fitz.Page, dpi: int) -> tuple[int, int, int]:
    width = max(1, round(page.rect.width / 72.0 * dpi))
    height = max(1, round(page.rect.height / 72.0 * dpi))
    return width, height, width * height


def target_page_size(page: fitz.Page, dpi: int, target_long_edge_px: int) -> tuple[float, float]:
    width_pt = float(page.rect.width)
    height_pt = float(page.rect.height)
    long_edge_pt = target_long_edge_px / float(dpi) * 72.0
    if width_pt >= height_pt:
        return long_edge_pt, long_edge_pt * height_pt / width_pt
    return long_edge_pt * width_pt / height_pt, long_edge_pt


def normalize(
    input_pdf: Path,
    output_pdf: Path,
    dpi: int,
    max_pixels: int,
    target_long_edge_px: int,
) -> None:
    source = fitz.open(input_pdf)
    output = fitz.open()
    changed = 0

    try:
        print(f"[INFO] input: {input_pdf}", flush=True)
        print(f"[INFO] output: {output_pdf}", flush=True)
        print(f"[INFO] check dpi: {dpi}", flush=True)
        print(f"[INFO] max pixels: {max_pixels:,}", flush=True)
        print(f"[INFO] safe long edge: {target_long_edge_px:,} px", flush=True)

        for index, page in enumerate(source, start=1):
            pixel_width, pixel_height, pixels = estimated_dimensions(page, dpi)
            if pixels <= max_pixels:
                output.insert_pdf(source, from_page=index - 1, to_page=index - 1)
                print(
                    f"[KEEP] page {index}: {pixel_width:,}x{pixel_height:,} "
                    f"({pixels:,} pixels)",
                    flush=True,
                )
                continue

            target_width, target_height = target_page_size(page, dpi, target_long_edge_px)
            new_page = output.new_page(width=target_width, height=target_height)
            new_page.show_pdf_page(new_page.rect, source, index - 1, keep_proportion=True)
            new_width = round(target_width / 72.0 * dpi)
            new_height = round(target_height / 72.0 * dpi)
            changed += 1
            print(
                f"[RESIZE] page {index}: {pixel_width:,}x{pixel_height:,} "
                f"-> {new_width:,}x{new_height:,}",
                flush=True,
            )

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf, garbage=4, deflate=True, clean=True)
    finally:
        output.close()
        source.close()

    print(f"[DONE] changed pages: {changed}", flush=True)
    print(f"[DONE] saved: {output_pdf}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="PDFをOCR向けの安全なページサイズへ正規化する")
    parser.add_argument("input_pdf")
    parser.add_argument("output_pdf")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--max-pixels", type=int, default=25_000_000)
    parser.add_argument("--target-long-edge-px", type=int, default=3400)
    args = parser.parse_args()

    if args.dpi <= 0 or args.max_pixels <= 0 or args.target_long_edge_px <= 0:
        raise SystemExit("dpi・max-pixels・target-long-edge-px は正の整数で指定してください")

    normalize(
        Path(args.input_pdf).expanduser().resolve(),
        Path(args.output_pdf).expanduser().resolve(),
        args.dpi,
        args.max_pixels,
        args.target_long_edge_px,
    )


if __name__ == "__main__":
    main()
