#!/usr/bin/env python3
"""Dependency-free contract tests for the experimental Python CLI."""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("paddleocr_cli", ROOT / "paddleocr_cli.py")
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class PythonCliTests(unittest.TestCase):
    def test_interpreter_path_matches_platform(self):
        self.assertEqual(
            cli.interpreter_in(Path("myenv"), platform_name="nt"),
            Path("myenv") / "Scripts" / "python.exe",
        )
        self.assertEqual(
            cli.interpreter_in(Path("myenv"), platform_name="posix"),
            Path("myenv") / "bin" / "python",
        )

    def test_selection_preserves_virtualenv_symlink(self):
        # On POSIX, resolving .venv/bin/python can select the base interpreter
        # and lose access to packages installed only in the virtualenv.
        if os.name == "nt":
            self.skipTest("POSIX symlink behavior")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            venv_python = cli.interpreter_in(root / ".venv")
            venv_python.parent.mkdir(parents=True)
            venv_python.symlink_to(Path(sys.executable))
            with mock.patch.object(cli, "python_works", return_value=True):
                selected = cli.select_interpreter(
                    None, [venv_python], "import fontTools", "Helper Python"
                )
                self.assertEqual(selected, venv_python.absolute())
                self.assertNotEqual(selected, Path(sys.executable).resolve())

    def test_override_preserves_virtualenv_symlink(self):
        if os.name == "nt":
            self.skipTest("POSIX symlink behavior")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            venv_python = cli.interpreter_in(root / ".venv")
            venv_python.parent.mkdir(parents=True)
            venv_python.symlink_to(Path(sys.executable))
            with mock.patch.object(cli, "python_works", return_value=True):
                selected = cli.select_interpreter(
                    str(venv_python), [], "import fontTools", "Helper Python"
                )
                self.assertEqual(selected, venv_python.absolute())

    def test_name_blocks_traversal_and_windows_invalid_characters(self):
        self.assertEqual(cli.clean_name("../a:b?c"), "a_b_c")
        self.assertEqual(cli.clean_name(""), "paddleocr_job")
        self.assertEqual(cli.clean_name("normal input"), "normal input")
        self.assertEqual(cli.clean_name("CON"), "_CON")
        self.assertEqual(cli.clean_name("nul.txt"), "_nul.txt")
        self.assertEqual(cli.clean_name("COM1"), "_COM1")
        self.assertEqual(cli.clean_name("LPT9.log"), "_LPT9.log")
        self.assertEqual(cli.clean_name("COM10"), "COM10")

    def test_paths_preserve_current_job_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = cli.paths_for(
                root / "source.pdf", root, "my job", dt.datetime(2026, 9, 23)
            )
            self.assertEqual(result["name"], "my job")
            self.assertEqual(result["json"], root / "jobs/my job/paddle_ocr/json")
            self.assertEqual(
                result["merged"],
                root / "jobs/my job/searchable_pdf/source_paddleocr_searchable.pdf",
            )

    def test_preflight_negative_does_not_create_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            source.write_bytes(b"test")
            err = io.StringIO()
            with (
                mock.patch.object(cli, "ROOT", root),
                mock.patch.object(cli, "resolve_interpreters", return_value=(Path("ocr"), Path("helper"))),
                mock.patch.object(cli, "check_fonts", side_effect=cli.PipelineError("missing fonts")),
                contextlib.redirect_stderr(err),
            ):
                status = cli.main([str(source), "--check"])
            self.assertEqual(status, 1)
            self.assertIn("missing fonts", err.getvalue())
            self.assertFalse((root / "jobs").exists())

    def test_preflight_success_does_not_create_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            source.write_bytes(b"test")
            out = io.StringIO()
            with (
                mock.patch.object(cli, "ROOT", root),
                mock.patch.object(cli, "resolve_interpreters", return_value=(Path("ocr"), Path("helper"))),
                mock.patch.object(cli, "check_fonts", return_value=["font.ttf"]),
                contextlib.redirect_stdout(out),
            ):
                status = cli.main([str(source), "--check"])
            self.assertEqual(status, 0)
            self.assertIn("font.ttf", out.getvalue())
            self.assertFalse((root / "jobs").exists())

    def test_input_identity_detects_changed_bytes_and_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original.png"
            source.write_bytes(b"original")
            options = {
                "dpi": 180, "normalize_pdf": True,
                "max_pixels": 25000000, "long_edge": 3400,
            }
            first = cli.input_identity(source, **options)
            self.assertEqual(first, cli.input_identity(source, **options))
            source.write_bytes(b"different")
            self.assertNotEqual(first, cli.input_identity(source, **options))
            source.write_bytes(b"original")
            self.assertNotEqual(first, cli.input_identity(source, **{**options, "dpi": 200}))

    def test_input_identity_detects_directory_image_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "images"
            source.mkdir()
            (source / "page_01.png").write_bytes(b"one")
            kwargs = {
                "dpi": 180, "normalize_pdf": True,
                "max_pixels": 25000000, "long_edge": 3400,
            }
            first = cli.input_identity(source, **kwargs)
            (source / "page_02.png").write_bytes(b"two")
            self.assertNotEqual(first, cli.input_identity(source, **kwargs))
            (source / "page_02.png").unlink()
            (source / "page_01.png").write_bytes(b"changed")
            self.assertNotEqual(first, cli.input_identity(source, **kwargs))

    def test_job_identity_rejects_legacy_and_mismatched_resume_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "job"
            logs = job / "logs"
            logs.mkdir(parents=True)
            original = job / "existing_marker.txt"
            original.write_text("protected", encoding="utf-8")
            identity = {"version": 1, "input_path": "/a", "source": {"sha256": "A"}}
            with self.assertRaisesRegex(cli.PipelineError, "入力識別記録がない"):
                cli.validate_job_identity(job, identity)
            record = logs / cli.INPUT_IDENTITY_FILENAME
            record.write_text('{"version": 1, "input_path": "/b"}', encoding="utf-8")
            with self.assertRaisesRegex(cli.PipelineError, "一致しません"):
                cli.validate_job_identity(job, identity)
            self.assertEqual(original.read_text(encoding="utf-8"), "protected")
            self.assertEqual(record.read_text(encoding="utf-8"), '{"version": 1, "input_path": "/b"}')
            record.write_text(json.dumps(identity), encoding="utf-8")
            cli.validate_job_identity(job, identity)

    def test_python_child_env_forces_utf8_without_mutating_inputs(self):
        supplied = {"MY_STAGE_SETTING": "kept", "PYTHONIOENCODING": "cp1252"}
        child = cli.python_child_env(supplied)
        self.assertEqual(child["MY_STAGE_SETTING"], "kept")
        self.assertEqual(child["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(child["PYTHONUTF8"], "1")
        self.assertEqual(supplied["PYTHONIOENCODING"], "cp1252")
        self.assertNotIn("PYTHONUTF8", supplied)

    def test_stage_japanese_output_with_hostile_parent_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            with mock.patch.dict(
                os.environ,
                {"PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"},
            ):
                cli.run_stage(
                    "test_japanese_utf8",
                    [sys.executable, "-c", "print('\\u65e5\\u672c\\u8a9e')"],
                    log_dir,
                )
            self.assertIn(
                "日本語",
                (log_dir / "test_japanese_utf8.log").read_text(encoding="utf-8"),
            )

    def test_stage_failure_stops_with_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            with self.assertRaisesRegex(cli.PipelineError, "failed: exit=7"):
                cli.run_stage(
                    "test_failure",
                    [sys.executable, "-c", "print('failure marker'); raise SystemExit(7)"],
                    log_dir,
                )
            self.assertIn(
                "failure marker",
                (log_dir / "test_failure.log").read_text(encoding="utf-8"),
            )

    def test_stage_success_logs_output(self):
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            cli.run_stage(
                "test_success",
                [sys.executable, "-c", "print('success marker')"],
                log_dir,
            )
            self.assertIn(
                "success marker",
                (log_dir / "test_success.log").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
