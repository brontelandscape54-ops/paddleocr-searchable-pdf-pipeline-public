#!/usr/bin/env python3
from __future__ import annotations

"""ページ別のPaddleOCR成果物を、閲覧・検索・後処理向けに統合する。

ページ別JSONは再処理や検証に有用なので残し、統合版は利便性のために追加する。
どちらか一方へ潰さないことが、このパイプラインの基本方針である。

大きなJSONを読む工程は、処理自体が正常でも端末上では停止して見えやすい。
そのためページ単位とファイル書き出し単位で進捗を明示し、利用者が現在位置を
確認できるようにする。
"""

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any


def page_number(path: Path) -> int:
    match = re.search(r"page_(\d+)", path.name)
    return int(match.group(1)) if match else 10**12


def main() -> None:
    parser = argparse.ArgumentParser(description="PaddleOCRのページ別TXT・JSONを統合する")
    parser.add_argument("ocr_dir", help="paddle_batch_ocr.py の出力ディレクトリ")
    parser.add_argument("output_dir")
    parser.add_argument("--prefix", required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    ocr_dir = Path(args.ocr_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    json_dir = ocr_dir / "json"
    text_dir = ocr_dir / "txt"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_files = sorted(json_dir.glob("page_*_paddle_small.json"), key=page_number)
    if not json_files:
        raise SystemExit(f"ページJSONがありません: {json_dir}")

    print(f"[INFO] aggregate pages: {len(json_files)}", flush=True)
    print(f"[INFO] JSON source: {json_dir}", flush=True)
    print(f"[INFO] output: {output_dir}", flush=True)

    combined: list[dict[str, Any]] = []
    txt_sections: list[str] = []
    md_sections: list[str] = [f"# {args.prefix} PaddleOCR結果", ""]

    jsonl_path = output_dir / f"{args.prefix}_paddle_pages.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as jsonl_file:
        for index, json_path in enumerate(json_files, start=1):
            page_started = time.perf_counter()
            page_no = page_number(json_path)
            label = page_no if page_no < 10**12 else index
            print(
                f"[{index}/{len(json_files)}] aggregate page {label}: "
                f"{json_path.name}",
                flush=True,
            )

            text_path = text_dir / json_path.name.replace("_paddle_small.json", "_paddle_small.txt")
            text = text_path.read_text(encoding="utf-8", errors="replace").rstrip() if text_path.exists() else ""
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            record = {
                "page": label,
                "image": f"page_{page_no:04d}.png" if page_no < 10**12 else "",
                "source_json": json_path.name,
                "text": text,
                "ocr": payload,
            }
            combined.append(record)
            jsonl_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            jsonl_file.flush()

            txt_sections.append(f"===== PAGE {label} =====\n{text}".rstrip())
            md_sections.extend([f"## PAGE {label}", "", text or "（OCRテキストなし）", "", "---", ""])

            elapsed = time.perf_counter() - page_started
            print(
                f"[OK] page {label}: text chars={len(text)} "
                f"seconds={elapsed:.2f}",
                flush=True,
            )

    txt_path = output_dir / f"{args.prefix}_paddle.txt"
    md_path = output_dir / f"{args.prefix}_paddle.md"
    json_path = output_dir / f"{args.prefix}_paddle.json"

    print(f"[WRITE] TXT: {txt_path.name}", flush=True)
    txt_path.write_text("\n\n".join(txt_sections) + "\n", encoding="utf-8")
    print(f"[OK] TXT: {txt_path}", flush=True)

    print(f"[WRITE] Markdown: {md_path.name}", flush=True)
    md_path.write_text("\n".join(md_sections), encoding="utf-8")
    print(f"[OK] Markdown: {md_path}", flush=True)

    # 統合JSONはページ数が多いほど書き出しに時間がかかるため、開始前に明示する。
    print(f"[WRITE] combined JSON: {json_path.name}", flush=True)
    json_path.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] combined JSON: {json_path}", flush=True)
    print(f"[OK] JSONL: {jsonl_path}", flush=True)

    elapsed = time.perf_counter() - started
    print(f"[DONE] pages: {len(combined)}", flush=True)
    print(f"[DONE] aggregate seconds: {elapsed:.2f}", flush=True)
    print(f"[DONE] output: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
