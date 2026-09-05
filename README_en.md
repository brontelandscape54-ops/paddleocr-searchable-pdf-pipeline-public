# PaddleOCR Searchable PDF Pipeline

English | [日本語](README.md)

A practical pipeline for turning PDFs, single images, or image folders into searchable PDFs and structured OCR outputs with PaddleOCR.

> This is an unofficial independent project using PaddleOCR. It is not affiliated with or endorsed by PaddlePaddle.

## Why this pipeline?

- **Designed with Japanese historical documents in mind** — useful for old forms, variant characters, and CJK extension characters.
- **Preserves the original scanned page** — the visible PDF page remains the source image; OCR is added as an invisible Unicode text layer.
- **Preserves tables, illustrations, marginalia, and complex layouts visually** — the pipeline does not redraw the page from OCR text.
- **Character-by-character font fallback** — M PLUS 1p is combined with Jigmo/Jigmo2/Jigmo3 for broad CJK coverage.
- **Reproducible setup and validation** — pinned OCR dependencies, verified font downloads, PDF/CMap regression tests, and searchable-text verification.

## Layout preservation: tables and figures

The searchable PDF keeps the original scanned page as the visible layer and places OCR text over it as an invisible Unicode text layer. As a result, tables, ruled lines, illustrations, seals, marginal notes, unusual line arrangements, and other complex visual layouts remain visually unchanged instead of being reconstructed from OCR output.

This is especially useful for historical materials where the page itself carries information that would be lost by converting the document into plain text alone.

**Important:** this is not a dedicated table-structure extraction engine. It does not promise to reconstruct tables as editable spreadsheets or recover logical row/column structure perfectly. Its strength is preserving the original visual layout while adding searchability and copyable text.

## Pipeline

```text
PDF / image / image folder
→ OCR-safe preprocessing for oversized PDF pages
→ page images
→ PaddleOCR
→ per-page JSON / TXT
→ merged TXT / Markdown / JSON / JSONL
→ character-by-character Japanese font fallback
→ searchable PDF pages
→ merged searchable PDF
→ searchable-text verification
→ optional Ghostscript-compressed searchable PDF
```

The searchable-PDF renderer embeds real TrueType fonts and checks each font's cmap before selecting a font for each character.

## Tested environment

The current pipeline has been validated primarily on **macOS**.

- Bash
- Python 3.10–3.13
- PaddleOCR / PaddleX / ONNX Runtime versions pinned in `requirements-paddle.txt`
- helper PDF/image libraries in `requirements-helper.txt`
- optional Ghostscript (`gs`) for compressed PDF output

The public version avoids known macOS-only assumptions in its main pipeline where practical. Timing logs use portable `date` forms and font discovery includes common macOS and Linux locations. Linux has not yet been end-to-end validated, so it is not claimed as a tested target yet.

## Quick setup

After cloning the repository, run:

```bash
bash tools/setup.sh
```

This one command:

1. checks for Python 3.10–3.13;
2. creates or reuses `.venv_paddle` for PaddleOCR / PaddleX / ONNX Runtime;
3. creates or reuses the helper `.venv`;
4. downloads the recommended Japanese fonts into the ignored local `fonts/` directory;
5. verifies pinned font sources and checksums;
6. runs the PDF/CMap regression tests;
7. validates a real supplementary-plane Jigmo character through PDF generation and exact extraction;
8. runs the static public smoke test.

Existing working environments are reused. Existing user-provided fonts are preserved by default.

Useful options:

```bash
bash tools/setup.sh --rebuild       # rebuild both Python environments
bash tools/setup.sh --no-fonts      # do not download recommended fonts
bash tools/setup.sh --force-fonts   # replace setup-managed local fonts
```

Cloning the repository itself never runs external downloads. Font retrieval happens only when you explicitly run `tools/setup.sh` or `tools/setup_fonts.sh`.

The normal entry point after setup is:

```bash
./paddleocr.sh "/path/to/input.pdf"
```

### Manual setup

Advanced users can still perform each step separately:

```bash
bash tools/rebuild_paddle_venv.sh

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-helper.txt

bash tools/setup_fonts.sh
bash tools/smoke_test_public.sh
```

## Japanese font fallback

Font fallback is a core part of the searchable-PDF renderer, not only a visual preference.

The recommended order is:

```text
MPLUS1p-Medium.ttf
→ Jigmo.ttf
→ Jigmo2.ttf
→ Jigmo3.ttf
```

For every OCR character, the renderer reads each registered TTF's cmap and selects the first font that contains that Unicode code point.

- **M PLUS 1p** handles ordinary Japanese text as the primary font.
- **Jigmo** covers CJK Unified Ideographs in the BMP / Extension A range needed when M PLUS lacks a code point.
- **Jigmo2** and **Jigmo3** extend fallback coverage into supplementary-plane CJK blocks through Unicode 17.0 / Extension J.
- If a character is not present in any registered font, the renderer records it as unsupported and prints a warning.

The renderer also tries a one-character NFKC-normalized form when the original code point is unavailable. This should not be treated as a substitute for suitable historical-character fonts.

The Jigmo migration was validated against an existing 10-page historical-document OCR result: the old Hanazono configuration and the new Jigmo configuration produced identical coverage totals (`7870` M PLUS occurrences plus `14` fallback occurrences, `9` unique fallback characters, `0` unsupported). A real supplementary-plane character (`U+20000`) was also rendered with Jigmo2, extracted exactly with pypdf, and parsed by Ghostscript without a CMap warning.

### Supplying fonts

Font binaries are intentionally **not bundled in Git history**.

The easiest route is:

```bash
bash tools/setup_fonts.sh
```

This populates the ignored local directory:

```text
fonts/
├── MPLUS1p-Medium.ttf
├── Jigmo.ttf
├── Jigmo2.ttf
├── Jigmo3.ttf
└── licenses/
```

The setup helper uses pinned sources and integrity checks. See `THIRD_PARTY_LICENSES.md` for provenance and licensing notes.

You can instead place your own compatible TTF files under `fonts/`, use system fonts, or set `PADDLE_PDF_FONTS` explicitly:

```bash
export PADDLE_PDF_FONTS="$PWD/fonts/MPLUS1p-Medium.ttf:$PWD/fonts/Jigmo.ttf:$PWD/fonts/Jigmo2.ttf:$PWD/fonts/Jigmo3.ttf"
./paddleocr.sh "/path/to/input.pdf"
```

The renderer also searches common system font locations on macOS and Linux, including:

```text
~/Library/Fonts
/Library/Fonts
/System/Library/Fonts/Supplemental
~/.local/share/fonts
~/.fonts
/usr/local/share/fonts
/usr/share/fonts
```

When invoking `paddle_json_to_searchable_pdf.py` or `tools/report_font_fallbacks.py` directly, `--font-path` may be repeated in priority order. If at least one `--font-path` is supplied, only those explicitly supplied font files are used; automatic local/system fallback discovery is not appended. `PADDLE_PDF_FONTS` behaves the same way as an explicit priority list.

If no usable Japanese TTF is found, searchable-PDF generation stops with an error rather than silently creating a text layer with an unknown substitute font.

### Checking which font was used

PDF generation prints each registered font and its used-character count. Unsupported characters are also reported.

For a detailed audit from existing PaddleOCR JSON, without rerunning OCR or regenerating the PDF, use:

```bash
.venv/bin/python tools/report_font_fallbacks.py \
  jobs/<job_name>/paddle_ocr/json
```

To validate the supplementary-plane path against the locally installed Jigmo fonts:

```bash
.venv/bin/python tools/validate_jigmo_supplementary.py
```

## Usage

Run OCR on a PDF:

```bash
./paddleocr.sh "/path/to/input.pdf"
```

Specify a job name and rendering DPI:

```bash
./paddleocr.sh "/path/to/input.pdf" my_job_name 180
```

Input may be a PDF, a single image, or a directory of page images.

Use a new job name when the input document changes. Existing page images and OCR JSON may otherwise be reused intentionally by the restart mechanism.

## Output

```text
jobs/<job_name>/
├── preprocessed/
├── pages/
├── paddle_ocr/
│   ├── json/
│   ├── txt/
│   ├── font_fallback_report/
│   └── paddle_batch_summary.csv
├── output/
│   ├── <name>_paddle.txt
│   ├── <name>_paddle.md
│   ├── <name>_paddle.json
│   └── <name>_paddle_pages.jsonl
├── searchable_pdf/
│   ├── pages_pdf/
│   ├── <name>_paddleocr_searchable.pdf
│   └── <name>_paddleocr_searchable_small_150dpi.pdf
└── logs/
```

`jobs/` is intentionally excluded from Git. It contains reusable intermediate OCR results and troubleshooting information, so it should not automatically be treated as disposable temporary data.

## Re-running OCR

Existing compact JSON is reused by default. To force OCR again:

```bash
PADDLE_OVERWRITE=1 ./paddleocr.sh "/path/to/input.pdf" same_job_name 180
```

## Large PDF pages

By default, PDF pages estimated to exceed 25 million pixels at the selected DPI are normalized to roughly 3400 px on the long edge before OCR. Normal-sized pages are left unchanged.

Disable this behavior:

```bash
PADDLE_NORMALIZE_PDF=0 ./paddleocr.sh "/path/to/input.pdf"
```

Tune it:

```bash
PADDLE_MAX_PIXELS=30000000 \
PADDLE_TARGET_LONG_EDGE_PX=3800 \
./paddleocr.sh "/path/to/input.pdf" my_job 180
```

## Validation and smoke tests

The pipeline does not treat PDF creation alone as success. After merging page PDFs, it verifies that searchable text can be extracted.

If Ghostscript is installed, the pipeline also creates a smaller 150-dpi-oriented PDF and checks that the compressed PDF retains an acceptable amount of extractable text. If that check fails, the invalid compressed output is removed rather than kept as a successful result.

Run the static public-tree smoke test:

```bash
bash tools/smoke_test_public.sh
```

Run an end-to-end OCR smoke test with your own input:

```bash
bash tools/smoke_test_public.sh "/path/to/input.pdf"
```

The public-release regression suite includes tests for empty OCR pages and the ReportLab ToUnicode CMap compatibility fix, including supplementary-plane Unicode mappings.

Ghostscript is optional; without `gs`, the normal searchable PDF remains available and the compression stage is skipped.

## Third-party software

This repository does not commit PaddleOCR, PaddleX, Japanese font binaries, PyMuPDF/MuPDF, or Ghostscript source trees. They remain third-party components under their respective licenses. See `THIRD_PARTY_LICENSES.md`.
