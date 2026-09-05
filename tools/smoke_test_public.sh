#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INPUT_PATH="${1:-}"
JOB_NAME="${2:-public_smoke_$(date +%Y%m%d_%H%M%S)}"
DPI="${3:-180}"

fail() {
  echo "[ERROR] $*" >&2
  exit 1
}

check_file() {
  [ -f "$ROOT/$1" ] || fail "required file missing: $1"
}

echo "=== public tree smoke test ==="
echo "ROOT=$ROOT"

required_files=(
  "README.md"
  "README_en.md"
  "LICENSE"
  "THIRD_PARTY_LICENSES.md"
  "requirements-paddle.txt"
  "requirements-helper.txt"
  "paddleocr.sh"
  "paddleocr_input.sh"
  "paddle_batch_ocr.py"
  "paddle_json_to_searchable_pdf.py"
  "docs/DEVELOPMENT_BACKGROUND.md"
  "docs/DEVELOPMENT_BACKGROUND_en.md"
  "docs/OCR_SELECTION_HISTORY_SUPPLEMENT.md"
  "docs/OCR_SELECTION_HISTORY_SUPPLEMENT_en.md"
  "docs/PIPELINE_HARDENING_HISTORY.md"
  "docs/PIPELINE_HARDENING_HISTORY_en.md"
  "code/aggregate_paddle_outputs.py"
  "code/compress_pdf_150dpi.py"
  "code/merge_pdfs.py"
  "code/prepare_input_pages.py"
  "code/verify_searchable_pdf.py"
  "tools/normalize_pdf_for_ocr.py"
  "tools/rebuild_paddle_venv.sh"
  "tools/report_font_fallbacks.py"
  "tools/setup.sh"
  "tools/setup_fonts.sh"
  "tools/smoke_test_public.sh"
  "tools/validate_jigmo_supplementary.py"
  "tests/test_empty_ocr_page.py"
  "tests/test_reportlab_cmap_chunking.py"
)

for rel in "${required_files[@]}"; do
  check_file "$rel"
done

echo "[OK] required files present"

python3 - "$ROOT" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
problems = []

skip_exact = {
    '.git',
    'jobs',
    '__pycache__',
    '.pytest_cache',
    '.paddlex',
    'models',
    'model_cache',
    'fonts',
}

def should_skip(path: Path) -> bool:
    for part in path.relative_to(root).parts:
        if part in skip_exact or part.startswith('.venv'):
            return True
    return False

home_pattern = re.compile(r'/(?:Users|home)/[^/\s"\']+/')
for path in root.rglob('*'):
    if not path.is_file() or should_skip(path):
        continue
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        continue
    for match in home_pattern.finditer(text):
        problems.append(f"{path.relative_to(root)}: absolute user-home path: {match.group(0)}")

renderer = (root / 'paddle_json_to_searchable_pdf.py').read_text(encoding='utf-8')
if 'project_root.parent' in renderer:
    problems.append('paddle_json_to_searchable_pdf.py: parent-repository font lookup remains')
if 'HanaMinA.ttf' in renderer or 'HanaMinB.ttf' in renderer:
    problems.append('paddle_json_to_searchable_pdf.py: legacy Hanazono default remains')

if problems:
    for problem in problems:
        print(f"[ERROR] {problem}", file=sys.stderr)
    raise SystemExit(1)
PY

echo "[OK] no hard-coded user-home, parent-repository, or legacy Hanazono default detected"

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 not found"
fi

python3 -m py_compile \
  "$ROOT/paddle_batch_ocr.py" \
  "$ROOT/paddle_json_to_searchable_pdf.py" \
  "$ROOT/code/aggregate_paddle_outputs.py" \
  "$ROOT/code/compress_pdf_150dpi.py" \
  "$ROOT/code/merge_pdfs.py" \
  "$ROOT/code/prepare_input_pages.py" \
  "$ROOT/code/verify_searchable_pdf.py" \
  "$ROOT/tools/normalize_pdf_for_ocr.py" \
  "$ROOT/tools/report_font_fallbacks.py" \
  "$ROOT/tools/validate_jigmo_supplementary.py"

echo "[OK] Python syntax compilation"

if [ -x "$ROOT/.venv_paddle/bin/python" ]; then
  if "$ROOT/.venv_paddle/bin/python" -c 'import paddleocr, paddlex, onnxruntime' >/dev/null 2>&1; then
    echo "[OK] PaddleOCR environment imports"
  else
    echo "[WARN] .venv_paddle exists but required OCR imports failed"
  fi
else
  echo "[WARN] .venv_paddle not present; run: bash tools/setup.sh"
fi

HELPER=""
for candidate in \
  "$ROOT/.venv/bin/python" \
  "$(command -v python3)"
do
  [ -x "$candidate" ] || continue
  if "$candidate" -c 'import pymupdf, PIL, reportlab, pypdf, fontTools' >/dev/null 2>&1; then
    HELPER="$candidate"
    break
  fi
done

if [ -n "$HELPER" ]; then
  echo "[OK] helper imports: $HELPER"
else
  echo "[WARN] helper imports unavailable; run: bash tools/setup.sh"
fi

FONT_READY=0
if [ -n "$HELPER" ]; then
  if "$HELPER" - "$ROOT" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from paddle_json_to_searchable_pdf import resolve_font_paths

try:
    fonts = resolve_font_paths(None)
except Exception as exc:
    print(f"[WARN] font discovery failed: {exc}")
    raise SystemExit(2)

print("[OK] discovered fonts:")
for font in fonts:
    print(f"  {font}")
PY
  then
    FONT_READY=1
  else
    status="$?"
    if [ "$status" -eq 2 ]; then
      echo "[WARN] no usable Japanese TTF found automatically; run: bash tools/setup_fonts.sh"
    else
      fail "font discovery check failed unexpectedly"
    fi
  fi
fi

if [ -z "$INPUT_PATH" ]; then
  cat <<'EOF'
[INFO] static smoke test completed.
[INFO] For an end-to-end OCR smoke test, pass a PDF/image/image-directory:
  bash tools/smoke_test_public.sh "/path/to/input.pdf" [job_name] [dpi]
EOF
  exit 0
fi

[ -e "$INPUT_PATH" ] || fail "input does not exist: $INPUT_PATH"
[ -n "$HELPER" ] || fail "helper environment is required for end-to-end smoke test; run: bash tools/setup.sh"
[ "$FONT_READY" -eq 1 ] || fail "Japanese TTF fonts are required before end-to-end OCR; run: bash tools/setup_fonts.sh"

if [ ! -x "$ROOT/.venv_paddle/bin/python" ]; then
  fail ".venv_paddle is required for end-to-end smoke test; run: bash tools/setup.sh"
fi
if ! "$ROOT/.venv_paddle/bin/python" -c 'import paddleocr, paddlex, onnxruntime' >/dev/null 2>&1; then
  fail "PaddleOCR environment imports failed"
fi

echo "=== end-to-end pipeline smoke test ==="
"$ROOT/paddleocr.sh" "$INPUT_PATH" "$JOB_NAME" "$DPI"

JOB_DIR="$ROOT/jobs/$JOB_NAME"
[ -d "$JOB_DIR" ] || fail "job directory not created: $JOB_DIR"

SEARCHABLE=("$JOB_DIR"/searchable_pdf/*_paddleocr_searchable.pdf)
if [ ! -e "${SEARCHABLE[0]}" ]; then
  fail "normal searchable PDF not found"
fi

echo "[OK] end-to-end searchable PDF produced: ${SEARCHABLE[0]}"
echo "[DONE] public smoke test passed"
