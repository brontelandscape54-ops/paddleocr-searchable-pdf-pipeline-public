#!/usr/bin/env bash
set -euo pipefail

# PaddleOCR単独パイプラインの内部実行本体。
# 利用者向けの正規入口は paddleocr.sh であり、このファイルは同ランチャーから呼び出される。
# OCRエンジン、入力前処理、PDFレンダラを分離し、中間生成物を残す。
# これは、結果の検証・部分再実行・将来の部品交換を安全にするための設計である。

SCRIPT_START_EPOCH="$(date +%s)"
SCRIPT_START_TEXT="$(date '+%Y-%m-%d %H:%M:%S')"
SCRIPT_ARGS="$*"
ROOT="$(cd "$(dirname "$0")" && pwd)"
CODE_ROOT="$ROOT/code"
TOOLS_ROOT="$ROOT/tools"
JOBS_ROOT="$ROOT/jobs"
LOG_DIR=""

format_seconds() {
  local total="$1"
  printf "%02d:%02d:%02d" $((total / 3600)) $(((total % 3600) / 60)) $((total % 60))
}

write_timing_summary() {
  local status="$1"
  local end_epoch elapsed end_text
  end_epoch="$(date +%s)"
  end_text="$(date '+%Y-%m-%d %H:%M:%S')"
  elapsed=$((end_epoch - SCRIPT_START_EPOCH))
  {
    echo "status=$status"
    echo "start=$SCRIPT_START_TEXT"
    echo "end=$end_text"
    echo "elapsed_seconds=$elapsed"
    echo "elapsed_hms=$(format_seconds "$elapsed")"
    echo "script=$0"
    echo "args=$SCRIPT_ARGS"
  } > "$LOG_DIR/timing_summary.log"
}

on_exit() {
  local status="$?"
  if [ -n "$LOG_DIR" ] && [ -d "$LOG_DIR" ]; then
    write_timing_summary "$status"
  fi
}
trap on_exit EXIT

usage() {
  cat <<'EOF'
内部実行用スクリプトです。通常は ./paddleocr.sh を使用してください。

使い方:
  bash paddleocr_input.sh /path/to/input.pdf [job_name] [dpi]
  bash paddleocr_input.sh /path/to/image_or_folder [job_name] [dpi]

引数:
  1. input path : PDF / 単一画像 / 画像フォルダ
  2. job_name   : 省略時は入力名 + timestamp
  3. dpi        : PDF画像化DPI。既定 180

主な環境変数:
  PADDLE_PYTHON                 PaddleOCR環境のPython
  HELPER_PYTHON                 PyMuPDF/Pillow/ReportLab/pypdf環境のPython
  PADDLE_NORMALIZE_PDF          1: 巨大PDFページを安全化（既定） / 0: 無効
  PADDLE_MAX_PIXELS             巨大ページ判定。既定 25000000
  PADDLE_TARGET_LONG_EDGE_PX    縮小後長辺。既定 3400
  PADDLE_OVERWRITE              1: 既存JSONも再OCR / 0: 再利用（既定）
EOF
}

if [ $# -lt 1 ] || [ $# -gt 3 ]; then
  usage
  exit 1
fi

INPUT_PATH="$1"
JOB_NAME="${2:-}"
DPI="${3:-180}"

if [ ! -e "$INPUT_PATH" ]; then
  echo "[ERROR] 入力が見つかりません: $INPUT_PATH" >&2
  exit 1
fi
if ! [[ "$DPI" =~ ^[1-9][0-9]*$ ]]; then
  echo "[ERROR] dpi は正の整数で指定してください: $DPI" >&2
  exit 1
fi

resolve_abs() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
}

sanitize_name() {
  python3 - "$1" <<'PY'
import re
import sys
name = sys.argv[1]
for char in "[]?*{}":
    name = name.replace(char, "_")
name = name.replace("/", "_")
name = re.sub(r"[\x00-\x1f\x7f]", "_", name)
name = re.sub(r"_+", "_", name).strip(" ._")
print(name or "paddleocr_job")
PY
}

resolve_paddle_python() {
  if [ -n "${PADDLE_PYTHON:-}" ] && [ -x "$PADDLE_PYTHON" ]; then
    echo "$PADDLE_PYTHON"
    return
  fi
  if [ -x "$ROOT/.venv_paddle/bin/python" ]; then
    echo "$ROOT/.venv_paddle/bin/python"
    return
  fi
  return 1
}

resolve_helper_python() {
  if [ -n "${HELPER_PYTHON:-}" ] && [ -x "$HELPER_PYTHON" ]; then
    echo "$HELPER_PYTHON"
    return
  fi
  if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    echo "$VIRTUAL_ENV/bin/python"
    return
  fi
  local candidates=("$ROOT/.venv/bin/python")
  local candidate
  for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  command -v python3
}

if ! PADDLE_PY="$(resolve_paddle_python)"; then
  echo "[ERROR] PaddleOCR用Pythonが見つかりません。PADDLE_PYTHONを指定してください。" >&2
  exit 1
fi
HELPER_PY="$(resolve_helper_python)"

# 依存不足を処理途中ではなく開始時に明示する。
"$PADDLE_PY" -c 'import paddleocr, onnxruntime' || {
  echo "[ERROR] PaddleOCR環境に paddleocr / onnxruntime がありません" >&2
  exit 1
}
"$HELPER_PY" -c 'import fitz, PIL, reportlab, pypdf' || {
  echo "[ERROR] helper環境に pymupdf / pillow / reportlab / pypdf が必要です" >&2
  exit 1
}

INPUT_ABS="$(resolve_abs "$INPUT_PATH")"
INPUT_NAME="$(basename "$INPUT_ABS")"
if [ -d "$INPUT_ABS" ]; then
  INPUT_STEM="$INPUT_NAME"
else
  INPUT_STEM="${INPUT_NAME%.*}"
fi
OUTPUT_PREFIX="$(sanitize_name "$INPUT_STEM")"
if [ -z "$JOB_NAME" ]; then
  JOB_NAME="${OUTPUT_PREFIX}_paddleocr_$(date +%Y%m%d_%H%M%S)"
fi
JOB_NAME="$(sanitize_name "$JOB_NAME")"

JOB_DIR="$JOBS_ROOT/$JOB_NAME"
PREPROCESS_DIR="$JOB_DIR/preprocessed"
PAGES_DIR="$JOB_DIR/pages"
OCR_DIR="$JOB_DIR/paddle_ocr"
JSON_DIR="$OCR_DIR/json"
TEXT_DIR="$OCR_DIR/txt"
OUTPUT_DIR="$JOB_DIR/output"
PAGE_PDF_DIR="$JOB_DIR/searchable_pdf/pages_pdf"
MERGED_PDF="$JOB_DIR/searchable_pdf/${OUTPUT_PREFIX}_paddleocr_searchable.pdf"
SMALL_PDF="$JOB_DIR/searchable_pdf/${OUTPUT_PREFIX}_paddleocr_searchable_small_150dpi.pdf"
LOG_DIR="$JOB_DIR/logs"

mkdir -p "$PREPROCESS_DIR" "$PAGES_DIR" "$OCR_DIR" "$OUTPUT_DIR" "$PAGE_PDF_DIR" "$LOG_DIR"

PADDLE_NORMALIZE_PDF="${PADDLE_NORMALIZE_PDF:-1}"
PADDLE_MAX_PIXELS="${PADDLE_MAX_PIXELS:-25000000}"
PADDLE_TARGET_LONG_EDGE_PX="${PADDLE_TARGET_LONG_EDGE_PX:-3400}"
PADDLE_OVERWRITE="${PADDLE_OVERWRITE:-0}"

run_stage() {
  local stage="$1"
  shift
  local log="$LOG_DIR/${stage}.log"
  echo
  echo "=== $stage ==="
  echo "[COMMAND] $*"
  "$@" 2>&1 | tee "$log"
}

PREP_INPUT="$INPUT_ABS"
PREP_INPUT_KIND="original"
if [ "$PADDLE_NORMALIZE_PDF" = "1" ]; then
  case "$INPUT_ABS" in
    *.pdf|*.PDF)
      NORMALIZED_PDF="$PREPROCESS_DIR/${OUTPUT_PREFIX}_ocrsafe_${PADDLE_TARGET_LONG_EDGE_PX}px.pdf"
      if [ ! -f "$NORMALIZED_PDF" ]; then
        run_stage 00_normalize_pdf \
          "$HELPER_PY" "$TOOLS_ROOT/normalize_pdf_for_ocr.py" \
          "$INPUT_ABS" "$NORMALIZED_PDF" \
          --dpi "$DPI" \
          --max-pixels "$PADDLE_MAX_PIXELS" \
          --target-long-edge-px "$PADDLE_TARGET_LONG_EDGE_PX"
      else
        echo "[00_normalize_pdf] skip: $NORMALIZED_PDF" | tee "$LOG_DIR/00_normalize_pdf.log"
      fi
      PREP_INPUT="$NORMALIZED_PDF"
      PREP_INPUT_KIND="normalized_pdf"
      ;;
  esac
fi

cat > "$LOG_DIR/00_run_config.txt" <<EOF
INPUT_ABS=$INPUT_ABS
PREP_INPUT=$PREP_INPUT
PREP_INPUT_KIND=$PREP_INPUT_KIND
JOB_NAME=$JOB_NAME
JOB_DIR=$JOB_DIR
DPI=$DPI
PADDLE_NORMALIZE_PDF=$PADDLE_NORMALIZE_PDF
PADDLE_MAX_PIXELS=$PADDLE_MAX_PIXELS
PADDLE_TARGET_LONG_EDGE_PX=$PADDLE_TARGET_LONG_EDGE_PX
PADDLE_OVERWRITE=$PADDLE_OVERWRITE
PADDLE_PY=$PADDLE_PY
HELPER_PY=$HELPER_PY
MERGED_PDF=$MERGED_PDF
SMALL_PDF=$SMALL_PDF
EOF

PAGES_SENTINEL="$PAGES_DIR/.complete"
if [ ! -f "$PAGES_SENTINEL" ]; then
  rm -f "$PAGES_DIR"/page_*.png
  run_stage 01_prepare_pages \
    "$HELPER_PY" "$CODE_ROOT/prepare_input_pages.py" \
    "$PREP_INPUT" "$PAGES_DIR" --dpi "$DPI"
  touch "$PAGES_SENTINEL"
else
  echo "[01_prepare_pages] skip: completed page images exist" | tee "$LOG_DIR/01_prepare_pages.log"
fi

OCR_ARGS=(
  "$PADDLE_PY" "$ROOT/paddle_batch_ocr.py"
  --pages-dir "$PAGES_DIR"
  --output-dir "$OCR_DIR"
)
if [ "$PADDLE_OVERWRITE" = "1" ]; then
  OCR_ARGS+=(--overwrite)
fi
run_stage 02_paddle_ocr env \
  PYTHONUNBUFFERED=1 \
  OMP_NUM_THREADS=2 \
  VECLIB_MAXIMUM_THREADS=2 \
  MKL_NUM_THREADS=2 \
  NUMEXPR_NUM_THREADS=2 \
  "${OCR_ARGS[@]}"

run_stage 03_aggregate_outputs \
  "$HELPER_PY" "$CODE_ROOT/aggregate_paddle_outputs.py" \
  "$OCR_DIR" "$OUTPUT_DIR" --prefix "$OUTPUT_PREFIX"

build_page_pdfs() {
  local page_count=0 image_path stem json_path pdf_path
  rm -f "$PAGE_PDF_DIR"/page_*.pdf
  for image_path in "$PAGES_DIR"/page_*.png; do
    [ -e "$image_path" ] || continue
    stem="$(basename "$image_path" .png)"
    json_path="$JSON_DIR/${stem}_paddle_small.json"
    pdf_path="$PAGE_PDF_DIR/${stem}.pdf"
    if [ ! -f "$json_path" ]; then
      echo "[ERROR] JSONがありません: $json_path" >&2
      return 1
    fi
    "$HELPER_PY" "$ROOT/paddle_json_to_searchable_pdf.py" \
      --image "$image_path" --json "$json_path" --out "$pdf_path"
    page_count=$((page_count + 1))
  done
  if [ "$page_count" -eq 0 ]; then
    echo "[ERROR] ページPDFを生成できませんでした" >&2
    return 1
  fi
  echo "[DONE] page PDFs: $page_count"
}
run_stage 04_searchable_pdf_pages build_page_pdfs

run_stage 05_merge_pdf \
  "$HELPER_PY" "$CODE_ROOT/merge_pdfs.py" "$PAGE_PDF_DIR" "$MERGED_PDF"

run_stage 06_verify_pdf \
  "$HELPER_PY" "$CODE_ROOT/verify_searchable_pdf.py" "$MERGED_PDF"

run_stage 07_compress_pdf \
  "$HELPER_PY" "$CODE_ROOT/compress_pdf_150dpi.py" "$MERGED_PDF" "$SMALL_PDF"

cat <<EOF

=== PADDLEOCR PIPELINE FINISHED ===
JOB_DIR            : $JOB_DIR
PAGES_DIR          : $PAGES_DIR
JSON_DIR           : $JSON_DIR
TEXT_DIR           : $TEXT_DIR
OUTPUT_DIR         : $OUTPUT_DIR
PAGE_PDF_DIR       : $PAGE_PDF_DIR
MERGED_PDF         : $MERGED_PDF
SMALL_PDF          : $SMALL_PDF
LOG_DIR            : $LOG_DIR
EOF
