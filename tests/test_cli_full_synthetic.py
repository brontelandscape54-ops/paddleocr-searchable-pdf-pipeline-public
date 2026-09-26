#!/usr/bin/env python3
"""Full Python CLI flow using synthetic stage outputs, never real OCR."""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from reportlab.pdfgen import canvas

import paddleocr_cli as cli


ROOT = Path(__file__).resolve().parents[1]
PDF_TEXT = "SEARCHABLE PAGE 1"


def write_file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def write_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = canvas.Canvas(str(path))
    document.drawString(72, 720, PDF_TEXT)
    document.showPage()
    document.save()
    return path


class SyntheticCliEndToEndTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.root = Path(temporary.name)
        self.source = write_file(
            self.root / "original.png",
            b"SYNTHETIC INPUT: MUST REMAIN UNCHANGED",
        )
        self.original_bytes = self.source.read_bytes()
        self.paths = cli.paths_for(
            self.source,
            self.root,
            "synthetic_cli_job",
            dt.datetime(2026, 9, 26),
        )
        self.job = self.paths["job"]
        self.archive = self.job / "original_ocr_bundle.zip"

        # The CLI uses ROOT to find its helper script. Copy that script
        # into the isolated test root; do not operate on repository jobs.
        finalizer_dir = self.root / "tools"
        finalizer_dir.mkdir()
        shutil.copy2(
            ROOT / "tools" / "finalize_paddle_outputs.py",
            finalizer_dir / "finalize_paddle_outputs.py",
        )

    def run_synthetic_cli(
        self,
        *,
        keep_intermediates=False,
        generate_150dpi_pdf=False,
        missing_compressed_pdf=False,
        failing_stage=None,
    ):
        prefix = "original"

        def fake_stage(label, command, logs, *, env=None):
            write_file(
                logs / f"{label}.log",
                f"[SYNTHETIC] {label}\n".encode("utf-8"),
            )

            if label == failing_stage:
                raise cli.PipelineError(
                    f"synthetic failure in {label}"
                )

            if label == "01_prepare_pages":
                write_file(
                    self.paths["pages"] / "page_0001.png",
                    b"SYNTHETIC PAGE IMAGE",
                )

            elif label == "02_paddle_ocr":
                write_file(
                    self.paths["json"]
                    / "page_0001_paddle_small.json",
                    json.dumps({
                        "ocr": {"rec_texts": [PDF_TEXT]}
                    }).encode("utf-8"),
                )
                write_file(
                    self.paths["txt"]
                    / "page_0001_paddle_small.txt",
                    (PDF_TEXT + "\n").encode("utf-8"),
                )
                write_file(
                    self.paths["ocr"]
                    / "paddle_batch_summary.csv",
                    b"page,status\npage_0001.png,ok\n",
                )

            elif label == "03_aggregate_outputs":
                for extension, content in (
                    ("txt", b"SYNTHETIC TEXT\n"),
                    ("md", b"# SYNTHETIC\n"),
                    ("json", b'[{"page":1}]'),
                    ("jsonl", b'{"page":1}\n'),
                ):
                    if extension == "jsonl":
                        name = f"{prefix}_paddle_pages.jsonl"
                    else:
                        name = f"{prefix}_paddle.{extension}"
                    write_file(
                        self.paths["output"] / name,
                        content,
                    )

            elif label == "05_merge_pdf":
                write_pdf(self.paths["merged"])

            elif label == "07_compress_pdf":
                if not missing_compressed_pdf:
                    write_pdf(self.paths["small"])

        class FakePageProcess:
            def __init__(self):
                self.stdout = io.StringIO(
                    "[SYNTHETIC] page PDF generated\n"
                )

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                self.stdout.close()
                return False

            def wait(self):
                return 0

        def fake_page_process(command, **kwargs):
            self.assertIn("--out", command)
            destination = Path(
                command[command.index("--out") + 1]
            )
            write_pdf(destination)
            return FakePageProcess()

        # Patch only cli.subprocess, not the global subprocess
        # module. The real finalizer still runs as a child process.
        process_api = types.SimpleNamespace(
            Popen=fake_page_process,
            run=subprocess.run,
            PIPE=subprocess.PIPE,
            STDOUT=subprocess.STDOUT,
        )

        args = [
            str(self.source),
            "synthetic_cli_job",
        ]
        if keep_intermediates:
            args.append("--keep-intermediates")
        if generate_150dpi_pdf:
            args.append("--generate-150dpi-pdf")

        output = io.StringIO()
        errors = io.StringIO()

        with (
            mock.patch.object(cli, "ROOT", self.root),
            mock.patch.object(
                cli,
                "resolve_interpreters",
                return_value=(
                    Path(sys.executable),
                    Path(sys.executable),
                ),
            ),
            mock.patch.object(
                cli,
                "check_fonts",
                return_value=["synthetic-font.ttf"],
            ),
            mock.patch.object(
                cli,
                "run_stage",
                side_effect=fake_stage,
            ),
            mock.patch.object(
                cli,
                "subprocess",
                process_api,
            ),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            result = cli.main(args)

        self.assertEqual(
            self.source.read_bytes(),
            self.original_bytes,
        )

        return result, output.getvalue(), errors.getvalue()

    def status_text(self):
        return (
            self.job / "logs" / "finalization_status.log"
        ).read_text(encoding="utf-8")

    def test_default_run_finishes_and_cleans(self):
        result, output, errors = self.run_synthetic_cli()

        self.assertEqual(result, 0, errors)
        self.assertTrue(self.archive.is_file())
        self.assertTrue(self.paths["merged"].is_file())
        self.assertFalse(self.paths["small"].exists())
        self.assertFalse(
            (self.paths["pages"] / "page_0001.png").exists()
        )
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
                self.assertFalse((self.job / relative).exists())
        self.assertFalse(
            (
                self.paths["json"]
                / "page_0001_paddle_small.json"
            ).exists()
        )
        self.assertIn(
            "status=success\n",
            self.status_text(),
        )
        self.assertIn(
            "PADDLEOCR PIPELINE FINISHED",
            output,
        )

        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())
            names = set(bundle.namelist())
            self.assertIn(
                "logs/timing_summary.log",
                names,
            )
            self.assertNotIn(
                "logs/finalization_status.log",
                names,
            )
            self.assertIn(
                "scope=ocr_pdf_stages\n",
                bundle.read(
                    "logs/timing_summary.log"
                ).decode("utf-8"),
            )

    def test_keep_intermediates_preserves_page_files(self):
        result, _, errors = self.run_synthetic_cli(
            keep_intermediates=True
        )

        self.assertEqual(result, 0, errors)
        self.assertTrue(self.archive.is_file())
        self.assertTrue(
            (self.paths["pages"] / "page_0001.png").is_file()
        )
        self.assertTrue(
            (
                self.paths["json"]
                / "page_0001_paddle_small.json"
            ).is_file()
        )
        self.assertIn(
            "keep_intermediates=1\n",
            self.status_text(),
        )

    def test_explicit_compressed_pdf_is_delivered(self):
        result, _, errors = self.run_synthetic_cli(
            generate_150dpi_pdf=True
        )

        self.assertEqual(result, 0, errors)
        self.assertTrue(self.archive.is_file())
        self.assertTrue(self.paths["merged"].is_file())
        self.assertTrue(self.paths["small"].is_file())
        self.assertIn(
            "compressed_pdf_requested=1\n",
            self.status_text(),
        )

        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertFalse(
                any(
                    name.endswith(".pdf")
                    for name in bundle.namelist()
                )
            )

    def test_missing_requested_compressed_pdf_fails(self):
        result, _, errors = self.run_synthetic_cli(
            generate_150dpi_pdf=True,
            missing_compressed_pdf=True,
        )

        self.assertEqual(result, 1)
        self.assertIn("Finalization failed", errors)
        self.assertFalse(self.archive.exists())
        self.assertTrue(self.paths["merged"].is_file())
        self.assertTrue(
            (self.paths["pages"] / "page_0001.png").is_file()
        )
        self.assertIn(
            "status=failed\n",
            self.status_text(),
        )
        self.assertIn(
            "archive_published=0\n",
            self.status_text(),
        )

    def test_ocr_stage_failure_skips_finalization(self):
        result, _, errors = self.run_synthetic_cli(
            failing_stage="02_paddle_ocr"
        )

        self.assertEqual(result, 1)
        self.assertIn(
            "synthetic failure in 02_paddle_ocr",
            errors,
        )
        self.assertFalse(self.archive.exists())
        self.assertIn(
            "status=failed\nphase=ocr_pdf\n",
            self.status_text(),
        )

    def test_completed_job_is_not_reused_or_modified(self):
        first, _, errors = self.run_synthetic_cli()
        self.assertEqual(first, 0, errors)

        zip_before = self.archive.read_bytes()
        status_before = self.status_text()

        second, _, second_errors = self.run_synthetic_cli()

        self.assertEqual(second, 1)
        self.assertIn("ZIP", second_errors)
        self.assertEqual(
            self.archive.read_bytes(), zip_before
        )
        self.assertEqual(
            self.status_text(), status_before
        )


class ExplicitCompressionTests(unittest.TestCase):
    def test_missing_ghostscript_fails_when_required(self):
        spec = importlib.util.spec_from_file_location(
            "compress_pdf_150dpi_for_test",
            ROOT / "code" / "compress_pdf_150dpi.py",
        )
        assert spec is not None and spec.loader is not None
        compressor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compressor)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            output = Path(directory) / "small.pdf"
            source.write_bytes(b"synthetic source")

            with (
                mock.patch.object(
                    compressor,
                    "find_ghostscript",
                    return_value=None,
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "compress_pdf_150dpi.py",
                        str(source),
                        str(output),
                        "--require-ghostscript",
                    ],
                ),
            ):
                with self.assertRaisesRegex(
                    SystemExit, "Ghostscript"
                ):
                    compressor.main()

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
