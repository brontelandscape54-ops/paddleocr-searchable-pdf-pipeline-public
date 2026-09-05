# PaddleOCR Pipeline Hardening History

[日本語](PIPELINE_HARDENING_HISTORY.md) | English

This document continues the [OCR Selection History Supplement](OCR_SELECTION_HISTORY_SUPPLEMENT_en.md).

The earlier supplement explains why the project moved from experiments involving Marker, NDL Classical OCR Lite, Yomitoku, and PaddleOCR toward a PaddleOCR-centered architecture. This document covers the next phase: **how a successful one-page PaddleOCR experiment became a reusable pipeline that could accept a PDF directly, preserve restartable intermediate data, generate searchable PDFs, validate compression, and survive real-world failure cases**.

The main period covered here begins on June 21, 2026. Timings, sizes, character counts, and other measurements below come from particular development documents, hardware, and settings. They are historical engineering records, not general benchmarks.

## 1. Starting point: one page worked, but the five-page batch path was still broken

The successful one-page PaddleOCR comparison already used:

```text
PP-OCRv6_small_det
PP-OCRv6_small_rec
engine = onnxruntime
provider = CPUExecutionProvider
```

On the representative table page, it produced 214 OCR regions, 726 characters, mean confidence 0.9741, and a searchable PDF from which 720 characters could be extracted.

The first multi-page batch implementation, however, had different initialization settings:

```text
PP-OCRv5_mobile_det
PP-OCRv5_mobile_rec
engine = paddle
```

The `.venv_paddle` environment did not contain `paddlepaddle`; it was an ONNX Runtime environment. The batch run therefore stopped with:

```text
Engine 'paddle_static' is unavailable because dependency 'paddlepaddle' is not installed.
```

The fix was not to add another OCR stack. It was to **copy the already-proven one-page configuration faithfully into the batch pipeline**.

The batch path was therefore standardized on PP-OCRv6 small models with ONNX Runtime and CPUExecutionProvider.

## 2. A five-page minimum viable production flow succeeded

After that correction, a five-page document completed the following sequence:

```text
page images
→ PaddleOCR on all pages
→ per-page JSON / TXT
→ per-page searchable PDFs
→ five-page merged searchable PDF
→ extracted-text verification
```

Representative OCR timings and counts were:

```text
page 1: 0.82 s / 2 lines / 14 chars
page 2: 6.20 s / 214 lines / 726 chars
page 3: 7.18 s / 273 lines / 845 chars
page 4: 6.73 s / 248 lines / 825 chars
page 5: 5.81 s / 206 lines / 773 chars
```

The merged PDF yielded 14, 720, 845, 824, and 773 extracted characters per page, for **3,176 characters total**.

At this point, a practical minimum architecture existed:

```text
OCR
→ structured intermediate data
→ searchable PDF
→ merge
→ verification
```

## 3. Looking frozen was itself an operational failure

The successful five-page run exposed a usability problem.

Even when model files were already cached, output could remain unchanged for a long period after messages such as:

```text
Creating model: ...
Model files already exist. Using cached files.
```

The user could not tell whether the program had stopped or was still initializing.

PaddleOCR / ONNX Runtime still needed to load models and construct inference sessions on each fresh process. The development timer also originally began after model initialization, so the displayed total did not represent true wall-clock time.

Rather than inventing a fake percentage progress bar, the pipeline added:

- an explicit model-initialization start message;
- elapsed-time messages every 10 seconds;
- an initialization-complete time;
- `flush=True` and unbuffered output;
- model initialization in the total runtime;
- lazy initialization so existing JSON could be reused without loading the OCR model at all.

Typical output became:

```text
[INIT] Initializing PaddleOCR and ONNX Runtime...
[INIT] Still initializing... 10 seconds elapsed
[INIT] Still initializing... 20 seconds elapsed
[OK] PaddleOCR initialization complete: ... seconds
```

This **lazy initialization** later became important for restartability: if every page JSON already existed, PDF rendering or verification could run without loading OCR models.

## 4. From a fixed test to a direct-PDF command

The next step was to move from a fixed five-image test to a user-facing path that accepted a real PDF directly.

The project reused design lessons from another NDL-based OCR code set:

- normalize only oversized PDF pages for OCR safety;
- render PDFs to page images;
- keep stage-specific logs;
- preserve intermediate outputs for restartability;
- separate per-page and merged outputs;
- verify searchable text after PDF generation.

The PaddleOCR pipeline became:

```text
PDF / image / image directory
→ oversized-page normalization
→ page images
→ PaddleOCR
→ per-page JSON / TXT
→ merged TXT / Markdown / JSON / JSONL
→ per-page searchable PDFs
→ merged searchable PDF
→ text-layer verification
→ optional Ghostscript compression
```

Intermediate data was stored under `jobs/<job_name>/` so later stages could be rerun independently.

This phase created the internal pipeline driver `paddleocr_input.sh`.

## 5. A Python executable existing did not mean it was usable

The first direct-PDF run stopped before OCR began.

A project-local `.venv/bin/python` existed, but that environment did not contain PyMuPDF's `fitz`, which the helper stages required.

This demonstrated that:

```text
Python executable exists
```

does not imply:

```text
this Python can run the helper pipeline
```

The user-facing launcher `paddleocr.sh` was therefore introduced. Instead of choosing Python solely by path, it tests whether candidate interpreters can actually import the required modules.

The helper requirements later included approximately:

```text
fitz / PyMuPDF
Pillow
ReportLab
pypdf
fontTools
```

The responsibilities remain:

```text
paddleocr.sh
  → user-facing launcher
  → selects working PaddleOCR/helper Python environments

paddleocr_input.sh
  → internal pipeline driver
  → preprocessing, OCR, aggregation, PDF generation, verification, compression
```

This split originated from a real dependency-selection failure, not merely a naming preference.

## 6. A compressed PDF could exist and still no longer be searchable

The normal searchable PDF worked, but an early 150-dpi compressed PDF lost searchable text.

Compression reconstructed the already-generated searchable PDF through Ghostscript `pdfwrite`, while downsampling images.

The first PaddleOCR PDF renderer used the ReportLab CID font:

```text
HeiseiKakuGo-W5
```

Ghostscript substituted another fallback font during reconstruction, and the compressed PDF no longer yielded the expected text.

This changed the definition of success.

```text
PDF file was created
```

was not sufficient. For a searchable-PDF workflow, success had to mean:

```text
the generated PDF still yields searchable/extractable text
```

## 7. A proven NDL-family path: embed a real TTF

Inspection of an existing NDL-family searchable-PDF renderer showed that it preferred a real font file:

```text
MPLUS1p-Medium.ttf
```

registered through ReportLab `TTFont`.

The PaddleOCR renderer therefore moved away from the CID font and embedded a real TTF. Its invisible-text drawing approach was also aligned with the proven NDL-family path.

Post-compression extracted-text checks were then added so that a compressed PDF that lost too much text would not remain as a successful output.

This is the origin of the current policy: keep the normal searchable PDF, and treat the compressed variant as successful only if it passes validation.

## 8. M PLUS alone did not cover all historical characters

Real material showed that M PLUS 1p lacked some characters needed by the OCR output.

An existing NDL/Yomitoku hybrid implementation had already implemented character-level fallback:

```text
MPLUS1p-Medium.ttf
→ HanaMinA.ttf
→ HanaMinB.ttf
```

Each font's cmap was inspected and the first font containing each character was selected.

The same design was brought into the PaddleOCR renderer.

In one five-page real-document test, **15 unique character types and 30 occurrences** fell back from M PLUS to HanaMinA, including characters such as `圖`, `據`, `癡`, `說`, `辨`, `錄`, `關`, `闡`, `隱`, and `黑`.

That test produced:

```text
HanaMinA: used
HanaMinB: 0
unsupported: 0
```

Both the normal and 150-dpi compressed searchable PDFs yielded **3,194 characters**, retention ratio 1.000.

A separate `tools/report_font_fallbacks.py` utility was then added so exact fallback characters, code points, pages, and counts could be audited without rerunning OCR.

> Historical note: the current public release no longer uses HanaMin as its standard fallback. The present stack is `M PLUS → Jigmo → Jigmo2 → Jigmo3`. This section records the June 2026 development state.

## 9. Compression validation evolved from count checks to content checks

The first compression validator compared extracted character counts.

That still allowed a theoretical failure mode: the count could remain unchanged while some characters changed.

Because Ghostscript also emitted CMap-related warnings at the time, related NDL code sets strengthened validation to:

```text
page-count equality
→ per-page extracted-character counts
→ normalized per-page text comparison
→ exact normalized whole-text match
```

In five-page tests, the normal NDL code set retained 2,842→2,842 characters and the classical NDL code set retained 3,626→3,626, with every page at `similarity=1.000000` and `exact normalized text match: OK`.

Thus, a failure discovered while hardening the PaddleOCR pipeline also improved the safety checks in sibling OCR code sets.

## 10. The experiment repository became an independent pipeline

The project had started as an OCR comparison lab, and its repository and local working-directory names reflected that experimental phase.

By June 21, its actual role had become:

```text
PDF input
→ preprocessing
→ PaddleOCR
→ structured outputs
→ searchable PDF
→ compression
→ post-compression verification
```

The project was therefore renamed:

```text
paddleocr-searchable-pdf-pipeline
```

A preservation tag was created before the rename, and hard-coded references to the old local path were removed from executable code. Comparison code was kept as historical/reproducibility material rather than deleted.

The rename was not a declaration of complete production maturity; it was a correction of the project's identity.

## 11. Renaming broke the virtual environment, revealing another reproducibility problem

Immediately after the local folder rename, `.venv_paddle/bin/python` no longer worked correctly.

Python virtual environments may contain absolute paths from the location where they were created. Moving or renaming the project can therefore break them.

The project responded by preserving **reconstruction information rather than treating the venv itself as the durable artifact**.

```text
requirements-paddle.txt
tools/rebuild_paddle_venv.sh
```

were added, and the then-current environment was rebuilt around:

```text
Python 3.10.4
paddleocr 3.7.0
paddlex 3.7.1
onnxruntime 1.23.2
numpy 2.2.6
```

After rebuilding, the existing five-page JSON was reused and both normal and compressed PDFs again yielded 3,194 characters.

## 12. Raw PaddleOCR JSON made a five-page job grow to gigabytes

A workspace audit exposed another design issue.

Serializing the full PaddleOCR result could include large image arrays and other data unnecessary for later stages. One page could approach 192 MB.

The five-page test reached approximately:

```text
per-page JSON total: about 961.3 MiB
merged JSON:         about 1.2 GB
whole job:           about 2.4 GB
```

The later searchable-PDF stages mainly needed:

```text
text
confidence
bbox
polygon
```

The project therefore introduced `compact-v1` JSON.

Converting the existing five-page result yielded:

```text
per-page JSON total: 961.3 MiB → 129.3 KiB
merged outputs:       about 1.4 GB → 916 KiB
whole job:            2.4 GB → 15 MB
aggregation time:     47.86 s → 0.04 s
```

Searchable-PDF generation, font fallback, and post-compression text retention still worked after compaction.

This was not only storage optimization. It defined what the **durable restart boundary** between OCR and downstream processing should contain.

## 13. Generated data needed documented retention rules

Workspace cleanup removed obsolete experimental outputs, a broken virtual environment, duplicate outputs, and caches.

But `jobs/` was deliberately not treated as disposable cache. Retaining per-page compact JSON allows later improvements to:

- PDF rendering;
- font fallback;
- compression;
- verification;

without rerunning OCR.

Comparison artifacts were archived instead of simply deleted.

The resulting lesson was that:

```text
ignored by Git ≠ unimportant
clean git status ≠ no important local data
```

## 14. Human and ChatGPT forgetting became an explicit design requirement

After cleanup, the user pointed out that the reasons files remained, how they had been generated, and which items were safe to delete would eventually be forgotten—and that a new ChatGPT conversation would also lose context.

The private project therefore added **a durable project-memory document** and **a short new-conversation handoff template**.

The durable project memory recorded items such as:

- the role of major files;
- why ignored local files were retained;
- external dependencies;
- what could or could not be deleted;
- compact-v1 behavior;
- job-name reuse risks;
- known warnings;
- shell-specific failures;
- remaining validation gaps.

The handoff template identified the canonical documents to read first and provided fields for the most recent successful state and unresolved work.

From this point, **recording design rationale that might otherwise be forgotten became part of the development policy itself**.

## 15. A 43-page real document validated the full flow beyond the small test

The pipeline was then exercised on an approximately 43-page real Epson-generated PDF.

The complete flow ran through:

```text
PDF preprocessing
→ page rendering
→ PaddleOCR
→ merged outputs
→ per-page searchable PDFs
→ merged searchable PDF
→ text verification
→ 150-dpi compression
```

Both the normal and compressed PDFs yielded **34,433 characters**, giving retention ratio 1.000.

Approximate file sizes for that material were:

```text
source PDF:                   about 5.2 MB
PaddleOCR searchable PDF:     about 39.9 MB
PaddleOCR 150dpi PDF:         about 18.5 MB
NDL pipeline 150dpi PDF:      about 28.6 MB
```

The project therefore did not optimize solely toward matching the source file size. Searchability, image quality, Unicode retention, and pipeline simplicity remained part of the trade-off.

## 16. A 70-page art catalog showed that zero OCR text can be valid

On a 70-page art-catalog PDF, PaddleOCR completed all pages and produced merged text/JSON outputs.

The searchable-PDF renderer, however, stopped on page 7 because that page contained:

```text
lines = 0
chars = 0
```

For pages dominated by paintings, photographs, or blank areas, zero OCR text can be normal. Dropping such a page would damage the archival document by changing its page count or order.

The renderer was changed to treat the cases separately:

```text
OCR text present
→ original image + invisible Unicode text

no OCR text
→ image-only PDF page
```

A regression test using empty OCR JSON was added so that “no recognized text” would remain a supported case rather than an exception.

## 17. Engineering principles that emerged from these failures

The June 2026 hardening work established several durable principles.

### Success is determined by validating the artifact, not by process exit

```text
OCR finished
≠ success

PDF created
≠ searchable-PDF success

Ghostscript exited
≠ compressed-PDF success
```

Extracted text, page count, and where necessary content preservation are checked.

### OCR and downstream rendering remain separable

Per-page compact JSON forms a restart boundary so PDF, fonts, and compression can evolve without rerunning OCR.

### Long silent stages should explain themselves

Operational usability includes showing what the program is doing during initialization, aggregation, and other long stages.

### The original page remains authoritative

Even zero-text pages are retained. Search text is an added layer, not a replacement for the document image.

### Environments and project memory should be reconstructable

The project avoids depending exclusively on a preserved venv, local generated files, or one conversation history. Requirements, development history, durable memory, and handoff information are part of reproducibility.

## 18. How this work led into the public release

The June hardening work established the core ideas later retained in the public version:

```text
single PDF/image entry point
OCR-safe preprocessing
PaddleOCR / ONNX Runtime
per-page compact JSON
image-preserving searchable PDF
character-level font fallback
post-compression text verification
zero-text page preservation
reproducible setup
```

During September 2026 public-release preparation, font distribution, supplementary-plane CJK support, ReportLab ToUnicode CMaps, and clean setup were validated further, producing the current `M PLUS → Jigmo → Jigmo2 → Jigmo3` design.

The repository is therefore not merely a wrapper around PaddleOCR. Its current architecture is the accumulated result of **turning concrete failures from real document processing into explicit pipeline behavior and validation rules**.

---

For the OCR-engine-selection history, see [OCR Selection History Supplement](OCR_SELECTION_HISTORY_SUPPLEMENT_en.md). For the overall public-facing rationale, see [Development Background and Design Rationale](DEVELOPMENT_BACKGROUND_en.md).
