#!/usr/bin/env python3
"""Create and verify a PaddleOCR output ZIP without deleting source files."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import zipfile
from pathlib import Path

from pypdf import PdfReader


def require_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"Missing or unsafe file: {path}")
    return path


def file_digest(stream) -> bytes:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.digest()


def collect_files(job: Path, stem: str) -> dict[str, Path]:
    """Collect known OCR outputs and logs; do not collect page images/PDFs."""
    files: dict[str, Path] = {}

    def add(path: Path) -> None:
        source = require_file(path)
        relative = source.relative_to(job).as_posix()
        if relative in files:
            raise RuntimeError(f"Duplicate archive member: {relative}")
        files[relative] = source

    pages_dir = job / "pages"
    if pages_dir.is_symlink() or not pages_dir.is_dir():
        raise RuntimeError(f"Missing or unsafe page directory: {pages_dir}")

    images = sorted(pages_dir.glob("page_*.png"))
    if not images:
        raise RuntimeError("No page images found")

    page_stems: list[str] = []
    for image in images:
        require_file(image)
        if not re.fullmatch(r"page_[0-9]{4,}", image.stem):
            raise RuntimeError(f"Unexpected page image name: {image.name}")
        page_stems.append(image.stem)

    if len(set(page_stems)) != len(page_stems):
        raise RuntimeError("Duplicate page identifiers")

    # Page images define the expected page set. Reject missing,
    # extra and incorrectly named page-related OCR/PDF files.
    expected_page_files = (
        (
            job / "paddle_ocr" / "json",
            {f"{stem}_paddle_small.json" for stem in page_stems},
        ),
        (
            job / "paddle_ocr" / "txt",
            {f"{stem}_paddle_small.txt" for stem in page_stems},
        ),
        (
            job / "searchable_pdf" / "pages_pdf",
            {f"{stem}.pdf" for stem in page_stems},
        ),
    )

    for directory, expected_names in expected_page_files:
        actual = list(directory.glob("page_*"))
        for item in actual:
            require_file(item)

        actual_names = {item.name for item in actual}
        if actual_names != expected_names:
            missing = sorted(expected_names - actual_names)
            extra = sorted(actual_names - expected_names)
            raise RuntimeError(
                f"Page file mismatch in {directory}: "
                f"missing={missing}, extra={extra}"
            )

    for page_stem in page_stems:
        add(
            job / "paddle_ocr" / "json"
            / f"{page_stem}_paddle_small.json"
        )
        add(
            job / "paddle_ocr" / "txt"
            / f"{page_stem}_paddle_small.txt"
        )
        require_file(
            job / "searchable_pdf" / "pages_pdf"
            / f"{page_stem}.pdf"
        )

    add(job / "paddle_ocr" / "paddle_batch_summary.csv")

    for name in (
        f"{stem}_paddle.txt",
        f"{stem}_paddle.md",
        f"{stem}_paddle.json",
        f"{stem}_paddle_pages.jsonl",
    ):
        add(job / "output" / name)

    fallback_dir = job / "paddle_ocr" / "font_fallback_report"
    if fallback_dir.exists() or fallback_dir.is_symlink():
        if fallback_dir.is_symlink() or not fallback_dir.is_dir():
            raise RuntimeError(f"Unsafe fallback directory: {fallback_dir}")
        for path in sorted(fallback_dir.rglob("*")):
            if path.is_symlink():
                raise RuntimeError(f"Symlink in fallback records: {path}")
            if path.is_file():
                add(path)

    logs_dir = job / "logs"
    if logs_dir.is_symlink() or not logs_dir.is_dir():
        raise RuntimeError(f"Missing or unsafe logs directory: {logs_dir}")

    for name in (
        "00_input_identity.json",
        "00_run_config.txt",
        "06_verify_pdf.log",
        "timing_summary.log",
    ):
        add(logs_dir / name)

    for path in sorted(logs_dir.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Symlink in logs: {path}")
        if path.is_file():
            relative = path.relative_to(job).as_posix()
            if relative == "logs/finalization_status.log":
                # Overall job status is written after ZIP publication.
                # It must remain outside the immutable archive.
                continue
            if relative not in files:
                add(path)

    return files


def verify_pdf(job: Path, stem: str, expected_pages: int) -> None:
    pdf_path = require_file(
        job / "searchable_pdf" / f"{stem}_paddleocr_searchable.pdf"
    )
    reader = PdfReader(str(pdf_path))

    if len(reader.pages) != expected_pages:
        raise RuntimeError(
            f"PDF page count mismatch: "
            f"{len(reader.pages)} != {expected_pages}"
        )

    if not any((page.extract_text() or "").strip() for page in reader.pages):
        raise RuntimeError("Searchable PDF has no extractable text")


def verify_optional_pdf(
    job: Path, stem: str, *, require_compressed: bool
) -> None:
    """Require an explicitly requested 150-dpi PDF with matching page text."""
    compressed = (
        job / "searchable_pdf"
        / f"{stem}_paddleocr_searchable_small_150dpi.pdf"
    )

    if not require_compressed:
        if compressed.exists() or compressed.is_symlink():
            raise RuntimeError(
                f"Unexpected 150-dpi PDF without explicit request: {compressed}"
            )
        return

    require_file(compressed)

    normal = require_file(
        job / "searchable_pdf" / f"{stem}_paddleocr_searchable.pdf"
    )
    normal_pages = PdfReader(str(normal)).pages
    compressed_pages = PdfReader(str(compressed)).pages

    if len(compressed_pages) != len(normal_pages):
        raise RuntimeError(
            "150-dpi PDF page count differs from the normal PDF"
        )

    for index, (normal_page, compressed_page) in enumerate(
        zip(normal_pages, compressed_pages), start=1
    ):
        normal_text = "".join(
            (normal_page.extract_text() or "").split()
        )
        compressed_text = "".join(
            (compressed_page.extract_text() or "").split()
        )

        if normal_text != compressed_text:
            raise RuntimeError(
                f"150-dpi PDF extracted text differs on page {index}"
            )


def create_verified_bundle(
    job: Path, stem: str, *, require_compressed: bool = False
) -> Path:
    """Verify and publish a ZIP. Never remove source files."""
    job = Path(job).absolute()

    if job.is_symlink() or not job.is_dir():
        raise RuntimeError(f"Missing or unsafe job directory: {job}")

    if (
        not stem
        or stem in (".", "..")
        or "/" in stem
        or "\\" in stem
    ):
        raise ValueError(f"Invalid output stem: {stem!r}")

    archive = job / f"{stem}_ocr_bundle.zip"

    if archive.exists() or archive.is_symlink():
        raise FileExistsError(f"Archive already exists: {archive}")

    # Do not follow symlinked directories when collecting job outputs.
    for relative in (
        "pages",
        "paddle_ocr",
        "paddle_ocr/json",
        "paddle_ocr/txt",
        "output",
        "searchable_pdf",
        "searchable_pdf/pages_pdf",
        "logs",
    ):
        directory = job / relative
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError(
                f"Missing or unsafe job directory: {directory}"
            )

    files = collect_files(job, stem)

    page_count = sum(
        name.startswith("paddle_ocr/json/page_")
        and name.endswith("_paddle_small.json")
        for name in files
    )
    verify_pdf(job, stem, page_count)
    verify_optional_pdf(
        job, stem, require_compressed=require_compressed
    )

    with tempfile.NamedTemporaryFile(
        prefix="._paddle_bundle_",
        suffix=".tmp",
        dir=job,
        delete=False,
    ) as temporary:
        temp_path = Path(temporary.name)

    try:
        with zipfile.ZipFile(
            temp_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as bundle:
            for name, source in sorted(files.items()):
                bundle.write(source, arcname=name)

        with zipfile.ZipFile(temp_path, "r") as bundle:
            if set(bundle.namelist()) != set(files):
                raise RuntimeError("ZIP member list mismatch")

            if len(bundle.namelist()) != len(files):
                raise RuntimeError("ZIP has duplicate members")

            if bundle.testzip() is not None:
                raise RuntimeError("ZIP integrity verification failed")

            for name, source in files.items():
                with source.open("rb") as original:
                    original_digest = file_digest(original)
                with bundle.open(name, "r") as archived:
                    archived_digest = file_digest(archived)

                if original_digest != archived_digest:
                    raise RuntimeError(f"ZIP source mismatch: {name}")

        # Same-directory hard link publishes without replacing an
        # archive that may have appeared after the initial check.
        os.link(temp_path, archive)

    finally:
        temp_path.unlink(missing_ok=True)

    return archive


def cleanup_targets(job: Path, stem: str) -> list[Path]:
    """Plan deletion of explicitly recognized generated files only.

    Validate every target before ZIP publication. Unknown files are
    deliberately excluded from the cleanup plan.
    """
    directories = (
        job,
        job / "pages",
        job / "paddle_ocr",
        job / "paddle_ocr" / "json",
        job / "paddle_ocr" / "txt",
        job / "output",
        job / "searchable_pdf",
        job / "searchable_pdf" / "pages_pdf",
    )

    for directory in directories:
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError(
                f"Missing or unsafe cleanup directory: {directory}"
            )

    preprocessed = job / "preprocessed"
    if preprocessed.is_symlink() or (
        preprocessed.exists() and not preprocessed.is_dir()
    ):
        raise RuntimeError(
            f"Unsafe preprocessed directory: {preprocessed}"
        )

    images = sorted((job / "pages").glob("page_*.png"))
    if not images:
        raise RuntimeError("No generated page images to finalize")

    targets = [
        job / "paddle_ocr" / "paddle_batch_summary.csv",
        job / "output" / f"{stem}_paddle.txt",
        job / "output" / f"{stem}_paddle.md",
        job / "output" / f"{stem}_paddle.json",
        job / "output" / f"{stem}_paddle_pages.jsonl",
    ]

    for image in images:
        targets.extend(
            (
                image,
                job / "paddle_ocr" / "json"
                / f"{image.stem}_paddle_small.json",
                job / "paddle_ocr" / "txt"
                / f"{image.stem}_paddle_small.txt",
                job / "searchable_pdf" / "pages_pdf"
                / f"{image.stem}.pdf",
            )
        )

    # .complete is a generated marker, but an older job may lack it.
    sentinel = job / "pages" / ".complete"
    if sentinel.exists() or sentinel.is_symlink():
        targets.append(sentinel)

    if preprocessed.is_dir():
        for candidate in sorted(
            preprocessed.glob(f"{stem}_ocrsafe_*px.pdf")
        ):
            if re.fullmatch(
                rf"{re.escape(stem)}_ocrsafe_[1-9][0-9]*px[.]pdf",
                candidate.name,
            ):
                targets.append(candidate)

    if len(targets) != len(set(targets)):
        raise RuntimeError("Duplicate cleanup target")

    for target in targets:
        require_file(target)

    return targets


def cleanup_empty_intermediate_directories(job: Path) -> None:
    """Remove known intermediate directories, only if empty."""

    import errno

    directories = (
        job / "pages",
        job / "paddle_ocr" / "json",
        job / "paddle_ocr" / "txt",
        job / "paddle_ocr" / "font_fallback_report",
        job / "searchable_pdf" / "pages_pdf",
        job / "preprocessed",
        job / "output",
        job / "paddle_ocr",
    )

    for directory in directories:
        if directory.is_symlink():
            raise RuntimeError(
                f"Unsafe cleanup directory: {directory}"
            )

        if not directory.exists():
            continue

        if not directory.is_dir():
            raise RuntimeError(
                f"Cleanup path is not a directory: {directory}"
            )

        try:
            directory.rmdir()
        except OSError as exc:
            if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise


def finalize_outputs(
    job: Path,
    stem: str,
    *,
    keep_intermediates: bool = False,
    require_compressed: bool = False,
) -> Path:
    """Publish a verified bundle, then optionally remove known intermediates.

    Normalized working PDFs and empty intermediate directories are
    removed after ZIP publication. Original input files, final PDFs,
    logs, and unknown files are not cleanup targets.
    """
    job = Path(job).absolute()

    if keep_intermediates:
        return create_verified_bundle(
            job, stem, require_compressed=require_compressed
        )

    # A missing or unsafe target must fail before publishing the ZIP.
    targets = cleanup_targets(job, stem)

    archive = create_verified_bundle(
        job, stem, require_compressed=require_compressed
    )

    # Repeat target checks before the first deletion. A concurrent
    # filesystem change cannot be made fully atomic here; the caller
    # must not treat a partial cleanup failure as a reusable job.
    cleanup_targets(job, stem)

    for target in targets:
        require_file(target)
        target.unlink()

    cleanup_empty_intermediate_directories(job)

    return archive


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Create a verified OCR bundle and optionally clean up"
    )
    parser.add_argument("job_dir")
    parser.add_argument("stem")
    parser.add_argument("--keep-intermediates", action="store_true")
    parser.add_argument("--require-compressed", action="store_true")
    args = parser.parse_args(argv)

    archive = finalize_outputs(
        Path(args.job_dir),
        args.stem,
        keep_intermediates=args.keep_intermediates,
        require_compressed=args.require_compressed,
    )
    print(f"[OUTPUT_FINALIZE] verified ZIP: {archive}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
