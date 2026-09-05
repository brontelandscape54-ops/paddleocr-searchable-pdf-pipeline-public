#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FONT_DIR="${PADDLE_FONT_DIR:-$ROOT/fonts}"
FORCE=0

usage() {
  cat <<'EOF'
Usage: bash tools/setup_fonts.sh [--force]

Downloads the recommended Japanese OCR PDF fonts into ./fonts/.
Existing user-provided font files are preserved unless --force is used.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "[ERROR] unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

select_python() {
  local candidate
  local candidates=()
  if [ -n "${BASE_PYTHON:-}" ]; then candidates+=("$BASE_PYTHON"); fi
  if command -v python3.10 >/dev/null 2>&1; then candidates+=("$(command -v python3.10)"); fi
  if command -v python3 >/dev/null 2>&1; then candidates+=("$(command -v python3)"); fi

  for candidate in "${candidates[@]}"; do
    [ -x "$candidate" ] || continue
    if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 14) else 1)
PY
    then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON="$(select_python)"; then
  echo "[ERROR] Python 3.10-3.13 is required for font setup." >&2
  exit 1
fi

mkdir -p "$FONT_DIR"

echo "[INFO] font directory: $FONT_DIR"
echo "[INFO] existing font files are preserved unless --force is used"

"$PYTHON" - "$FONT_DIR" "$FORCE" <<'PY'
from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

font_dir = Path(sys.argv[1]).expanduser().resolve()
force = sys.argv[2] == "1"
license_dir = font_dir / "licenses"
font_dir.mkdir(parents=True, exist_ok=True)
license_dir.mkdir(parents=True, exist_ok=True)

# M PLUS 1p: pin an immutable Google Fonts repository snapshot and verify the
# exact Git blob IDs reported by GitHub for both the TTF and OFL text.
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

# Jigmo 2025-09-12 is the current upstream release and covers Unicode 17.0
# CJK Unified Ideographs through Extension J. The primary distribution is the
# author's GitHub Pages site. Its archive is pinned by exact size and a full
# SHA-256 independently recorded for this exact URL by Tor Browser's build
# configuration in October 2025.
JIGMO_URLS = [
    "https://kamichikoichi.github.io/jigmo/Jigmo-20250912.zip",
]
JIGMO_ARCHIVE_SIZE = 35_559_738
JIGMO_SHA256 = "5744c7386d129475d87607ca66d043c8793c65448adeaedc921b6931890e5d0b"
JIGMO_FILES = ["Jigmo.ttf", "Jigmo2.ttf", "Jigmo3.ttf"]

USER_AGENT = "paddleocr-searchable-pdf-pipeline-font-setup/1"


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


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


def looks_like_sfnt(data: bytes) -> bool:
    return data[:4] in {b"\x00\x01\x00\x00", b"true", b"ttcf", b"OTTO"}


def keep_existing(path: Path, managed_check=None) -> bool:
    if not path.is_file():
        return False
    if force:
        print(f"[INFO] replacing existing font because --force was requested: {path.name}")
        return False
    if managed_check is not None:
        try:
            if managed_check(path.read_bytes()):
                print(f"[OK] already installed and verified: {path.name}")
                return True
        except OSError:
            pass
    print(f"[INFO] preserving existing user-provided font: {path.name}")
    return True


mplus_target = font_dir / "MPLUS1p-Medium.ttf"
if not keep_existing(mplus_target, lambda data: git_blob_sha1(data) == MPLUS_FONT_BLOB_SHA1):
    data = download(MPLUS_FONT_URLS, "M PLUS 1p Medium")
    blob_hash = git_blob_sha1(data)
    if blob_hash != MPLUS_FONT_BLOB_SHA1:
        raise RuntimeError(
            "M PLUS 1p Git blob hash mismatch: "
            f"expected {MPLUS_FONT_BLOB_SHA1}, got {blob_hash}"
        )
    if not looks_like_sfnt(data):
        raise RuntimeError("downloaded M PLUS file does not look like a font")
    atomic_write(mplus_target, data)
    print(f"[OK] installed: {mplus_target}")
    print(f"[CHECK] M PLUS SHA-256: {hashlib.sha256(data).hexdigest()}")

mplus_license_target = license_dir / "MPLUS1p-OFL-1.1.txt"
if force or not mplus_license_target.is_file():
    data = download(MPLUS_LICENSE_URLS, "M PLUS OFL license")
    blob_hash = git_blob_sha1(data)
    if blob_hash != MPLUS_LICENSE_BLOB_SHA1:
        raise RuntimeError(
            "M PLUS license Git blob hash mismatch: "
            f"expected {MPLUS_LICENSE_BLOB_SHA1}, got {blob_hash}"
        )
    atomic_write(mplus_license_target, data)
    print(f"[OK] saved license: {mplus_license_target}")

jigmo_targets = [font_dir / name for name in JIGMO_FILES]
need_jigmo = force or any(not path.is_file() for path in jigmo_targets)
if need_jigmo:
    archive = download(JIGMO_URLS, "Jigmo 2025-09-12 official ZIP")
    if len(archive) != JIGMO_ARCHIVE_SIZE:
        raise RuntimeError(
            "Jigmo archive size mismatch: "
            f"expected {JIGMO_ARCHIVE_SIZE}, got {len(archive)}"
        )
    archive_hash = hashlib.sha256(archive).hexdigest()
    if archive_hash != JIGMO_SHA256:
        raise RuntimeError(
            "Jigmo archive SHA-256 mismatch: "
            f"expected {JIGMO_SHA256}, got {archive_hash}"
        )
    print(f"[OK] Jigmo archive SHA-256 verified: {archive_hash}")

    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = set(zf.namelist())
        missing = [name for name in JIGMO_FILES if name not in names]
        if missing:
            raise RuntimeError(f"Jigmo archive missing expected fonts: {missing}")
        font_payloads = {name: zf.read(name) for name in JIGMO_FILES}

        license_candidates = [
            name
            for name in zf.namelist()
            if Path(name).name.lower() in {"license.txt", "license", "cc0.txt"}
        ]
        license_payload = zf.read(license_candidates[0]) if license_candidates else None

    for source_name, target in zip(JIGMO_FILES, jigmo_targets):
        if target.is_file() and not force:
            print(f"[INFO] preserving existing user-provided font: {target.name}")
            continue
        data = font_payloads[source_name]
        if not looks_like_sfnt(data):
            raise RuntimeError(f"{source_name} does not look like a font")
        atomic_write(target, data)
        print(f"[OK] installed: {target}")
        print(f"[CHECK] {target.name} SHA-256: {hashlib.sha256(data).hexdigest()}")

    if license_payload is not None:
        license_target = license_dir / "Jigmo-CC0-1.0.txt"
        if force or not license_target.is_file():
            atomic_write(license_target, license_payload)
            print(f"[OK] saved license: {license_target}")
    else:
        print("[WARN] Jigmo archive did not contain a standalone license text; see upstream CC0 notice")
else:
    print("[OK] Jigmo.ttf, Jigmo2.ttf and Jigmo3.ttf already exist; preserving them")

required_fonts = [mplus_target, *jigmo_targets]
for required in required_fonts:
    if not required.is_file():
        raise RuntimeError(f"required font is still missing: {required}")

print("[DONE] recommended fonts are available")
print("[INFO] priority order:")
for index, path in enumerate(required_fonts, start=1):
    print(f"  {index}. {path}")
PY

cat <<EOF
[DONE] font setup completed

Fonts are stored locally under:
  $FONT_DIR

They are ignored by Git and are not part of the public repository history.
EOF
