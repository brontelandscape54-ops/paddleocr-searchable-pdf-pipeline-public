#!/usr/bin/env bash
set -euo pipefail

# 利用者向けの正規ランチャー。
# 既存の仮想環境を名前だけで信用せず、必要モジュールを実際にimportできるPythonを
# 探してから、パイプライン本体へ明示的に渡す。

ROOT="$(cd "$(dirname "$0")" && pwd)"

paddle_python_works() {
  local python_path="$1"
  [ -x "$python_path" ] || return 1
  "$python_path" -c 'import paddleocr, paddlex, onnxruntime' >/dev/null 2>&1
}

helper_python_works() {
  local python_path="$1"
  [ -x "$python_path" ] || return 1
  "$python_path" -c 'import fitz, PIL, reportlab, pypdf, fontTools' >/dev/null 2>&1
}

select_paddle_python() {
  local candidate

  if [ -n "${PADDLE_PYTHON:-}" ]; then
    if paddle_python_works "$PADDLE_PYTHON"; then
      echo "$PADDLE_PYTHON"
      return
    fi
    echo "[ERROR] PADDLE_PYTHONが実行不能、または必要モジュール不足です: $PADDLE_PYTHON" >&2
    return 1
  fi

  candidate="$ROOT/.venv_paddle/bin/python"
  if paddle_python_works "$candidate"; then
    echo "$candidate"
    return
  fi

  return 1
}

select_helper_python() {
  local candidate

  if [ -n "${HELPER_PYTHON:-}" ]; then
    if helper_python_works "$HELPER_PYTHON"; then
      echo "$HELPER_PYTHON"
      return
    fi
    echo "[ERROR] HELPER_PYTHONに必要モジュールがありません: $HELPER_PYTHON" >&2
    return 1
  fi

  local candidates=()
  if [ -n "${VIRTUAL_ENV:-}" ]; then
    candidates+=("$VIRTUAL_ENV/bin/python")
  fi
  candidates+=("$ROOT/.venv/bin/python")
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi

  for candidate in "${candidates[@]}"; do
    if helper_python_works "$candidate"; then
      echo "$candidate"
      return
    fi
  done
  return 1
}

if ! RESOLVED_PADDLE_PYTHON="$(select_paddle_python)"; then
  echo "[ERROR] PaddleOCR用Pythonが見つかりません。" >&2
  echo "" >&2
  echo "確認対象: $ROOT/.venv_paddle/bin/python" >&2
  if [ -e "$ROOT/.venv_paddle" ]; then
    echo "[INFO] .venv_paddleは存在しますが、移動後に壊れているか依存不足です。" >&2
  else
    echo "[INFO] .venv_paddle自体が存在しません。" >&2
  fi
  echo "" >&2
  echo "復旧方法:" >&2
  echo "  bash tools/rebuild_paddle_venv.sh" >&2
  echo "" >&2
  echo "別環境を使う場合:" >&2
  echo "  PADDLE_PYTHON=/path/to/python bash paddleocr.sh ..." >&2
  exit 1
fi

if ! RESOLVED_HELPER_PYTHON="$(select_helper_python)"; then
  echo "[ERROR] fitz / Pillow / ReportLab / pypdf / fontTools を備えたPythonが見つかりません。" >&2
  echo "        HELPER_PYTHON=/path/to/python を指定してください。" >&2
  exit 1
fi

export PADDLE_PYTHON="$RESOLVED_PADDLE_PYTHON"
export HELPER_PYTHON="$RESOLVED_HELPER_PYTHON"

echo "[INFO] Paddle Python: $PADDLE_PYTHON"
echo "[INFO] Helper Python: $HELPER_PYTHON"

exec bash "$ROOT/paddleocr_input.sh" "$@"
