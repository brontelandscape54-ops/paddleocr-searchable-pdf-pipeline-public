#!/usr/bin/env python3
"""Dependency-free read-only checks of experimental native environment setup."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("setup_python_envs", ROOT / "tools/setup_python_envs.py")
assert spec is not None and spec.loader is not None
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class NativeSetupTests(unittest.TestCase):
    def test_supported_version_boundary(self):
        self.assertFalse(setup.supported_python((3, 9)))
        self.assertTrue(setup.supported_python((3, 10)))
        self.assertTrue(setup.supported_python((3, 13)))
        self.assertFalse(setup.supported_python((3, 14)))

    def test_windows_and_posix_venv_python(self):
        venv = Path("myenv")
        self.assertEqual(setup.environment_python(venv, platform_name="win32"), venv / "Scripts/python.exe")
        self.assertEqual(setup.environment_python(venv, platform_name="darwin"), venv / "bin/python")

    def test_plan_does_not_create_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for _, requirements, _ in setup.ENV_SPECS:
                (root / requirements).write_text("# test\n", encoding="utf-8")
            with mock.patch.object(setup, "imports_work", return_value=False):
                entries = setup.plan(root)
            self.assertEqual([entry[3] for entry in entries], ["CREATE", "CREATE"])
            self.assertFalse((root / ".venv").exists())
            self.assertFalse((root / ".venv_paddle").exists())

    def test_existing_unusable_env_blocks_install_before_any_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for _, requirements, _ in setup.ENV_SPECS:
                (root / requirements).write_text("# test\n", encoding="utf-8")
            (root / ".venv").mkdir()
            with mock.patch.object(setup, "imports_work", return_value=False):
                entries = setup.plan(root)
            self.assertEqual([entry[3] for entry in entries], ["CREATE", "BLOCKED_EXISTING_ENV"])
            with mock.patch.object(setup.venv.EnvBuilder, "create") as create:
                with self.assertRaisesRegex(RuntimeError, "Existing unusable environment"):
                    setup.install_environments(entries)
                create.assert_not_called()
            self.assertFalse((root / ".venv_paddle").exists())

    def test_setup_does_not_replace_working_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for _, requirements, _ in setup.ENV_SPECS:
                (root / requirements).write_text("# test\n", encoding="utf-8")
            (root / ".venv").mkdir()
            (root / ".venv_paddle").mkdir()
            with mock.patch.object(setup, "imports_work", return_value=True):
                entries = setup.plan(root)
            self.assertEqual([entry[3] for entry in entries], ["REUSE", "REUSE"])
            with mock.patch.object(setup.venv.EnvBuilder, "create") as create:
                setup.install_environments(entries)
                create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
