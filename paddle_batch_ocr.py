#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import threading
import time
from pathlib import Path
from typing import Any


COMPACT_SCHEMA = "paddleocr-searchable-pdf-pipeline/compact-v1"


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]

    if hasattr(value, "tolist"):
        try:
            return jsonable(value.tolist())
        except Exception:
            pass

    if hasattr(value, "item"):
        try:
            return jsonable(value.item())
        except Exception:
            pass

    if hasattr(value, "model_dump"):
        try:
            return jsonable(value.model_dump())
        except Exception:
            pass

    return str(value)


def result_payload(result: Any) -> Any:
    if isinstance(result, (dict, list)):
        return jsonable(result)

    for name in ("json", "res", "data"):
        try:
            value = getattr(result, name)
        except Exception:
            continue

        try:
            value = value() if callable(value) else value
        except Exception:
            continue

        if isinstance(value, (dict, list)):
            return jsonable(value)

    for name in ("to_dict", "model_dump", "dict"):
        try:
            method = getattr(result, name)
        except Exception:
            continue

        if not callable(method):
            continue

        try:
            value = method()
        except Exception:
            continue

        if isinstance(value, (dict, list)):
            return jsonable(value)

    raise RuntimeError(
        f"PaddleOCR結果をJSONへ変換できません: {type(result).__name__}"
    )


def find_ocr_result(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        if isinstance(obj.get("rec_texts"), list):
            return obj
        for value in obj.values():
            found = find_ocr_result(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_ocr_result(value)
            if found is not None:
                return found
    return None


def find_first_scalar(obj: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                if key in obj:
                    return value
        for value in obj.values():
            found = find_first_scalar(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_first_scalar(value, keys)
            if found is not None:
                return found
    return None


def compact_payload(payload: Any, image_path: Path | None = None) -> dict[str, Any]:
    """検索可能PDF生成と検証に必要なOCR項目だけを保存する。

    PaddleOCRの生結果には入力画像配列や中間処理結果が含まれる場合があり、
    1ページで100MBを超えることがある。再処理に必要な文字、信頼度、bbox、polygonだけを
    明示的な小型スキーマへ移し、巨大な内部配列を永続化しない。
    """

    result = find_ocr_result(payload)
    if result is None:
        raise RuntimeError("rec_textsを含むPaddleOCR結果を検出できません")

    compact_result: dict[str, Any] = {}
    for key in (
        "rec_texts",
        "rec_scores",
        "rec_boxes",
        "rec_polys",
        "dt_polys",
    ):
        value = result.get(key)
        if value is not None:
            compact_result[key] = jsonable(value)

    return {
        "schema": COMPACT_SCHEMA,
        "input_image": (
            str(image_path.resolve())
            if image_path is not None
            else find_first_scalar(payload, ("input_path", "input_image", "img_path"))
        ),
        "page_index": find_first_scalar(payload, ("page_index", "page_id", "page")),
        "ocr": compact_result,
    }


def summarize_payload(payload: Any) -> dict[str, Any]:
    result = find_ocr_result(payload)
    if result is None:
        return {
            "lines": 0,
            "characters": 0,
            "mean_confidence": None,
            "min_confidence": None,
            "texts": [],
        }

    texts = [
        str(text).strip()
        for text in (result.get("rec_texts") or [])
        if str(text).strip()
    ]

    scores: list[float] = []
    for value in result.get("rec_scores") or []:
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(score):
            scores.append(score)

    return {
        "lines": len(texts),
        "characters": sum(len(text) for text in texts),
        "mean_confidence": (
            sum(scores) / len(scores) if scores else None
        ),
        "min_confidence": min(scores) if scores else None,
        "texts": texts,
    }


def build_ocr() -> tuple[Any, float]:
    from paddleocr import PaddleOCR

    kwargs = {
        "text_detection_model_name": "PP-OCRv6_small_det",
        "text_recognition_model_name": "PP-OCRv6_small_rec",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "text_recognition_batch_size": 8,
        "engine": "onnxruntime",
        "engine_config": {
            "providers": ["CPUExecutionProvider"],
            "intra_op_num_threads": 2,
            "inter_op_num_threads": 1,
            "execution_mode": "sequential",
            "enable_mem_pattern": False,
            "enable_cpu_mem_arena": False,
        },
    }

    print(f"[INFO] PaddleOCR init settings: {kwargs}", flush=True)
    print(
        "[INIT] PaddleOCRモデルとONNX Runtimeを初期化しています...",
        flush=True,
    )

    start = time.perf_counter()
    finished = threading.Event()

    def report_elapsed() -> None:
        while not finished.wait(10.0):
            elapsed = time.perf_counter() - start
            print(
                f"[INIT] 初期化中... {elapsed:.0f}秒経過",
                flush=True,
            )

    reporter = threading.Thread(
        target=report_elapsed,
        name="paddleocr-init-progress",
        daemon=True,
    )
    reporter.start()

    try:
        ocr = PaddleOCR(**kwargs)
    except Exception:
        elapsed = time.perf_counter() - start
        print(
            f"[ERROR] PaddleOCR初期化失敗: {elapsed:.2f}秒",
            flush=True,
        )
        raise
    finally:
        finished.set()
        reporter.join(timeout=0.2)

    elapsed = time.perf_counter() - start
    print(f"[OK] PaddleOCR初期化完了: {elapsed:.2f}秒", flush=True)
    return ocr, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PNGページ群をPaddleOCR smallモデルで一括OCRする"
    )
    parser.add_argument("--pages-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--pattern",
        default="page_*.png",
        help="既定: page_*.png",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存JSONも再OCRする",
    )
    args = parser.parse_args()

    pages_dir = Path(args.pages_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    json_dir = output_dir / "json"
    text_dir = output_dir / "txt"

    if not pages_dir.is_dir():
        raise FileNotFoundError(f"ページフォルダがありません: {pages_dir}")

    images = sorted(pages_dir.glob(args.pattern))
    if not images:
        raise FileNotFoundError(
            f"画像が見つかりません: {pages_dir / args.pattern}"
        )

    json_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] pages: {len(images)}", flush=True)
    print(f"[INFO] input: {pages_dir}", flush=True)
    print(f"[INFO] output: {output_dir}", flush=True)

    process_start = time.perf_counter()
    ocr: Any | None = None
    initialization_seconds = 0.0
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    ocr_page_count = 0
    existing_page_count = 0

    for index, image_path in enumerate(images, start=1):
        stem = image_path.stem
        json_path = json_dir / f"{stem}_paddle_small.json"
        text_path = text_dir / f"{stem}_paddle_small.txt"

        print(flush=True)
        print(f"[{index}/{len(images)}] {image_path.name}", flush=True)

        elapsed = 0.0
        status = "ok"

        try:
            if json_path.exists() and not args.overwrite:
                print(f"[SKIP] existing: {json_path}", flush=True)
                payload = json.loads(
                    json_path.read_text(encoding="utf-8")
                )
                status = "existing"
                existing_page_count += 1
            else:
                if ocr is None:
                    ocr, initialization_seconds = build_ocr()

                start = time.perf_counter()
                results = list(
                    ocr.predict(
                        str(image_path),
                        text_rec_score_thresh=0.0,
                    )
                )
                elapsed = time.perf_counter() - start
                ocr_page_count += 1

                if not results:
                    raise RuntimeError("OCR結果が0件です")

                payloads = [result_payload(result) for result in results]
                raw_payload = payloads[0] if len(payloads) == 1 else payloads
                payload = compact_payload(raw_payload, image_path=image_path)

                json_path.write_text(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )

            summary = summarize_payload(payload)
            text_path.write_text(
                "\n".join(summary["texts"])
                + ("\n" if summary["texts"] else ""),
                encoding="utf-8",
            )

            mean_text = (
                ""
                if summary["mean_confidence"] is None
                else f"{summary['mean_confidence']:.4f}"
            )
            min_text = (
                ""
                if summary["min_confidence"] is None
                else f"{summary['min_confidence']:.4f}"
            )

            print(
                f"[OK] seconds={elapsed:.2f} "
                f"lines={summary['lines']} "
                f"chars={summary['characters']} "
                f"mean={mean_text} min={min_text}",
                flush=True,
            )

            rows.append(
                {
                    "page": image_path.name,
                    "status": status,
                    "seconds": f"{elapsed:.3f}",
                    "lines": summary["lines"],
                    "characters": summary["characters"],
                    "mean_confidence": mean_text,
                    "min_confidence": min_text,
                    "json": str(json_path),
                    "txt": str(text_path),
                }
            )
        except Exception as exc:
            failures.append(image_path.name)
            print(f"[ERROR] {image_path.name}: {exc}", flush=True)
            rows.append(
                {
                    "page": image_path.name,
                    "status": "error",
                    "seconds": f"{elapsed:.3f}",
                    "lines": "",
                    "characters": "",
                    "mean_confidence": "",
                    "min_confidence": "",
                    "json": str(json_path),
                    "txt": str(text_path),
                }
            )

    total_elapsed = time.perf_counter() - process_start
    summary_csv = output_dir / "paddle_batch_summary.csv"

    with summary_csv.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "page",
                "status",
                "seconds",
                "lines",
                "characters",
                "mean_confidence",
                "min_confidence",
                "json",
                "txt",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(flush=True)
    if ocr is None:
        print(
            "[INFO] OCR対象ページがないため、"
            "PaddleOCRモデルの初期化を省略しました",
            flush=True,
        )
    else:
        print(
            f"[DONE] initialization seconds: "
            f"{initialization_seconds:.2f}",
            flush=True,
        )
    print(f"[DONE] OCR pages: {ocr_page_count}", flush=True)
    print(f"[DONE] existing pages: {existing_page_count}", flush=True)
    print(
        f"[DONE] total wall seconds (including initialization): "
        f"{total_elapsed:.2f}",
        flush=True,
    )
    print(f"[DONE] summary: {summary_csv}", flush=True)

    if failures:
        raise SystemExit(
            "[ERROR] failed pages: " + ", ".join(failures)
        )


if __name__ == "__main__":
    main()
