#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paddle_batch_ocr import COMPACT_SCHEMA, compact_payload  # noqa: E402


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def compact_file(path: Path, dry_run: bool) -> tuple[int, int, str]:
    before = path.stat().st_size
    payload = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(payload, dict) and payload.get("schema") == COMPACT_SCHEMA:
        return before, before, "already-compact"

    compact = compact_payload(payload)
    encoded = json.dumps(
        compact,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    after = len(encoded)

    if not dry_run:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    return before, after, "compacted"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "既存の巨大なPaddleOCRページJSONを、文字・信頼度・座標だけのcompact-v1へ変換する"
        )
    )
    parser.add_argument("json_dir", help="page_*_paddle_small.json のあるフォルダ")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="変換せず削減見込みだけ表示する",
    )
    args = parser.parse_args()

    json_dir = Path(args.json_dir).expanduser().resolve()
    if not json_dir.is_dir():
        raise SystemExit(f"JSONフォルダがありません: {json_dir}")

    paths = sorted(json_dir.glob("page_*_paddle_small.json"))
    if not paths:
        raise SystemExit(f"対象JSONがありません: {json_dir}")

    total_before = 0
    total_after = 0

    for index, path in enumerate(paths, start=1):
        before, after, status = compact_file(path, args.dry_run)
        total_before += before
        total_after += after
        print(
            f"[{index}/{len(paths)}] {status}: {path.name} "
            f"{format_size(before)} -> {format_size(after)}"
        )

    saved = total_before - total_after
    print(f"[TOTAL] before: {format_size(total_before)}")
    print(f"[TOTAL] after : {format_size(total_after)}")
    print(f"[TOTAL] saved : {format_size(saved)}")
    if args.dry_run:
        print("[INFO] dry-runのためファイルは変更していません")
    else:
        print("[OK] compact-v1へ変換しました")


if __name__ == "__main__":
    main()
