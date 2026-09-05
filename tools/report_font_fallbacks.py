#!/usr/bin/env python3
from __future__ import annotations

"""PaddleOCR JSON中の各文字が、どのPDF埋め込みフォントに割り当てられるかを報告する。

OCRやPDF生成をやり直さず、既存JSONとTTFのcmapだけから判定する。
M PLUS 1pで扱える文字、HanaMinA/Bへフォールバックする文字、どのフォントにも
収録されていない文字を、ページ別・全体集計の両方で確認できる。
"""

import argparse
import csv
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paddle_json_to_searchable_pdf import (  # noqa: E402
    FontRegistry,
    clean_text,
    find_result_dict,
    resolve_font_paths,
)


def page_number(path: Path) -> int:
    stem = path.stem
    marker = "page_"
    position = stem.find(marker)
    if position < 0:
        return 10**12
    digits = []
    for character in stem[position + len(marker):]:
        if not character.isdigit():
            break
        digits.append(character)
    return int("".join(digits)) if digits else 10**12


def load_texts(json_path: Path) -> list[str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    result = find_result_dict(data)
    if result is None:
        raise RuntimeError(f"rec_textsを検出できません: {json_path}")
    return [clean_text(value) for value in result.get("rec_texts", []) if clean_text(value)]


def codepoint_label(character: str) -> str:
    return f"U+{ord(character):04X}"


def unicode_name(character: str) -> str:
    return unicodedata.name(character, "UNNAMED")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PaddleOCR JSONの文字別フォント割り当てを報告する"
    )
    parser.add_argument(
        "json_dir",
        help="page_XXXX_paddle_small.json が入ったディレクトリ",
    )
    parser.add_argument(
        "--font-path",
        action="append",
        help="主・補助TTF。指定しない場合は通常の自動探索を使う",
    )
    parser.add_argument(
        "--output-dir",
        help="CSV・JSONレポートの出力先。省略時はjson_dirの親/report_font_fallbacks",
    )
    args = parser.parse_args()

    json_dir = Path(args.json_dir).expanduser().resolve()
    if not json_dir.is_dir():
        raise SystemExit(f"JSONディレクトリがありません: {json_dir}")

    json_files = sorted(json_dir.glob("page_*_paddle_small.json"), key=page_number)
    if not json_files:
        raise SystemExit(f"対象JSONがありません: {json_dir}")

    font_paths = resolve_font_paths(args.font_path)
    registry = FontRegistry()
    for index, font_path in enumerate(font_paths):
        registry.register(font_path, f"PaddleOCRFont{index}")

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else json_dir.parent / "font_fallback_report"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    alias_to_path = {
        str(entry["name"]): str(entry["path"])
        for entry in registry.entries
    }
    page_counts: dict[int, dict[str, Counter[str]]] = {}
    total_counts: dict[str, Counter[str]] = defaultdict(Counter)
    rows: list[dict[str, Any]] = []

    print(f"[INFO] pages: {len(json_files)}", flush=True)
    for index, json_path in enumerate(json_files, start=1):
        page = page_number(json_path)
        texts = load_texts(json_path)
        counts: dict[str, Counter[str]] = defaultdict(Counter)

        for text in texts:
            for character in text:
                font_name, draw_character = registry.pick_font_for_char(character)
                counts[font_name][character] += 1
                total_counts[font_name][character] += 1
                rows.append(
                    {
                        "page": page,
                        "source_character": character,
                        "source_codepoint": codepoint_label(character),
                        "source_name": unicode_name(character),
                        "draw_character": draw_character,
                        "draw_codepoint": codepoint_label(draw_character),
                        "font_alias": font_name,
                        "font_path": alias_to_path.get(font_name, ""),
                    }
                )

        page_counts[page] = counts
        print(f"[{index}/{len(json_files)}] page {page}", flush=True)
        for entry in registry.entries:
            alias = str(entry["name"])
            counter = counts.get(alias, Counter())
            unique = "".join(sorted(counter))
            print(
                f"  {Path(entry['path']).name}: occurrences={sum(counter.values())} "
                f"unique={len(counter)} chars={unique!r}",
                flush=True,
            )

    csv_path = output_dir / "font_fallback_characters.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "page",
                "source_character",
                "source_codepoint",
                "source_name",
                "draw_character",
                "draw_codepoint",
                "font_alias",
                "font_path",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    summary: dict[str, Any] = {
        "fonts": [],
        "pages": {},
        "unsupported_characters": sorted(registry.missing_characters),
    }

    print("\n=== TOTAL ===", flush=True)
    for entry in registry.entries:
        alias = str(entry["name"])
        counter = total_counts.get(alias, Counter())
        unique_characters = sorted(counter)
        details = [
            {
                "character": character,
                "codepoint": codepoint_label(character),
                "name": unicode_name(character),
                "occurrences": counter[character],
            }
            for character in unique_characters
        ]
        summary["fonts"].append(
            {
                "alias": alias,
                "path": str(entry["path"]),
                "occurrences": sum(counter.values()),
                "unique_characters": details,
            }
        )
        print(f"{entry['path']}", flush=True)
        print(f"  occurrences: {sum(counter.values())}", flush=True)
        print(f"  unique characters: {len(counter)}", flush=True)
        for detail in details:
            print(
                f"  {detail['character']!r} {detail['codepoint']} "
                f"{detail['name']} x{detail['occurrences']}",
                flush=True,
            )

    for page, counts in page_counts.items():
        summary["pages"][str(page)] = {
            alias: {
                "occurrences": sum(counter.values()),
                "characters": dict(counter),
            }
            for alias, counter in counts.items()
        }

    json_path = output_dir / "font_fallback_summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if registry.missing_characters:
        print("\n[WARN] unsupported characters:", flush=True)
        for character in sorted(registry.missing_characters):
            print(
                f"  {character!r} {codepoint_label(character)} {unicode_name(character)}",
                flush=True,
            )
    else:
        print("\n[OK] unsupported characters: 0", flush=True)

    print(f"[OK] CSV: {csv_path}", flush=True)
    print(f"[OK] JSON: {json_path}", flush=True)


if __name__ == "__main__":
    main()
