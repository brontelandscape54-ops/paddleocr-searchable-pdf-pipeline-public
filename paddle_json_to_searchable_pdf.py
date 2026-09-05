#!/usr/bin/env python3
from __future__ import annotations

"""PaddleOCR JSONから、実在TTFを埋め込んだ検索可能PDFを作成する。

透明テキストは検索・コピーのための情報層であり、見た目の書体を再現することが
主目的ではない。Ghostscriptによる圧縮後もUnicode対応を維持しやすくするため、
CIDフォント名への依存を避け、実在する日本語TTFをReportLabのTTFontとして登録する。

通常の日本語はM PLUS 1pで扱い、収録されていない旧字・異体字・CJK拡張文字は
Jigmo / Jigmo2 / Jigmo3へ文字単位でフォールバックする。
"""

import argparse
import json
import os
import unicodedata
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont as FontToolsTTFont
from PIL import Image
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase import ttfonts as reportlab_ttfonts
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


DEFAULT_FONT_NAMES = [
    "MPLUS1p-Medium.ttf",
    "Jigmo.ttf",
    "Jigmo2.ttf",
    "Jigmo3.ttf",
]

PREFERRED_FONT_NAMES = [
    *DEFAULT_FONT_NAMES,
    "IPAexMincho.ttf",
    "ipaexm.ttf",
    "ipaexg.ttf",
    "NotoSansJP-Regular.ttf",
    "NotoSerifJP-Regular.ttf",
]

REPORTLAB_BFCHAR_BLOCK_LIMIT = 100


def unicode_codepoint_to_utf16be_hex(value: int) -> str:
    """Unicode code pointをPDF ToUnicode用UTF-16BE 16進表記へ変換する。"""
    return chr(value).encode("utf-16-be").hex().upper()


def make_to_unicode_cmap_compliant(fontname: str, subset: list[int]) -> str:
    """ReportLab互換のToUnicode CMapをAdobe仕様に沿う形で生成する。

    ReportLabのTTFontは最大256文字のsubsetを作る一方、標準の
    ``makeToUnicodeCMap`` はsubset全件を1つの ``beginbfchar`` ブロックへ
    書き出す。Adobe CMap仕様では1ブロック100件以下なので、対応内容は変えずに
    ブロック境界だけを100件ごとに分割する。

    また、補助面文字はToUnicode CMapの宛先をUTF-16BEのサロゲートペアで表す。
    BMP文字の出力は従来と同じ4桁16進表記になる。
    """
    cmap = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo",
        "<< /Registry (%s)" % fontname,
        "/Ordering (%s)" % fontname,
        "/Supplement 0",
        ">> def",
        "/CMapName /%s def" % fontname,
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<00> <%02X>" % (len(subset) - 1),
        "endcodespacerange",
    ]

    for start in range(0, len(subset), REPORTLAB_BFCHAR_BLOCK_LIMIT):
        chunk = subset[start : start + REPORTLAB_BFCHAR_BLOCK_LIMIT]
        cmap.append("%d beginbfchar" % len(chunk))
        cmap.extend(
            "<%02X> <%s>" % (code, unicode_codepoint_to_utf16be_hex(value))
            for code, value in enumerate(chunk, start=start)
        )
        cmap.append("endbfchar")

    cmap.extend(
        [
            "endcmap",
            "CMapName currentdict /CMap defineresource pop",
            "end",
            "end",
        ]
    )
    return "\n".join(cmap)


def install_reportlab_cmap_compatibility() -> None:
    """このプロセス内だけReportLabのToUnicode CMap生成を仕様準拠版へ差し替える。"""
    reportlab_ttfonts.makeToUnicodeCMap = make_to_unicode_cmap_compliant


# TTFont.addObjects() はreportlab.pdfbase.ttfontsのモジュールグローバル関数を
# 実行時に参照するため、この局所的な差し替えだけで埋め込みフォントのCMapへ効く。
# site-packages自体は変更しない。
install_reportlab_cmap_compatibility()


def unique_existing(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    found: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            resolved = path.expanduser()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            found.append(resolved)
    return found


def require_existing(paths: list[Path], source: str) -> list[Path]:
    existing = unique_existing(paths)
    if not existing:
        raise FileNotFoundError(f"{source}で指定されたTTFが見つかりません。")
    return existing


def resolve_font_paths(explicit_paths: list[str] | None) -> list[Path]:
    """指定フォントを優先し、未指定時はM PLUS→Jigmoの既定順で探す。

    ``--font-path`` を1つでも指定した場合は、その明示指定だけを使う。
    ``PADDLE_PDF_FONTS`` も同様に完全な優先順として扱う。これにより監査時に
    指定外のローカルフォントがcoverageを偶然補うことを防ぐ。
    """
    project_root = Path(__file__).resolve().parent

    if explicit_paths:
        return require_existing(
            [Path(value) for value in explicit_paths],
            "--font-path",
        )

    environment_paths = os.environ.get("PADDLE_PDF_FONTS", "").strip()
    if environment_paths:
        return require_existing(
            [Path(value) for value in environment_paths.split(os.pathsep) if value],
            "PADDLE_PDF_FONTS",
        )

    legacy_environment_path = os.environ.get("PADDLE_PDF_FONT", "").strip()
    if legacy_environment_path:
        return require_existing(
            [Path(legacy_environment_path)],
            "PADDLE_PDF_FONT",
        )

    candidates: list[Path] = []
    local_font_root = project_root / "fonts"
    for name in DEFAULT_FONT_NAMES:
        candidates.append(local_font_root / name)

    system_roots = [
        # macOS
        Path.home() / "Library/Fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        # Linux / freedesktop-style locations
        Path.home() / ".local/share/fonts",
        Path.home() / ".fonts",
        Path("/usr/local/share/fonts"),
        Path("/usr/share/fonts"),
    ]
    for name in PREFERRED_FONT_NAMES:
        for root in system_roots:
            candidates.append(root / name)
            if root.is_dir():
                candidates.extend(root.rglob(name))

    existing = unique_existing(candidates)
    if not existing:
        raise FileNotFoundError(
            "日本語TTFが見つかりません。推奨構成は "
            "MPLUS1p-Medium.ttf → Jigmo.ttf → Jigmo2.ttf → Jigmo3.ttf です。"
            "bash tools/setup_fonts.sh を実行するか、--font-pathを繰り返すか、"
            "PADDLE_PDF_FONTSで指定してください。"
        )
    return existing


class FontRegistry:
    """登録フォントのcmapを調べ、文字ごとに最初の対応フォントを選ぶ。"""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.missing_characters: set[str] = set()
        self.usage: dict[str, int] = {}

    def register(self, path: Path, alias: str) -> None:
        pdfmetrics.registerFont(TTFont(alias, str(path)))
        font = FontToolsTTFont(str(path), lazy=True)
        cmap: set[int] = set()
        try:
            for table in font["cmap"].tables:
                cmap.update(table.cmap.keys())
        finally:
            font.close()
        self.entries.append({"name": alias, "path": path, "cmap": cmap})
        self.usage[alias] = 0

    @property
    def primary_name(self) -> str:
        if not self.entries:
            raise RuntimeError("フォントが登録されていません")
        return str(self.entries[0]["name"])

    def pick_font_for_char(self, character: str) -> tuple[str, str]:
        codepoint = ord(character)
        for entry in self.entries:
            if codepoint in entry["cmap"]:
                return str(entry["name"]), character

        normalized = unicodedata.normalize("NFKC", character)
        if len(normalized) == 1:
            normalized_codepoint = ord(normalized)
            for entry in self.entries:
                if normalized_codepoint in entry["cmap"]:
                    return str(entry["name"]), normalized

        self.missing_characters.add(character)
        return self.primary_name, character

    def split_runs(self, text: str) -> list[tuple[str, str]]:
        runs: list[tuple[str, str]] = []
        current_font: str | None = None
        current_chars: list[str] = []

        for character in text:
            font_name, draw_character = self.pick_font_for_char(character)
            if current_chars and font_name != current_font:
                runs.append((str(current_font), "".join(current_chars)))
                current_chars = []
            current_font = font_name
            current_chars.append(draw_character)
            self.usage[font_name] = self.usage.get(font_name, 0) + 1

        if current_chars:
            runs.append((str(current_font), "".join(current_chars)))
        return runs


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split())


def find_result_dict(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        if isinstance(obj.get("rec_texts"), list):
            return obj
        for value in obj.values():
            found = find_result_dict(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_result_dict(value)
            if found is not None:
                return found
    return None


def to_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)):
        return None

    if (
        len(value) == 4
        and all(isinstance(v, (int, float)) for v in value)
    ):
        x0, y0, x1, y1 = map(float, value)
        if x1 <= x0 or y1 <= y0:
            return None
        return [x0, y0, x1, y1]

    points: list[tuple[float, float]] = []
    for point in value:
        if (
            isinstance(point, (list, tuple))
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        ):
            points.append((float(point[0]), float(point[1])))

    if not points:
        return None

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)

    if x1 <= x0 or y1 <= y0:
        return None

    return [x0, y0, x1, y1]


def load_items(json_path: Path) -> list[dict[str, Any]]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    result = find_result_dict(data)

    if result is None:
        raise RuntimeError("rec_textsを含むPaddleOCR結果を検出できません。")

    texts = result.get("rec_texts") or []
    scores = result.get("rec_scores") or []
    boxes = result.get("rec_boxes") or []
    polygons = result.get("rec_polys") or result.get("dt_polys") or []

    items: list[dict[str, Any]] = []

    for index, raw_text in enumerate(texts):
        text = clean_text(raw_text)
        if not text:
            continue

        bbox = None
        if index < len(boxes):
            bbox = to_bbox(boxes[index])
        if bbox is None and index < len(polygons):
            bbox = to_bbox(polygons[index])
        if bbox is None:
            continue

        score = None
        if index < len(scores):
            try:
                score = float(scores[index])
            except (TypeError, ValueError):
                pass

        items.append(
            {
                "text": text,
                "bbox": bbox,
                "score": score,
            }
        )

    items.sort(
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
        )
    )
    return items


def calc_font_size(
    runs: list[tuple[str, str]],
    width: float,
    height: float,
) -> float:
    base = max(2.0, height * 0.85)
    width_at_one = 0.0
    for font_name, text in runs:
        try:
            width_at_one += pdfmetrics.stringWidth(text, font_name, 1.0)
        except Exception:
            width_at_one += max(1.0, len(text) * 0.5)

    if width_at_one <= 0:
        return min(base, 30.0)

    fitted = width / width_at_one * 0.98
    return max(2.0, min(base, fitted, 30.0))


def make_pdf(
    image_path: Path,
    json_path: Path,
    output_path: Path,
    debug_visible: bool,
    font_paths: list[Path],
) -> None:
    items = load_items(json_path)

    registry = FontRegistry()
    if items:
        for index, font_path in enumerate(font_paths):
            registry.register(font_path, f"PaddleOCRFont{index}")

    with Image.open(image_path) as image:
        image_width, image_height = image.size

    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(
        str(output_path),
        pagesize=(float(image_width), float(image_height)),
        pageCompression=1,
    )
    pdf.drawImage(
        ImageReader(str(image_path)),
        0,
        0,
        width=float(image_width),
        height=float(image_height),
        preserveAspectRatio=False,
        mask="auto",
    )

    if not items:
        print("[WARN] OCR文字が0件のため、画像のみのPDFページを生成します。")

    for item in items:
        text = item["text"]
        x0, y0, x1, y1 = item["bbox"]
        box_width = x1 - x0
        box_height = y1 - y0
        runs = registry.split_runs(text)
        font_size = calc_font_size(runs, box_width, box_height)

        pdf_y_bottom = image_height - y1
        baseline_y = pdf_y_bottom + max(
            0.0,
            (box_height - font_size) * 0.42,
        )

        pdf.saveState()
        if debug_visible:
            pdf.setFillColor(Color(1, 0, 0, alpha=0.45))
        else:
            pdf.setFillColor(Color(1, 1, 1, alpha=0))

        text_object = pdf.beginText()
        text_object.setTextOrigin(x0, baseline_y)
        for font_name, run in runs:
            text_object.setFont(font_name, font_size)
            text_object.textOut(run)
        pdf.drawText(text_object)
        pdf.restoreState()

    pdf.showPage()
    pdf.save()

    scores = [
        item["score"]
        for item in items
        if item["score"] is not None
    ]

    for index, entry in enumerate(registry.entries):
        alias = str(entry["name"])
        print(
            f"[OK] font {index + 1}: {entry['path']} "
            f"used_chars={registry.usage.get(alias, 0)}"
        )
    if registry.missing_characters:
        sample = "".join(sorted(registry.missing_characters)[:40])
        print(
            f"[WARN] unsupported characters: "
            f"{len(registry.missing_characters)} sample={sample!r}"
        )
    else:
        print("[OK] unsupported characters: 0")

    print(f"[OK] OCR lines: {len(items)}")
    print(f"[OK] characters: {sum(len(item['text']) for item in items)}")
    if scores:
        print(f"[OK] mean confidence: {sum(scores) / len(scores):.4f}")
        print(f"[OK] min confidence: {min(scores):.4f}")
    print(f"[OK] output: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PaddleOCR JSONから複数TTF対応の透明テキスト付きPDFを作成する"
    )
    parser.add_argument("--image", required=True)
    parser.add_argument("--json", required=True, dest="json_path")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--font-path",
        action="append",
        help=(
            "主・補助TTF。指定した場合はそのフォントだけを指定順で使用する。"
            "推奨順はM PLUS 1p、Jigmo、Jigmo2、Jigmo3"
        ),
    )
    parser.add_argument("--debug-visible", action="store_true")
    args = parser.parse_args()

    font_paths = resolve_font_paths(args.font_path)
    make_pdf(
        image_path=Path(args.image),
        json_path=Path(args.json_path),
        output_path=Path(args.out),
        debug_visible=args.debug_visible,
        font_paths=font_paths,
    )


if __name__ == "__main__":
    main()
