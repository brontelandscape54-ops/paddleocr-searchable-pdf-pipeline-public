#!/usr/bin/env python3
"""Experimental, Bash-free orchestration for the existing PaddleOCR pipeline.

This entry point deliberately leaves the OCR and PDF rendering algorithms unchanged.
It is not yet a replacement for paddleocr.sh or the Bash-based setup scripts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
HELPER_MODULES = "import fitz, PIL, reportlab, pypdf, fontTools"
PADDLE_MODULES = "import paddleocr, paddlex, onnxruntime"
FONT_PROBE = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from paddle_json_to_searchable_pdf import resolve_font_paths
try:
    fonts = resolve_font_paths(None)
except (FileNotFoundError, ValueError) as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
for font in fonts:
    print(font)
"""


class PipelineError(Exception):
    """A prerequisite or pipeline stage failed."""


def python_child_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Force UTF-8 for Python subprocesses whose output is captured in pipes.

    Windows may otherwise use a legacy encoding such as cp1252 for piped stdout,
    causing Japanese progress messages to raise UnicodeEncodeError.
    Preserve caller-specified stage settings without changing the parent env.
    """
    child_env = (os.environ if env is None else env).copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    return child_env


def interpreter_in(venv: Path, *, platform_name: str | None = None) -> Path:
    """Return a platform-specific interpreter path without mutating global os.name."""
    platform_name = os.name if platform_name is None else platform_name
    if platform_name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def python_works(python: Path, imports: str) -> bool:
    if not python.is_file():
        return False
    try:
        result = subprocess.run(
            [str(python), "-c", imports],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except OSError:
        return False


def select_interpreter(
    override: str | None, candidates: list[Path], imports: str, label: str
) -> Path:
    if override:
        # A venv's python executable can be a symlink to its base interpreter.
        # resolve() would bypass the venv and silently lose its site-packages.
        path = Path(override).expanduser().absolute()
        if python_works(path, imports):
            return path
        raise PipelineError(f"{label} is unusable: {path}")
    for path in candidates:
        if python_works(path, imports):
            return path.absolute()
    raise PipelineError(f"{label} not found. Run the existing setup first.")


def resolve_interpreters(root: Path) -> tuple[Path, Path]:
    paddle = select_interpreter(
        os.environ.get("PADDLE_PYTHON"),
        [interpreter_in(root / ".venv_paddle")],
        PADDLE_MODULES,
        "Paddle Python",
    )
    helper_candidates: list[Path] = []
    if os.environ.get("VIRTUAL_ENV"):
        helper_candidates.append(interpreter_in(Path(os.environ["VIRTUAL_ENV"])))
    helper_candidates.extend([interpreter_in(root / ".venv"), Path(sys.executable)])
    helper = select_interpreter(
        os.environ.get("HELPER_PYTHON"),
        helper_candidates,
        HELPER_MODULES,
        "Helper Python",
    )
    return paddle, helper


def check_fonts(root: Path, helper: Path) -> list[str]:
    try:
        result = subprocess.run(
            [str(helper), "-c", FONT_PROBE, str(root)],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            env=python_child_env(),
        )
    except OSError as exc:
        raise PipelineError(f"Font preflight could not start: {exc}") from exc
    if result.returncode:
        message = (result.stderr or result.stdout).strip()
        if "Traceback (most recent call last)" in message:
            raise PipelineError(
                f"フォント検査を実行できません。Helper Pythonの依存関係を確認してください: "
                f"{helper}\n{message}"
            )
        raise PipelineError(
            "日本語TTFを解決できません。bash tools/setup_fonts.sh で取得するか、"
            "PADDLE_PDF_FONTSで指定してください。\n" + message
        )
    fonts = [line for line in result.stdout.splitlines() if line]
    if not fonts:
        raise PipelineError("Font preflight returned no font paths.")
    return fonts


def positive_int(raw: str, name: str) -> int:
    try:
        number = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError(f"{name} must be a positive integer")
    return number


def clean_name(value: str) -> str:
    # Retain legacy names for ordinary inputs; additionally exclude Windows-unsafe
    # filename characters and traversal when a user supplies the job name.
    value = re.sub(r'[<>:"/\\|?*\[\]{}\x00-\x1f\x7f]', "_", value)
    value = re.sub(r"_+", "_", value).strip(" ._")
    if not value:
        return "paddleocr_job"
    # Windows device names are reserved even when followed by an extension.
    # Prefix rather than replace to keep ordinary names and job labels stable.
    if re.fullmatch(r"(?i:(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]))(?:\..*)?", value):
        return "_" + value
    return value


def paths_for(input_path: Path, root: Path, job_name: str | None, when: dt.datetime) -> dict[str, Path | str]:
    prefix = clean_name(input_path.name if input_path.is_dir() else input_path.stem)
    name = clean_name(job_name or f"{prefix}_paddleocr_{when:%Y%m%d_%H%M%S}")
    job = root / "jobs" / name
    pdf_dir = job / "searchable_pdf"
    return {
        "name": name, "prefix": prefix, "job": job,
        "preprocessed": job / "preprocessed",
        "pages": job / "pages", "ocr": job / "paddle_ocr",
        "json": job / "paddle_ocr" / "json", "txt": job / "paddle_ocr" / "txt",
        "output": job / "output", "pdf_pages": pdf_dir / "pages_pdf",
        "merged": pdf_dir / f"{prefix}_paddleocr_searchable.pdf",
        "small": pdf_dir / f"{prefix}_paddleocr_searchable_small_150dpi.pdf",
        "logs": job / "logs",
    }


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
INPUT_IDENTITY_FILENAME = "00_input_identity.json"


def file_fingerprint(source: Path) -> dict[str, object]:
    """Hash input bytes without reading large PDFs or images into memory."""
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"size": source.stat().st_size, "sha256": digest.hexdigest()}


def input_identity(
    input_path: Path, *, dpi: int, normalize_pdf: bool,
    max_pixels: int, long_edge: int,
) -> dict[str, object]:
    """Fingerprint the original input and options controlling prepared pages."""
    if input_path.is_dir():
        sources = sorted(
            (entry for entry in input_path.iterdir()
             if entry.is_file() and entry.suffix.lower() in IMAGE_EXTENSIONS),
            key=lambda entry: entry.name,
        )
        if not sources:
            raise PipelineError(f"入力フォルダに対応画像がありません: {input_path}")
        contents: dict[str, object] = {
            "type": "directory",
            "images": [
                {"name": entry.name, **file_fingerprint(entry)}
                for entry in sources
            ],
        }
    elif input_path.is_file():
        contents = {"type": "file", **file_fingerprint(input_path)}
    else:
        raise PipelineError(f"入力がファイルまたはフォルダではありません: {input_path}")
    return {
        "version": 1,
        "input_path": str(input_path),
        "source": contents,
        "dpi": dpi,
        "normalize_pdf": normalize_pdf,
        "max_pixels": max_pixels,
        "target_long_edge_px": long_edge,
    }


def validate_job_identity(job: Path, identity: dict[str, object]) -> None:
    """Refuse unsafe reuse *before* writing logs or touching existing page/JSON files."""
    if not job.exists():
        return
    if not job.is_dir():
        raise PipelineError(f"job出力先がフォルダではありません: {job}")
    if not any(job.iterdir()):
        return
    record = job / "logs" / INPUT_IDENTITY_FILENAME
    if not record.is_file():
        raise PipelineError(
            f"既存jobには入力識別記録がないため安全に再開できません: {job}。"
            "元のjobを残し、別のjob名を指定してください。"
        )
    try:
        stored = json.loads(record.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PipelineError(
            f"既存jobの入力識別記録を読み取れません: {record}。"
            "元のjobを残し、別のjob名を指定してください。"
        ) from exc
    if stored != identity:
        raise PipelineError(
            f"入力ファイルの内容・パス、画像フォルダの構成、または処理設定が"
            f"既存jobと一致しません: {job}。"
            "既存のOCR結果を再利用せず、別のjob名を指定してください。"
        )


def run_stage(
    label: str, command: list[str], log_dir: Path, *, env: dict[str, str] | None = None
) -> None:
    """Stream combined subprocess output to both terminal and per-stage UTF-8 log."""
    print(f"\n=== {label} ===", flush=True)
    print("[COMMAND] " + " ".join(command), flush=True)
    log_path = log_dir / f"{label}.log"
    with log_path.open("w", encoding="utf-8") as log:
        try:
            with subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=python_child_env(env),
            ) as process:
                assert process.stdout is not None
                for line in process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                result = process.wait()
        except OSError as exc:
            raise PipelineError(f"{label} could not start: {exc}") from exc
        if result:
            raise PipelineError(f"{label} failed: exit={result}; log={log_path}")


def run_pipeline(
    input_path: Path, root: Path, paths: dict[str, Path | str],
    paddle: Path, helper: Path, dpi: int,
) -> None:
    job = paths["job"]
    assert isinstance(job, Path)
    # Check the original input *before* modifying an existing job, including
    # its run configuration, page images, OCR JSON, or stage logs.
    max_pixels = positive_int(os.environ.get("PADDLE_MAX_PIXELS", "25000000"), "PADDLE_MAX_PIXELS")
    long_edge = positive_int(os.environ.get("PADDLE_TARGET_LONG_EDGE_PX", "3400"), "PADDLE_TARGET_LONG_EDGE_PX")
    normalize_pdf = os.environ.get("PADDLE_NORMALIZE_PDF", "1") == "1"
    identity = input_identity(
        input_path, dpi=dpi, normalize_pdf=normalize_pdf,
        max_pixels=max_pixels, long_edge=long_edge,
    )
    validate_job_identity(job, identity)
    for key in ("preprocessed", "pages", "ocr", "output", "pdf_pages", "logs"):
        folder = paths[key]
        assert isinstance(folder, Path)
        folder.mkdir(parents=True, exist_ok=True)
    logs = paths["logs"]
    assert isinstance(logs, Path)
    started = dt.datetime.now()
    start_perf = time.monotonic()
    status = 1

    def path(key: str) -> Path:
        result = paths[key]
        assert isinstance(result, Path)
        return result

    try:
        dpi_str = str(dpi)
        normalized_input = input_path
        input_kind = "original"
        overwrite = os.environ.get("PADDLE_OVERWRITE", "0") == "1"
        (logs / INPUT_IDENTITY_FILENAME).write_text(
            json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if normalize_pdf and input_path.is_file() and input_path.suffix.lower() == ".pdf":
            normalized_input = path("preprocessed") / f"{paths['prefix']}_ocrsafe_{long_edge}px.pdf"
            if not normalized_input.is_file():
                run_stage(
                    "00_normalize_pdf",
                    [str(helper), str(root / "tools/normalize_pdf_for_ocr.py"),
                     str(input_path), str(normalized_input), "--dpi", dpi_str,
                     "--max-pixels", str(max_pixels), "--target-long-edge-px", str(long_edge)],
                    logs,
                )
            else:
                print(f"[00_normalize_pdf] skip: {normalized_input}", flush=True)
                (logs / "00_normalize_pdf.log").write_text(
                    f"[00_normalize_pdf] skip: {normalized_input}\n", encoding="utf-8"
                )
            input_kind = "normalized_pdf"

        config = {
            "INPUT_ABS": input_path, "PREP_INPUT": normalized_input,
            "PREP_INPUT_KIND": input_kind, "JOB_NAME": paths["name"],
            "JOB_DIR": job, "DPI": dpi,
            "PADDLE_NORMALIZE_PDF": os.environ.get("PADDLE_NORMALIZE_PDF", "1"),
            "PADDLE_MAX_PIXELS": max_pixels, "PADDLE_TARGET_LONG_EDGE_PX": long_edge,
            "PADDLE_OVERWRITE": os.environ.get("PADDLE_OVERWRITE", "0"),
            "PADDLE_PY": paddle, "HELPER_PY": helper,
            "MERGED_PDF": path("merged"), "SMALL_PDF": path("small"),
        }
        (logs / "00_run_config.txt").write_text(
            "".join(f"{key}={value}\n" for key, value in config.items()), encoding="utf-8"
        )

        sentinel = path("pages") / ".complete"
        if not sentinel.is_file():
            for old in path("pages").glob("page_*.png"):
                old.unlink()
            run_stage(
                "01_prepare_pages",
                [str(helper), str(root / "code/prepare_input_pages.py"),
                 str(normalized_input), str(path("pages")), "--dpi", dpi_str],
                logs,
            )
            sentinel.touch()
        else:
            msg = "[01_prepare_pages] skip: completed page images exist"
            print(msg, flush=True)
            (logs / "01_prepare_pages.log").write_text(msg + "\n", encoding="utf-8")

        ocr_env = os.environ.copy()
        ocr_env.update({
            "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "2",
            "VECLIB_MAXIMUM_THREADS": "2", "MKL_NUM_THREADS": "2",
            "NUMEXPR_NUM_THREADS": "2",
        })
        ocr_command = [
            str(paddle), str(root / "paddle_batch_ocr.py"),
            "--pages-dir", str(path("pages")), "--output-dir", str(path("ocr")),
        ]
        if overwrite:
            ocr_command.append("--overwrite")
        run_stage("02_paddle_ocr", ocr_command, logs, env=ocr_env)
        run_stage(
            "03_aggregate_outputs",
            [str(helper), str(root / "code/aggregate_paddle_outputs.py"),
             str(path("ocr")), str(path("output")), "--prefix", str(paths["prefix"])],
            logs,
        )

        print("\n=== 04_searchable_pdf_pages ===", flush=True)
        page_log = logs / "04_searchable_pdf_pages.log"
        with page_log.open("w", encoding="utf-8") as log:
            for old in path("pdf_pages").glob("page_*.pdf"):
                old.unlink()
            images = sorted(path("pages").glob("page_*.png"))
            if not images:
                raise PipelineError(f"ページ画像がありません: {path('pages')}")
            for image in images:
                json_path = path("json") / f"{image.stem}_paddle_small.json"
                if not json_path.is_file():
                    raise PipelineError(f"JSONがありません: {json_path}")
                pdf_path = path("pdf_pages") / f"{image.stem}.pdf"
                command = [str(helper), str(root / "paddle_json_to_searchable_pdf.py"),
                           "--image", str(image), "--json", str(json_path),
                           "--out", str(pdf_path)]
                print("[COMMAND] " + " ".join(command), flush=True)
                log.write("[COMMAND] " + " ".join(command) + "\n")
                # Keep the complete per-page renderer output in the stage log.
                with subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    env=python_child_env(),
                ) as process:
                    assert process.stdout is not None
                    for line in process.stdout:
                        print(line, end="", flush=True)
                        log.write(line)
                    if process.wait():
                        raise PipelineError(
                            f"04_searchable_pdf_pages failed: {image.name}; log={page_log}"
                        )
            msg = f"[DONE] page PDFs: {len(images)}"
            print(msg, flush=True)
            log.write(msg + "\n")

        for label, command in (
            ("05_merge_pdf", [str(helper), str(root / "code/merge_pdfs.py"),
                              str(path("pdf_pages")), str(path("merged"))]),
            ("06_verify_pdf", [str(helper), str(root / "code/verify_searchable_pdf.py"),
                               str(path("merged"))]),
            ("07_compress_pdf", [str(helper), str(root / "code/compress_pdf_150dpi.py"),
                                 str(path("merged")), str(path("small"))]),
        ):
            run_stage(label, command, logs)
        status = 0
        print("\n=== PADDLEOCR PIPELINE FINISHED ===", flush=True)
        for key in ("job", "pages", "json", "txt", "output", "pdf_pages", "merged", "small", "logs"):
            print(f"{key.upper():<18}: {path(key)}", flush=True)
    finally:
        ended = dt.datetime.now()
        seconds = int(time.monotonic() - start_perf)
        (logs / "timing_summary.log").write_text(
            f"status={status}\nstart={started:%Y-%m-%d %H:%M:%S}\n"
            f"end={ended:%Y-%m-%d %H:%M:%S}\nelapsed_seconds={seconds}\n"
            f"elapsed_hms={seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}\n"
            f"script={Path(__file__).name}\nargs={input_path}\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Experimental Python entry point; existing Bash CLI remains supported."
    )
    parser.add_argument("input_path", help="PDF, image, or directory containing page images")
    parser.add_argument("job_name", nargs="?", help="Optional job name")
    parser.add_argument("dpi", nargs="?", type=lambda v: positive_int(v, "dpi"), default=180)
    parser.add_argument(
        "--check", action="store_true",
        help="Check input, Python interpreters and PDF fonts without creating a job",
    )
    args = parser.parse_args(argv)
    input_path = Path(args.input_path).expanduser().resolve()
    if not input_path.exists():
        parser.error(f"入力が見つかりません: {input_path}")
    try:
        paddle, helper = resolve_interpreters(ROOT)
        print(f"[INFO] Paddle Python: {paddle}", flush=True)
        print(f"[INFO] Helper Python: {helper}", flush=True)
        fonts = check_fonts(ROOT, helper)
        for font in fonts:
            print(f"[INFO] PDF font: {font}")
        if args.check:
            print("[OK] preflight completed; no job created")
            return 0
        paths = paths_for(input_path, ROOT, args.job_name, dt.datetime.now())
        run_pipeline(input_path, ROOT, paths, paddle, helper, args.dpi)
        return 0
    except (PipelineError, OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
