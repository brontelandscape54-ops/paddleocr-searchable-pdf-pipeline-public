#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT/.venv_paddle"
REQUIREMENTS="$ROOT/requirements-paddle.txt"

select_python() {
  local candidate
  local candidates=()

  if [ -n "${BASE_PYTHON:-}" ]; then
    candidates+=("$BASE_PYTHON")
  fi
  if command -v python3.10 >/dev/null 2>&1; then
    candidates+=("$(command -v python3.10)")
  fi
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi

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
  echo "[ERROR] Python 3.10〜3.13が見つかりません。" >&2
  echo "        BASE_PYTHON=/path/to/python3.10 を指定してください。" >&2
  exit 1
fi

if [ ! -f "$REQUIREMENTS" ]; then
  echo "[ERROR] requirements file not found: $REQUIREMENTS" >&2
  exit 1
fi

if [ -e "$VENV_DIR" ]; then
  backup="$ROOT/.venv_paddle_broken_$(date +%Y%m%d_%H%M%S)"
  echo "[INFO] existing environment will be preserved: $backup"
  mv "$VENV_DIR" "$backup"
fi

echo "[INFO] base Python: $BASE"
"$BASE" --version

echo "[INFO] creating: $VENV_DIR"
"$BASE" -m venv "$VENV_DIR"

PYTHON="$VENV_DIR/bin/python"

echo "[INFO] upgrading packaging tools"
"$PYTHON" -m pip install --upgrade pip setuptools wheel

echo "[INFO] installing PaddleOCR environment"
"$PYTHON" -m pip install -r "$REQUIREMENTS"

echo "[INFO] verifying imports"
"$PYTHON" - <<'PY'
import numpy
import onnxruntime
import paddleocr
import paddlex

print("[OK] paddleocr", getattr(paddleocr, "__version__", "unknown"))
print("[OK] paddlex", getattr(paddlex, "__version__", "unknown"))
print("[OK] onnxruntime", onnxruntime.__version__)
print("[OK] numpy", numpy.__version__)
PY

echo "[DONE] PaddleOCR environment rebuilt: $VENV_DIR"
