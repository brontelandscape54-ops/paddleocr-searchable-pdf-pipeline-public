"""Contract tests for PaddleOCR output bundling, before cleanup is added."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import paddleocr_cli as cli

from reportlab.pdfgen import canvas


STEM = "sample"


def write_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write_pdf(path: Path, *, pages: int = 1, with_text: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    for page_number in range(pages):
        if with_text:
            pdf.drawString(72, 720, f"SEARCHABLE PAGE {page_number + 1}")
        pdf.showPage()
    pdf.save()
    return path


class PaddleOutputBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.root = Path(temporary.name)
        self.job = self.root / "jobs" / "sample_job"
        self.archive = self.job / f"{STEM}_ocr_bundle.zip"

        self.original_input = write_file(
            self.root / "original_input.pdf",
            b"ORIGINAL INPUT MUST REMAIN UNCHANGED",
        )

        self.page_image = write_file(
            self.job / "pages" / "page_0001.png",
            b"synthetic intermediate image",
        )
        self.page_json = write_file(
            self.job / "paddle_ocr" / "json"
            / "page_0001_paddle_small.json",
            b'{"page":1,"text":"SAMPLE"}',
        )
        self.page_txt = write_file(
            self.job / "paddle_ocr" / "txt"
            / "page_0001_paddle_small.txt",
            b"SAMPLE\n",
        )
        write_file(
            self.job / "paddle_ocr" / "paddle_batch_summary.csv",
            b"page,status\npage_0001.png,ok\n",
        )

        for extension, data in (
            ("txt", b"SAMPLE\n"),
            ("md", b"# SAMPLE\n"),
            ("json", b'[{"page":1}]'),
            ("jsonl", b'{"page":1}\n'),
        ):
            filename = (
                f"{STEM}_paddle_pages.jsonl"
                if extension == "jsonl"
                else f"{STEM}_paddle.{extension}"
            )
            write_file(
                self.job / "output" / filename,
                data,
            )

        self.normal_pdf = write_pdf(
            self.job / "searchable_pdf"
            / f"{STEM}_paddleocr_searchable.pdf"
        )
        self.page_pdf = write_pdf(
            self.job / "searchable_pdf" / "pages_pdf"
            / "page_0001.pdf"
        )

        write_file(
            self.job / "logs" / "00_input_identity.json",
            b'{"input":"synthetic"}\n',
        )
        write_file(
            self.job / "logs" / "00_run_config.txt",
            b"DPI=180\n",
        )
        write_file(
            self.job / "logs" / "06_verify_pdf.log",
            b"[OK] pages: 1\n",
        )
        write_file(
            self.job / "logs" / "timing_summary.log",
            b"status=0\n",
        )

    def build_bundle(self, *, require_compressed=False):
        from tools.finalize_paddle_outputs import create_verified_bundle

        return create_verified_bundle(
            self.job, STEM, require_compressed=require_compressed
        )

    def test_default_finalization_removes_normalized_pdf_and_empty_dirs(self):
        from tools.finalize_paddle_outputs import finalize_outputs

        normalized = write_file(
            self.job / "preprocessed" / "sample_ocrsafe_3400px.pdf",
            b"SYNTHETIC NORMALIZED WORKING PDF",
        )

        result = finalize_outputs(self.job, STEM)

        self.assertEqual(result, self.archive)
        self.assertTrue(self.archive.is_file())
        self.assertTrue(self.normal_pdf.is_file())
        self.assertTrue(self.original_input.is_file())
        self.assertFalse(normalized.exists())

        for relative in (
            "preprocessed",
            "pages",
            "paddle_ocr/json",
            "paddle_ocr/txt",
            "paddle_ocr",
            "output",
            "searchable_pdf/pages_pdf",
        ):
            with self.subTest(directory=relative):
                self.assertFalse(
                    (self.job / relative).exists(),
                    f"Intermediate directory still exists: {relative}",
                )

        self.assertTrue((self.job / "logs").is_dir())
        self.assertTrue((self.job / "searchable_pdf").is_dir())

        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertFalse(
                any(
                    name.startswith("preprocessed/")
                    for name in bundle.namelist()
                )
            )

    def test_keep_intermediates_retains_normalized_pdf_and_dirs(self):
        from tools.finalize_paddle_outputs import finalize_outputs

        normalized = write_file(
            self.job / "preprocessed" / "sample_ocrsafe_3400px.pdf",
            b"SYNTHETIC NORMALIZED WORKING PDF",
        )

        result = finalize_outputs(
            self.job, STEM, keep_intermediates=True
        )

        self.assertEqual(result, self.archive)
        self.assertTrue(normalized.is_file())
        self.assertTrue(self.page_image.is_file())
        self.assertTrue(self.page_json.is_file())
        self.assertTrue(self.page_pdf.is_file())
        self.assertTrue((self.job / "pages").is_dir())
        self.assertTrue((self.job / "output").is_dir())

    def test_unknown_files_prevent_directory_removal(self):
        from tools.finalize_paddle_outputs import finalize_outputs

        normalized = write_file(
            self.job / "preprocessed" / "sample_ocrsafe_3400px.pdf",
            b"SYNTHETIC NORMALIZED WORKING PDF",
        )
        unknown_preprocessed = write_file(
            self.job / "preprocessed" / "user_notes.txt",
            b"DO NOT DELETE",
        )
        unknown_pages = write_file(
            self.job / "pages" / "user_notes.txt",
            b"DO NOT DELETE",
        )

        result = finalize_outputs(self.job, STEM)

        self.assertEqual(result, self.archive)
        self.assertFalse(normalized.exists())
        self.assertTrue(unknown_preprocessed.is_file())
        self.assertTrue(unknown_pages.is_file())
        self.assertEqual(
            unknown_preprocessed.read_bytes(), b"DO NOT DELETE"
        )
        self.assertEqual(
            unknown_pages.read_bytes(), b"DO NOT DELETE"
        )
        self.assertTrue((self.job / "preprocessed").is_dir())
        self.assertTrue((self.job / "pages").is_dir())
        self.assertFalse(self.page_image.exists())
        self.assertTrue(self.original_input.is_file())

    def test_symlinked_preprocessed_directory_fails_before_zip(self):
        from tools.finalize_paddle_outputs import finalize_outputs

        outside = self.root / "outside"
        outside.mkdir()
        protected = write_file(
            outside / "protected.txt", b"DO NOT DELETE"
        )
        (self.job / "preprocessed").symlink_to(
            outside, target_is_directory=True
        )

        with self.assertRaisesRegex(
            RuntimeError, "preprocessed"
        ):
            finalize_outputs(self.job, STEM)

        self.assertFalse(self.archive.exists())
        self.assertTrue(self.page_image.is_file())
        self.assertEqual(
            protected.read_bytes(), b"DO NOT DELETE"
        )

    def test_archive_contains_ocr_outputs_and_logs_but_no_pdf(self):
        result = self.build_bundle()

        self.assertEqual(result, self.archive)
        self.assertTrue(self.archive.is_file())

        with zipfile.ZipFile(self.archive) as bundle:
            names = set(bundle.namelist())
            self.assertIsNone(bundle.testzip())

            self.assertIn(
                "paddle_ocr/json/page_0001_paddle_small.json", names
            )
            self.assertIn(
                "paddle_ocr/txt/page_0001_paddle_small.txt", names
            )
            self.assertIn(
                "paddle_ocr/paddle_batch_summary.csv", names
            )

            for filename in (
                f"{STEM}_paddle.txt",
                f"{STEM}_paddle.md",
                f"{STEM}_paddle.json",
                f"{STEM}_paddle_pages.jsonl",
            ):
                self.assertIn(f"output/{filename}", names)

            self.assertIn("logs/00_input_identity.json", names)
            self.assertIn("logs/00_run_config.txt", names)
            self.assertIn("logs/06_verify_pdf.log", names)
            self.assertIn("logs/timing_summary.log", names)

            self.assertFalse(
                any(name.endswith((".pdf", ".png")) for name in names)
            )

        # この段階では、ZIP化の成功後も中間ファイルを削除しない。
        for path in (
            self.original_input,
            self.page_image,
            self.page_json,
            self.page_txt,
            self.normal_pdf,
            self.page_pdf,
        ):
            self.assertTrue(path.is_file())

        self.assertEqual(
            self.original_input.read_bytes(),
            b"ORIGINAL INPUT MUST REMAIN UNCHANGED",
        )

    def test_symlinked_output_directory_is_rejected(self):
        outside = self.root / "outside_job_outputs"
        (self.job / "output").rename(outside)

        try:
            (self.job / "output").symlink_to(
                outside, target_is_directory=True
            )
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Directory symlinks unavailable: {exc}")

        with self.assertRaises(RuntimeError):
            self.build_bundle()

        self.assertFalse(self.archive.exists())
        self.assertTrue(
            (outside / f"{STEM}_paddle.txt").is_file()
        )
        self.assertTrue(self.page_image.is_file())

    def test_extra_page_json_is_rejected(self):
        extra = write_file(
            self.job / "paddle_ocr" / "json"
            / "page_0002_paddle_small.json",
            b'{"page":2}',
        )

        with self.assertRaises(RuntimeError):
            self.build_bundle()

        self.assertFalse(self.archive.exists())
        self.assertTrue(extra.is_file())
        self.assertTrue(self.page_image.is_file())

    def test_extra_page_txt_is_rejected(self):
        extra = write_file(
            self.job / "paddle_ocr" / "txt"
            / "page_0002_paddle_small.txt",
            b"EXTRA PAGE\\n",
        )

        with self.assertRaises(RuntimeError):
            self.build_bundle()

        self.assertFalse(self.archive.exists())
        self.assertTrue(extra.is_file())
        self.assertTrue(self.page_json.is_file())

    def test_extra_page_pdf_is_rejected(self):
        extra = write_pdf(
            self.job / "searchable_pdf" / "pages_pdf"
            / "page_0002.pdf",
        )

        with self.assertRaises(RuntimeError):
            self.build_bundle()

        self.assertFalse(self.archive.exists())
        self.assertTrue(extra.is_file())
        self.assertTrue(self.normal_pdf.is_file())

    def test_requested_compressed_pdf_is_retained_outside_zip(self):
        small = write_pdf(
            self.job / "searchable_pdf"
            / f"{STEM}_paddleocr_searchable_small_150dpi.pdf",
        )

        result = self.build_bundle(require_compressed=True)

        self.assertEqual(result, self.archive)
        self.assertTrue(self.normal_pdf.is_file())
        self.assertTrue(small.is_file())

        with zipfile.ZipFile(self.archive) as bundle:
            self.assertFalse(
                any(name.endswith(".pdf") for name in bundle.namelist())
            )

    def test_requested_compressed_pdf_must_exist(self):
        with self.assertRaises((RuntimeError, FileNotFoundError)):
            self.build_bundle(require_compressed=True)

        self.assertFalse(self.archive.exists())
        self.assertTrue(self.page_image.is_file())
        self.assertTrue(self.normal_pdf.is_file())

    def test_unrequested_compressed_pdf_is_rejected(self):
        small = write_pdf(
            self.job / "searchable_pdf"
            / f"{STEM}_paddleocr_searchable_small_150dpi.pdf",
        )

        with self.assertRaises(RuntimeError):
            self.build_bundle()

        self.assertFalse(self.archive.exists())
        self.assertTrue(small.is_file())
        self.assertTrue(self.page_image.is_file())

    def test_compressed_pdf_page_count_mismatch_is_rejected(self):
        small = write_pdf(
            self.job / "searchable_pdf"
            / f"{STEM}_paddleocr_searchable_small_150dpi.pdf",
            pages=2,
        )

        with self.assertRaises(RuntimeError):
            self.build_bundle(require_compressed=True)

        self.assertFalse(self.archive.exists())
        self.assertTrue(small.is_file())
        self.assertTrue(self.page_json.is_file())

    def test_compressed_pdf_text_mismatch_is_rejected(self):
        small = self.job / "searchable_pdf" / (
            f"{STEM}_paddleocr_searchable_small_150dpi.pdf"
        )
        small.parent.mkdir(parents=True, exist_ok=True)

        pdf = canvas.Canvas(str(small))
        pdf.drawString(72, 720, "DIFFERENT SEARCHABLE TEXT")
        pdf.showPage()
        pdf.save()

        with self.assertRaises(RuntimeError):
            self.build_bundle(require_compressed=True)

        self.assertFalse(self.archive.exists())
        self.assertTrue(small.is_file())
        self.assertTrue(self.page_txt.is_file())

    def finalize_job(self, *, keep_intermediates=False):
        # この関数は次の実装段階で追加する。
        from tools.finalize_paddle_outputs import finalize_outputs

        return finalize_outputs(
            self.job,
            STEM,
            keep_intermediates=keep_intermediates,
        )

    def test_default_cleanup_removes_known_intermediates_after_zip(self):
        sentinel = write_file(
            self.job / "pages" / ".complete",
            b"",
        )

        result = self.finalize_job()

        self.assertEqual(result, self.archive)
        self.assertTrue(self.archive.is_file())
        self.assertTrue(self.normal_pdf.is_file())
        self.assertTrue(
            (self.job / "logs" / "timing_summary.log").is_file()
        )
        self.assertTrue(self.original_input.is_file())

        for removed in (
            self.page_image,
            self.page_json,
            self.page_txt,
            self.page_pdf,
            sentinel,
            self.job / "paddle_ocr" / "paddle_batch_summary.csv",
            self.job / "output" / f"{STEM}_paddle.txt",
            self.job / "output" / f"{STEM}_paddle.md",
            self.job / "output" / f"{STEM}_paddle.json",
            self.job / "output" / f"{STEM}_paddle_pages.jsonl",
        ):
            self.assertFalse(
                removed.exists(),
                f"Known intermediate was not removed: {removed}",
            )

        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertEqual(
                bundle.read(
                    "paddle_ocr/json/page_0001_paddle_small.json"
                ),
                b'{"page":1,"text":"SAMPLE"}',
            )

    def test_keep_intermediates_still_creates_verified_zip(self):
        sentinel = write_file(
            self.job / "pages" / ".complete",
            b"",
        )

        result = self.finalize_job(keep_intermediates=True)

        self.assertEqual(result, self.archive)
        self.assertTrue(self.archive.is_file())

        for retained in (
            self.original_input,
            self.normal_pdf,
            self.page_image,
            self.page_json,
            self.page_txt,
            self.page_pdf,
            sentinel,
            self.job / "output" / f"{STEM}_paddle.txt",
            self.job / "logs" / "timing_summary.log",
        ):
            self.assertTrue(
                retained.is_file(),
                f"File should have been retained: {retained}",
            )

        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())

    def test_cleanup_failure_after_zip_preserves_deliverables(self):
        from unittest import mock

        unknown = write_file(
            self.job / "pages" / "user_note.txt",
            b"KEEP UNKNOWN FILE",
        )
        original_unlink = Path.unlink

        def refuse_page_image_unlink(target, *args, **kwargs):
            if target == self.page_image:
                raise PermissionError("synthetic cleanup failure")
            return original_unlink(target, *args, **kwargs)

        with mock.patch.object(
            Path, "unlink", new=refuse_page_image_unlink
        ):
            with self.assertRaisesRegex(
                PermissionError, "synthetic cleanup failure"
            ):
                self.finalize_job()

        # The ZIP was verified and published before deletion began.
        self.assertTrue(self.archive.is_file())
        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertEqual(
                bundle.read("output/sample_paddle.txt"),
                b"SAMPLE\n",
            )
            self.assertEqual(
                bundle.read(
                    "paddle_ocr/json/page_0001_paddle_small.json"
                ),
                b'{"page":1,"text":"SAMPLE"}',
            )

        # An unsuccessful cleanup must not remove primary deliverables,
        # user input, unknown files or files not yet reached.
        self.assertTrue(self.normal_pdf.is_file())
        self.assertTrue(self.original_input.is_file())
        self.assertTrue(
            (self.job / "logs" / "timing_summary.log").is_file()
        )
        self.assertEqual(unknown.read_bytes(), b"KEEP UNKNOWN FILE")
        # Cleanup reached the injected failure after deleting earlier
        # targets. The remaining files and verified ZIP must be protected.
        self.assertFalse(
            (self.job / "paddle_ocr" / "paddle_batch_summary.csv").exists()
        )
        self.assertFalse(
            (self.job / "output" / f"{STEM}_paddle.txt").exists()
        )
        self.assertTrue(self.page_image.is_file())
        self.assertTrue(self.page_json.is_file())

    def test_failed_finalization_preserves_intermediates(self):
        self.page_txt.unlink()

        with self.assertRaises(
            (RuntimeError, ValueError, FileNotFoundError)
        ):
            self.finalize_job()

        self.assertFalse(self.archive.exists())
        self.assertTrue(self.page_image.is_file())
        self.assertTrue(self.page_json.is_file())
        self.assertTrue(self.page_pdf.is_file())
        self.assertTrue(self.normal_pdf.is_file())
        self.assertTrue(self.original_input.is_file())

    def test_cleanup_preserves_unknown_files(self):
        unknown_page = write_file(
            self.job / "pages" / "user_note.txt",
            b"KEEP UNKNOWN PAGE FILE",
        )
        unknown_ocr = write_file(
            self.job / "paddle_ocr" / "json" / "user_note.txt",
            b"KEEP UNKNOWN OCR FILE",
        )

        result = self.finalize_job()

        self.assertEqual(result, self.archive)
        self.assertTrue(self.archive.is_file())

        self.assertEqual(
            unknown_page.read_bytes(), b"KEEP UNKNOWN PAGE FILE"
        )
        self.assertEqual(
            unknown_ocr.read_bytes(), b"KEEP UNKNOWN OCR FILE"
        )

        self.assertFalse(self.page_image.exists())
        self.assertFalse(self.page_json.exists())
        self.assertTrue(self.normal_pdf.is_file())
        self.assertTrue(self.original_input.is_file())

    def test_finalization_status_remains_outside_zip(self):
        status_log = write_file(
            self.job / "logs" / "finalization_status.log",
            b"status=pending\\n",
        )

        result = self.build_bundle()

        self.assertEqual(result, self.archive)
        self.assertEqual(status_log.read_bytes(), b"status=pending\\n")

        with zipfile.ZipFile(self.archive) as bundle:
            names = set(bundle.namelist())
            self.assertNotIn("logs/finalization_status.log", names)
            self.assertIn("logs/timing_summary.log", names)
            self.assertIsNone(bundle.testzip())

    def run_cli_finalization(self, *, keep_intermediates=False):
        return cli.run_finalization(
            self.job,
            STEM,
            Path(__file__).resolve().parents[1],
            Path(sys.executable),
            keep_intermediates=keep_intermediates,
            generate_150dpi_pdf=False,
        )

    def test_cli_finalization_success_cleans_intermediates(self):
        result = self.run_cli_finalization()

        self.assertEqual(result, self.archive)
        self.assertTrue(self.archive.is_file())
        self.assertTrue(self.normal_pdf.is_file())
        self.assertTrue(self.original_input.is_file())
        self.assertFalse(self.page_image.exists())
        self.assertFalse(self.page_json.exists())
        self.assertFalse(self.page_pdf.exists())

        status_log = (
            self.job / "logs" / "finalization_status.log"
        )
        status = status_log.read_text(encoding="utf-8")
        self.assertIn("status=success\n", status)
        self.assertIn("archive_published=1\n", status)
        self.assertIn("keep_intermediates=0\n", status)

        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertNotIn(
                "logs/finalization_status.log",
                bundle.namelist(),
            )
            self.assertIn(
                "logs/timing_summary.log",
                bundle.namelist(),
            )

    def test_cli_finalization_success_keeps_intermediates(self):
        result = self.run_cli_finalization(
            keep_intermediates=True
        )

        self.assertEqual(result, self.archive)
        self.assertTrue(self.archive.is_file())

        for retained in (
            self.original_input,
            self.normal_pdf,
            self.page_image,
            self.page_json,
            self.page_txt,
            self.page_pdf,
        ):
            self.assertTrue(retained.is_file())

        status = (
            self.job / "logs" / "finalization_status.log"
        ).read_text(encoding="utf-8")

        self.assertIn("status=success\n", status)
        self.assertIn("keep_intermediates=1\n", status)

    def test_cli_finalization_failure_before_zip_is_recorded(self):
        self.page_txt.unlink()

        with self.assertRaisesRegex(
            cli.PipelineError, "Finalization failed"
        ):
            self.run_cli_finalization()

        self.assertFalse(self.archive.exists())
        self.assertTrue(self.page_image.is_file())
        self.assertTrue(self.page_json.is_file())
        self.assertTrue(self.normal_pdf.is_file())
        self.assertTrue(self.original_input.is_file())

        status = (
            self.job / "logs" / "finalization_status.log"
        ).read_text(encoding="utf-8")

        self.assertIn("status=failed\n", status)
        self.assertIn("archive_published=0\n", status)

    def test_cli_records_failure_when_zip_exists(self):
        # Verify a real ZIP first. Simulate the nonzero subprocess
        # result of a cleanup failure after archive publication.
        self.build_bundle()

        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="synthetic cleanup failure",
        )

        with mock.patch.object(
            cli.subprocess, "run", return_value=result
        ):
            with self.assertRaisesRegex(
                cli.PipelineError, "Finalization failed"
            ):
                self.run_cli_finalization()

        self.assertTrue(self.archive.is_file())
        self.assertTrue(self.normal_pdf.is_file())

        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())

        status = (
            self.job / "logs" / "finalization_status.log"
        ).read_text(encoding="utf-8")

        self.assertIn("status=failed\n", status)
        self.assertIn("archive_published=1\n", status)
        self.assertIn("synthetic cleanup failure", status)

    def test_cli_rejects_job_with_existing_bundle(self):
        self.build_bundle()

        identity = {"version": 1, "synthetic": True}
        identity_path = (
            self.job / "logs" / "00_input_identity.json"
        )
        identity_path.write_text(
            '{"version": 1, "synthetic": true}',
            encoding="utf-8",
        )

        before_archive = self.archive.read_bytes()
        before_input = self.original_input.read_bytes()

        with self.assertRaisesRegex(
            cli.PipelineError, "ZIP"
        ):
            cli.validate_job_identity(self.job, identity)

        self.assertEqual(
            self.archive.read_bytes(), before_archive
        )
        self.assertEqual(
            self.original_input.read_bytes(), before_input
        )

    def test_missing_page_txt_preserves_intermediates(self):
        self.page_txt.unlink()

        with self.assertRaises((RuntimeError, ValueError, FileNotFoundError)):
            self.build_bundle()

        self.assertFalse(self.archive.exists())
        self.assertTrue(self.page_image.is_file())
        self.assertTrue(self.page_json.is_file())
        self.assertTrue(self.normal_pdf.is_file())

    def test_pdf_page_count_mismatch_preserves_intermediates(self):
        write_pdf(self.normal_pdf, pages=2)

        with self.assertRaises((RuntimeError, ValueError)):
            self.build_bundle()

        self.assertFalse(self.archive.exists())
        self.assertTrue(self.page_image.is_file())
        self.assertTrue(self.page_json.is_file())

    def test_existing_archive_is_never_overwritten(self):
        self.archive.write_bytes(b"EXISTING ARCHIVE")

        with self.assertRaises((RuntimeError, FileExistsError)):
            self.build_bundle()

        self.assertEqual(
            self.archive.read_bytes(),
            b"EXISTING ARCHIVE",
        )

    def test_unknown_file_is_not_removed(self):
        unknown = write_file(
            self.job / "pages" / "user_note.txt",
            b"KEEP THIS UNKNOWN FILE",
        )

        self.build_bundle()

        self.assertEqual(
            unknown.read_bytes(),
            b"KEEP THIS UNKNOWN FILE",
        )


if __name__ == "__main__":
    unittest.main()
