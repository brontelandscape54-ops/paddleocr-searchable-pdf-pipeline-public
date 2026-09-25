#!/usr/bin/env python3
"""Experimental Bash-free setup for the existing pinned Japanese PDF fonts.

Read-only by default. Downloads occur only with --install-fonts; existing files
are preserved unless --force is also explicitly requested. No OCR dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]

# Keep the source URLs and verification pins identical to tools/setup_fonts.sh.
# M PLUS 1p: immutable Google Fonts commit; verify Git blob IDs of font/license.
MPLUS_COMMIT = "5e35378e6bda803962ee6fd257e444a7d459660d"
MPLUS_FONT_BLOB_SHA1 = "84016bdcbf6e1be46eba4745d991d57c2f49aabf"
MPLUS_LICENSE_BLOB_SHA1 = "c173f0d8c43767c1e65b336d46a95c27b61bde92"
MPLUS_FONT_URLS = [
    f"https://raw.githubusercontent.com/google/fonts/{MPLUS_COMMIT}/ofl/mplus1p/MPLUS1p-Medium.ttf",
    f"https://github.com/google/fonts/raw/{MPLUS_COMMIT}/ofl/mplus1p/MPLUS1p-Medium.ttf",
]
MPLUS_LICENSE_URLS = [
    f"https://raw.githubusercontent.com/google/fonts/{MPLUS_COMMIT}/ofl/mplus1p/OFL.txt",
    f"https://github.com/google/fonts/raw/{MPLUS_COMMIT}/ofl/mplus1p/OFL.txt",
]

# Retain the historical, verified 2025-09-12 Jigmo archive rather than silently
# changing upstream version or trust roots.
JIGMO_URLS = ["https://kamichikoichi.github.io/jigmo/Jigmo-20250912.zip"]
JIGMO_ARCHIVE_SIZE = 35_559_738
JIGMO_SHA256 = "5744c7386d129475d87607ca66d043c8793c65448adeaedc921b6931890e5d0b"
JIGMO_FILES = ("Jigmo.ttf", "Jigmo2.ttf", "Jigmo3.ttf")
USER_AGENT = "paddleocr-searchable-pdf-pipeline-font-setup/1"


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def git_blob_sha1_file(path: Path) -> str:
    """Compare an existing M PLUS file to its historical pin without loading all bytes."""
    digest = hashlib.sha1()
    digest.update(f"blob {path.stat().st_size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def looks_like_sfnt(data: bytes) -> bool:
    return data[:4] in {b"\x00\x01\x00\x00", b"true", b"ttcf", b"OTTO"}


def download(urls: list[str], label: str) -> bytes:
    last_error: Exception | None = None
    for url in urls:
        for attempt in range(1, 4):
            try:
                print(f"[DOWNLOAD] {label}: {url} (attempt {attempt}/3)", flush=True)
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=180) as response:
                    return response.read()
            except Exception as exc:
                last_error = exc
                print(f"[WARN] download failed: {exc}", file=sys.stderr, flush=True)
                if attempt < 3:
                    time.sleep(attempt)
    raise RuntimeError(f"could not download {label}: {last_error}")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def install_plan(font_dir: Path, *, force: bool) -> dict[str, object]:
    """Determine writes without creating folders, downloading or altering files."""
    if font_dir.exists() and not font_dir.is_dir():
        raise RuntimeError(f"font destination is not a directory: {font_dir}")
    license_dir = font_dir / "licenses"
    if license_dir.exists() and not license_dir.is_dir():
        raise RuntimeError(f"license destination is not a directory: {license_dir}")
    mplus = font_dir / "MPLUS1p-Medium.ttf"
    mplus_license = license_dir / "MPLUS1p-OFL-1.1.txt"
    jigmo = [font_dir / name for name in JIGMO_FILES]
    jigmo_license = license_dir / "Jigmo-CC0-1.0.txt"
    targets = [mplus, mplus_license, *jigmo, jigmo_license]
    if any(path.exists() and not path.is_file() for path in targets):
        raise RuntimeError("a font or license destination exists but is not a regular file")
    return {
        "mplus": mplus,
        "mplus_license": mplus_license,
        "jigmo": jigmo,
        "jigmo_license": jigmo_license,
        "need_mplus": force or not mplus.is_file(),
        "need_mplus_license": force or not mplus_license.is_file(),
        "need_jigmo": force or any(not path.is_file() for path in jigmo),
        "force": force,
    }


def inspect_fonts(font_dir: Path) -> bool:
    """Read-only inspection; file existence alone does not prove a font is valid."""
    plan = install_plan(font_dir, force=False)
    print(f"[INFO] font directory: {font_dir}")
    complete = True
    mplus = plan["mplus"]
    assert isinstance(mplus, Path)
    if mplus.is_file():
        verified = git_blob_sha1_file(mplus) == MPLUS_FONT_BLOB_SHA1
        print(f"[{'VERIFIED' if verified else 'PRESENT_UNVERIFIED'}] {mplus.name}")
        if not verified:
            with mplus.open("rb") as stream:
                if not looks_like_sfnt(stream.read(4)):
                    complete = False
    else:
        complete = False
        print(f"[MISSING] {mplus.name}")
    jigmo = plan["jigmo"]
    assert isinstance(jigmo, list)
    for path in jigmo:
        if path.is_file():
            with path.open("rb") as stream:
                signature = stream.read(4)
            status = "PRESENT_UNVERIFIED" if looks_like_sfnt(signature) else "PRESENT_INVALID_HEADER"
            print(f"[{status}] {path.name}")
            if not looks_like_sfnt(signature):
                complete = False
        else:
            complete = False
            print(f"[MISSING] {path.name}")
    for key in ("mplus_license", "jigmo_license"):
        path = plan[key]
        assert isinstance(path, Path)
        print(f"[{'PRESENT' if path.is_file() else 'MISSING'}] license: {path.name}")
    print(f"[STATUS] {'ALL_FONT_FILES_PRESENT' if complete else 'FONT_SETUP_INCOMPLETE'}")
    print("[OK] read-only inspection; no downloads or file changes")
    return complete


def fetch_verified_payloads(plan: dict[str, object]) -> dict[Path, bytes]:
    """Verify all needed downloads before writing even one target file."""
    payloads: dict[Path, bytes] = {}
    if plan["need_mplus"]:
        data = download(MPLUS_FONT_URLS, "M PLUS 1p Medium")
        actual = git_blob_sha1(data)
        if actual != MPLUS_FONT_BLOB_SHA1:
            raise RuntimeError(
                f"M PLUS 1p Git blob hash mismatch: expected {MPLUS_FONT_BLOB_SHA1}, got {actual}"
            )
        if not looks_like_sfnt(data):
            raise RuntimeError("downloaded M PLUS file does not look like a font")
        payloads[plan["mplus"]] = data
    if plan["need_mplus_license"]:
        data = download(MPLUS_LICENSE_URLS, "M PLUS OFL license")
        actual = git_blob_sha1(data)
        if actual != MPLUS_LICENSE_BLOB_SHA1:
            raise RuntimeError(
                f"M PLUS license Git blob hash mismatch: expected {MPLUS_LICENSE_BLOB_SHA1}, got {actual}"
            )
        payloads[plan["mplus_license"]] = data

    if plan["need_jigmo"]:
        archive = download(JIGMO_URLS, "Jigmo 2025-09-12 official ZIP")
        if len(archive) != JIGMO_ARCHIVE_SIZE:
            raise RuntimeError(
                f"Jigmo archive size mismatch: expected {JIGMO_ARCHIVE_SIZE}, got {len(archive)}"
            )
        archive_hash = hashlib.sha256(archive).hexdigest()
        if archive_hash != JIGMO_SHA256:
            raise RuntimeError(
                f"Jigmo archive SHA-256 mismatch: expected {JIGMO_SHA256}, got {archive_hash}"
            )
        print(f"[OK] Jigmo archive SHA-256 verified: {archive_hash}", flush=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            missing = [name for name in JIGMO_FILES if name not in zipped.namelist()]
            if missing:
                raise RuntimeError(f"Jigmo archive missing expected fonts: {missing}")
            jigmo = plan["jigmo"]
            assert isinstance(jigmo, list)
            for filename, path in zip(JIGMO_FILES, jigmo):
                if plan["force"] or not path.is_file():
                    data = zipped.read(filename)
                    if not looks_like_sfnt(data):
                        raise RuntimeError(f"{filename} does not look like a font")
                    payloads[path] = data
            license_candidates = [
                name for name in zipped.namelist()
                if Path(name).name.lower() in {"license.txt", "license", "cc0.txt"}
            ]
            license_target = plan["jigmo_license"]
            assert isinstance(license_target, Path)
            if license_candidates and (plan["force"] or not license_target.is_file()):
                payloads[license_target] = zipped.read(license_candidates[0])
            elif not license_candidates:
                print("[WARN] Jigmo ZIP has no standalone license text; see upstream CC0 notice")
    return payloads


def install_fonts(font_dir: Path, *, force: bool = False) -> None:
    plan = install_plan(font_dir, force=force)
    print(f"[INFO] font directory: {font_dir}", flush=True)
    if force:
        print("[WARN] --force explicitly requested: existing managed font/license files may be replaced")
    else:
        print("[INFO] existing font and license files will be preserved", flush=True)
    payloads = fetch_verified_payloads(plan)
    # Retain user-provided existing files unless --force was explicitly requested.
    for path, data in payloads.items():
        if path.is_file() and not force:
            print(f"[SKIP] preserving existing file: {path.name}", flush=True)
            continue
        atomic_write(path, data)
        print(f"[OK] installed: {path}", flush=True)
    required = [plan["mplus"], *plan["jigmo"]]
    if not all(path.is_file() for path in required):
        raise RuntimeError("required font files are still missing")
    print("[DONE] recommended font file paths are available", flush=True)
    print("[INFO] font priority order:")
    for index, path in enumerate(required, start=1):
        print(f"  {index}. {path}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Experimental Python-only setup of historically pinned Japanese PDF fonts"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only inspection (default)")
    mode.add_argument(
        "--install-fonts", action="store_true",
        help="Explicitly download and verify missing recommended fonts and license files",
    )
    parser.add_argument(
        "--font-dir", type=Path,
        default=Path(os.environ.get("PADDLE_FONT_DIR") or ROOT / "fonts"),
        help="Font destination; defaults to PADDLE_FONT_DIR or repository/fonts",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Only with --install-fonts: explicitly replace managed font/license files",
    )
    args = parser.parse_args(argv)
    if args.force and not args.install_fonts:
        parser.error("--force requires --install-fonts")
    font_dir = args.font_dir.expanduser().resolve()
    try:
        if args.install_fonts:
            install_fonts(font_dir, force=args.force)
        else:
            inspect_fonts(font_dir)
        return 0
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
