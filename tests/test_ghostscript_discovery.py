#!/usr/bin/env python3
"""Dependency-free checks of cross-platform Ghostscript executable discovery."""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "code" / "compress_pdf_150dpi.py"


def load_discovery():
    """Load only the pure discovery helper; no pypdf installation is needed."""
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    method = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "find_ghostscript"
    )
    isolated = ast.Module(body=[method], type_ignores=[])
    namespace = {"shutil": shutil}
    exec(compile(isolated, str(SOURCE), "exec"), namespace)
    return namespace["find_ghostscript"]


class GhostscriptDiscoveryTests(unittest.TestCase):
    def test_prefers_established_gs_executable(self):
        finder = load_discovery()
        with mock.patch.object(shutil, "which", side_effect=lambda name: "/usr/bin/gs" if name == "gs" else None) as which:
            self.assertEqual(finder(), "/usr/bin/gs")
            which.assert_called_once_with("gs")

    def test_finds_windows_console_executable(self):
        finder = load_discovery()
        with mock.patch.object(shutil, "which", side_effect=lambda name: r"C:\\Program Files\\gs\\bin\\gswin64c.exe" if name == "gswin64c.exe" else None):
            self.assertEqual(finder(), r"C:\\Program Files\\gs\\bin\\gswin64c.exe")

    def test_skips_compression_when_ghostscript_absent(self):
        finder = load_discovery()
        with mock.patch.object(shutil, "which", return_value=None) as which:
            self.assertIsNone(finder())
            self.assertEqual(which.call_count, 3)


if __name__ == "__main__":
    unittest.main()
