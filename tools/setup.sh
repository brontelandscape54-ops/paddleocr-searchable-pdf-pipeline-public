#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REBUILD=0
SKIP_FONTS=0
FORCE_FONTS=0

usage() {
  cat <<'EOF'
Usage: bash tools/setup.sh [options]

Options:
  --rebuild       Rebuild both .venv_paddle and helper .venv.
  --no-fonts      Skip recommended font download/setup.
  --force-fonts   Replace fonts managed by tools/setup_fonts.sh.
  -h, --help      Show this help.

Default behavior is conservative and repeatable:
- reuse working environments when possible;
- create missing/broken environments;
- preserve existing user-provided fonts;
- run regression tests and the static public smoke test.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --rebuild) REBUILD=1 ;;
    --no-fonts) SKIP_FONTS=1 ;;
    --force-fonts) FORCE_FONTS=1 ;;
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

if ! BASE="$(select_python)"; then
  echo "[ERROR] Python 3.10-3.13 was not found." >&2
  echo "        Set BASE_PYTHON=/path/to/python3.10 if needed." >&2
  exit 1
fi

echo "=== PaddleOCR Searchable PDF setup ==="
echo "ROOT=$ROOT"
echo "BASE_PYTHON=$BASE"
"$BASE" --version

PADDLE_PY="$ROOT/.venv_paddle/bin/python"
if [ "$REBUILD" -eq 1 ]; then
  echo "[INFO] rebuilding PaddleOCR environment by request"
  BASE_PYTHON="$BASE" bash "$ROOT/tools/rebuild_paddle_venv.sh"
elif [ -x "$PADDLE_PY" ] && "$PADDLE_PY" -c 'import paddleocr, paddlex, onnxruntime, numpy' >/dev/null 2>&1; then
  echo "[OK] existing PaddleOCR environment is usable"
else
  if [ -e "$ROOT/.venv_paddle" ]; then
    echo "[WARN] existing PaddleOCR environment is not usable; rebuilding it"
  else
    echo "[INFO] creating PaddleOCR environment"
  fi
  BASE_PYTHON="$BASE" bash "$ROOT/tools/rebuild_paddle_venv.sh"
fi

HELPER_DIR="$ROOT/.venv"
HELPER_PY="$HELPER_DIR/bin/python"
helper_ok() {
  [ -x "$HELPER_PY" ] && "$HELPER_PY" -c 'import pymupdf, PIL, reportlab, pypdf, fontTools' >/dev/null 2>&1
}

if [ "$REBUILD" -eq 1 ] && [ -e "$HELPER_DIR" ]; then
  backup="$ROOT/.venv_broken_$(date +%Y%m%d_%H%M%S)"
  echo "[INFO] preserving existing helper environment: $backup"
  mv "$HELPER_DIR" "$backup"
fi

if helper_ok; then
  echo "[OK] existing helper environment is usable"
else
  if [ -e "$HELPER_DIR" ]; then
    backup="$ROOT/.venv_broken_$(date +%Y%m%d_%H%M%S)"
    echo "[WARN] preserving unusable helper environment: $backup"
    mv "$HELPER_DIR" "$backup"
  fi
  echo "[INFO] creating helper environment: $HELPER_DIR"
  "$BASE" -m venv "$HELPER_DIR"
  "$HELPER_PY" -m pip install --upgrade pip setuptools wheel
  "$HELPER_PY" -m pip install -r "$ROOT/requirements-helper.txt"
  "$HELPER_PY" -c 'import pymupdf, PIL, reportlab, pypdf, fontTools'
  echo "[OK] helper environment imports"
fi

if [ "$SKIP_FONTS" -eq 1 ]; then
  echo "[INFO] skipping font setup (--no-fonts)"
elif [ "$FORCE_FONTS" -eq 1 ]; then
  BASE_PYTHON="$BASE" bash "$ROOT/tools/setup_fonts.sh" --force
else
  BASE_PYTHON="$BASE" bash "$ROOT/tools/setup_fonts.sh"
fi

echo "[INFO] running regression tests"
(
  cd "$ROOT"
  "$HELPER_PY" -m unittest \
    tests/test_empty_ocr_page.py \
    tests/test_reportlab_cmap_chunking.py
)

if [ "$SKIP_FONTS" -eq 0 ]; then
  echo "[INFO] validating Jigmo supplementary-plane PDF path"
  (
    cd "$ROOT"
    "$HELPER_PY" tools/validate_jigmo_supplementary.py
  )
fi

echo "[INFO] running static public smoke test"
bash "$ROOT/tools/smoke_test_public.sh"

cat <<'EOF'

[DONE] setup completed.

Run OCR with:
  ./paddleocr.sh "/path/to/input.pdf"

For an end-to-end smoke test with your own input:
  bash tools/smoke_test_public.sh "/path/to/input.pdf"
EOF
