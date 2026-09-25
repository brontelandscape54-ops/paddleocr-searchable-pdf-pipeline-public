#!/usr/bin/env python3
"""Offline regression checks for the experimental pinned Python font installer."""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("setup_fonts_python", ROOT / "tools/setup_fonts.py")
assert spec is not None and spec.loader is not None
fonts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fonts)


def fake_jigmo_zip() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name in fonts.JIGMO_FILES:
            zf.writestr(name, b"\x00\x01\x00\x00" + name.encode("ascii"))
        zf.writestr("license.txt", b"test license")
    return out.getvalue()


class FontSetupTests(unittest.TestCase):
    def test_existing_font_inspection_is_read_only_and_download_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "fonts"
            with mock.patch.object(fonts, "download", side_effect=AssertionError("download called")):
                self.assertFalse(fonts.inspect_fonts(target))
            self.assertFalse(target.exists())

    def test_existing_fonts_and_licenses_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "fonts"
            (target / "licenses").mkdir(parents=True)
            for name in ("MPLUS1p-Medium.ttf", *fonts.JIGMO_FILES):
                (target / name).write_bytes(b"custom" + name.encode("ascii"))
            (target / "licenses/MPLUS1p-OFL-1.1.txt").write_bytes(b"user license")
            (target / "licenses/Jigmo-CC0-1.0.txt").write_bytes(b"user license 2")
            original = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
            with (
                mock.patch.object(fonts, "download", side_effect=AssertionError("download called")),
                mock.patch.object(fonts, "atomic_write", side_effect=AssertionError("write called")),
            ):
                fonts.install_fonts(target)
            self.assertEqual(original, {p: p.read_bytes() for p in original})

    def test_bad_mplus_hash_rejected_before_any_file_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "fonts"
            with (
                mock.patch.object(fonts, "download", return_value=b"\x00\x01\x00\x00bad font"),
                mock.patch.object(fonts, "atomic_write") as write,
            ):
                with self.assertRaisesRegex(RuntimeError, "M PLUS 1p Git blob hash mismatch"):
                    fonts.install_fonts(target)
                write.assert_not_called()
            self.assertFalse(target.exists())

    def test_jigmo_bad_hash_rejected_before_any_file_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "fonts"
            with (
                mock.patch.object(fonts, "download", return_value=b"not a zip"),
                mock.patch.object(fonts, "JIGMO_ARCHIVE_SIZE", len(b"not a zip")),
                mock.patch.object(fonts, "atomic_write") as write,
            ):
                plan = fonts.install_plan(target, force=False)
                with self.assertRaisesRegex(RuntimeError, "Jigmo archive SHA-256 mismatch"):
                    fonts.fetch_verified_payloads({**plan, "need_mplus": False, "need_mplus_license": False})
                write.assert_not_called()

    def test_valid_pinned_payloads_and_licenses_installed_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "fonts"
            mplus = b"\x00\x01\x00\x00" + b"sample font"
            license_data = b"sample OFL"
            jigmo = fake_jigmo_zip()
            def fixture(urls, label):
                if "OFL" in label:
                    return license_data
                if "Jigmo" in label:
                    return jigmo
                return mplus
            with (
                mock.patch.object(fonts, "download", side_effect=fixture),
                mock.patch.object(fonts, "MPLUS_FONT_BLOB_SHA1", fonts.git_blob_sha1(mplus)),
                mock.patch.object(fonts, "MPLUS_LICENSE_BLOB_SHA1", fonts.git_blob_sha1(license_data)),
                mock.patch.object(fonts, "JIGMO_ARCHIVE_SIZE", len(jigmo)),
                mock.patch.object(fonts, "JIGMO_SHA256", hashlib.sha256(jigmo).hexdigest()),
            ):
                fonts.install_fonts(target)
            self.assertEqual((target / "MPLUS1p-Medium.ttf").read_bytes(), mplus)
            self.assertEqual((target / "licenses/MPLUS1p-OFL-1.1.txt").read_bytes(), license_data)
            self.assertEqual((target / "licenses/Jigmo-CC0-1.0.txt").read_bytes(), b"test license")
            for name in fonts.JIGMO_FILES:
                self.assertTrue((target / name).is_file())


if __name__ == "__main__":
    unittest.main()
