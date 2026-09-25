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

## Why the production path centers on PaddleOCR

Marker was also tested in depth during development, and its recognition quality was very good where OCR succeeded. A working image-preserving searchable PDF was built from Marker `blocks.json` text and bounding-box output, so Marker was **not** rejected because its OCR quality was poor or because it could not support searchable-PDF generation.

The practical problem was operational cost on the development machine. Marker text recognition was heavy enough to make multi-page processing difficult, including MPS out-of-memory failures. With OCR disabled, however, Marker TableCell detection was fast, so an intermediate hybrid architecture was explored: Marker for table structure and PaddleOCR for text recognition.

The evaluation was then refined step by step, from character counts and whole-output similarity to an image-backed 168-cell comparison and direct assignment of PaddleOCR boxes into Marker TableCells. For the representative material, PaddleOCR alone provided usable recognition and bounding boxes. Because the final requirement was not perfect spreadsheet-style table reconstruction, but **preserving the original page while making its text searchable**, the production architecture was simplified to a PaddleOCR-centered pipeline.

For the practical problems that motivated the project, the OCRmyPDF/Tesseract detour, the Marker/NDL/Yomitoku/PaddleOCR comparisons, timing measurements, and the limitations of the evaluation methods, see [Development Background and Design Rationale](docs/DEVELOPMENT_BACKGROUND_en.md).

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

## Tested environments

The **Python CLI is the primary documented entry point**, but is still experimental. The original Bash entry points remain available for existing users.

- **macOS (Apple Silicon):** A disposable public export built fresh Python environments, downloaded fonts, and processed a synthetic one-page image into a searchable PDF, including a Ghostscript-compressed version with preserved extractable text, on Python 3.10.4.
- **Physical Boot Camp Windows x64:** Python 3.13.15 AMD64 passed Python setup and synthetic image/PDF/image-directory searchable-PDF smoke tests, including a Japanese/space-containing input path.
- **Not yet verified:** Linux end-to-end, Windows ARM64, Windows x64 emulation on ARM, actual Windows Ghostscript compression, and real-document OCR accuracy on Windows. These specific smoke tests do not establish compatibility across all Python and OS combinations.

This project uses Python 3.10–3.13, PaddleOCR / PaddleX / ONNX Runtime from `requirements-paddle.txt`, and PDF/image helpers from `requirements-helper.txt`. Ghostscript is optional and used only for the compressed PDF variant.

## Setup and run (primary Python CLI)

Clone the repository, then explicitly select an installed, supported Python interpreter. **Environment installation and font installation are separate commands.** The Python setup preserves working environments and user-supplied fonts by default and refuses to replace an existing unusable virtual environment automatically. The first OCR run may download model files.

### macOS

```bash
cd "/path/to/paddleocr-searchable-pdf-pipeline"
python3 tools/setup_python_envs.py --check
python3 tools/setup_python_envs.py --install-envs
python3 tools/setup_fonts.py --install-fonts
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf" --check
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf" my_new_job 180
```

Confirm that `python3` is Python 3.10–3.13. `--check` validates the input and prerequisites without creating a job. The job name and rendering DPI (`180` in this example) are optional.

### Windows x64 (PowerShell)

Install x64 Python 3.10–3.13 first. These commands use the Python 3.13 launcher; change `py -V:3.13` if you use another supported version.

```powershell
Set-Location "C:\path\to\paddleocr-searchable-pdf-pipeline"
py -V:3.13 tools/setup_python_envs.py --check
py -V:3.13 tools/setup_python_envs.py --install-envs
py -V:3.13 tools/setup_fonts.py --install-fonts
& ".\.venv\Scripts\python.exe" ".\paddleocr_cli.py" "C:\path\to\input.pdf" --check
& ".\.venv\Scripts\python.exe" ".\paddleocr_cli.py" "C:\path\to\input.pdf" "my_new_job" 180
```

The tested Windows x64 host needed Microsoft Visual C++ Redistributable x64 for ONNX Runtime DLL loading. The Python CLI configures UTF-8 for its child-process logs; manual PowerShell encoding environment overrides are unnecessary.

**Input** can be a PDF, a single image, or a directory of page images. Use a new job name for a changed input or changed processing settings. The Python CLI refuses to reuse an existing job with a missing or mismatched input-identity record.

### Subsequent runs (after first-time setup)

You normally do **not** need to reinstall the Python environments or Japanese fonts for each OCR job. To process a new input, just run the CLI:

macOS (Terminal):

```bash
cd "/path/to/paddleocr-searchable-pdf-pipeline"
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf"
```

Paste the input path using Finder’s Copy as Pathname command, or drag the input from Finder into Terminal. Existing development environments without a repository-local `.venv` can use `.venv_paddle/bin/python` to launch the CLI if it has the required dependencies; the CLI independently selects its OCR and PDF-processing interpreters.

Windows x64 (PowerShell):

```powershell
Set-Location "C:\path\to\paddleocr-searchable-pdf-pipeline"
.\.venv\Scripts\python.exe .\paddleocr_cli.py "C:\path\to\input.pdf"
```

Copy the input path from File Explorer with “Copy as path” and paste it into PowerShell. Dragging the file into the terminal may also insert its path, depending on the terminal environment. The executable paths above have no spaces, so PowerShell’s call operator `&` and executable-path quotes are unnecessary. For an executable path containing spaces, use the `& "C:\path with spaces\python.exe" ...` form.

Omitting the job name creates a new timestamped job. When resuming an existing job, preserve its original input, settings and job name; **use a new job name for changed input or settings**. See the setup examples above for explicit job name and DPI arguments.

### Legacy Bash workflow (existing macOS users)

The original `paddleocr.sh` entry point and `tools/setup.sh` remain available for users continuing an existing Bash-based workflow. Bash setup also performs regression checks, so it is not identical to the two separate Python setup commands.

```bash
bash tools/setup.sh
./paddleocr.sh "/path/to/input.pdf"
```

You do not need to install Bash to use the Python CLI on Windows.

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
python3 tools/setup_fonts.py --install-fonts
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
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf"
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

The primary entry point is `paddleocr_cli.py`. On macOS:

```bash
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf"
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf" my_new_job 180
```

On Windows, use `& ".\.venv\Scripts\python.exe" ".\paddleocr_cli.py" "C:\path\to\input.pdf" "my_new_job" 180`. Run the `--check` form first to validate the input and setup without writing a job.

Input can be a PDF, a single image, or a directory of page images. Use a new job name when the input or processing settings change; intermediate outputs are preserved to support safe reruns.

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

Existing compact JSON is reused by default. To force OCR again for the **same** input and processing settings on macOS:

```bash
PADDLE_OVERWRITE=1 .venv/bin/python paddleocr_cli.py "/path/to/input.pdf" same_job_name 180
```

On Windows PowerShell, set `$env:PADDLE_OVERWRITE = "1"` before running the Python CLI. Use a new job name for a changed input or processing settings.

## Large PDF pages

PDF pages estimated to exceed 25 million pixels at the selected DPI are normalized to roughly 3400 px on the long edge before OCR. Normal-sized pages are left unchanged.

On macOS, disable normalization with:

```bash
PADDLE_NORMALIZE_PDF=0 .venv/bin/python paddleocr_cli.py "/path/to/input.pdf"
```

Or adjust its thresholds:

```bash
PADDLE_MAX_PIXELS=30000000 PADDLE_TARGET_LONG_EDGE_PX=3800 \
  .venv/bin/python paddleocr_cli.py "/path/to/input.pdf" my_new_job 180
```

On Windows PowerShell set the corresponding environment variables, e.g. `$env:PADDLE_NORMALIZE_PDF = "0"`. Use a new job name when changing processing settings.

## Validation and smoke tests

After merging page PDFs, the pipeline verifies that text can actually be extracted. If Ghostscript is available, it can also create a compressed PDF and verify extractable-text retention. Without Ghostscript, the normal searchable PDF remains available.

After Python setup, run the exported regression tests on macOS with:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

The Bash-based `bash tools/smoke_test_public.sh` remains available for static public-tree checks on macOS. Its optional end-to-end mode **still invokes the legacy Bash workflow**; it is not the Windows Python CLI smoke-test entry point.

## Third-party software

This repository does not commit PaddleOCR, PaddleX, Japanese font binaries, PyMuPDF/MuPDF, or Ghostscript source trees. They remain third-party components under their respective licenses. See `THIRD_PARTY_LICENSES.md`.