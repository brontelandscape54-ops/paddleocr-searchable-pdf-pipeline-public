# OCR Selection History Supplement — Marker / NDL / Yomitoku / PaddleOCR

[日本語](OCR_SELECTION_HISTORY_SUPPLEMENT.md) | English

This document supplements [Development Background and Design Rationale](DEVELOPMENT_BACKGROUND_en.md).

A further review of the preserved 2026-05-31 through 2026-06-21 development chat, terminal logs, comparison scripts, and generated comparison artifacts revealed several important intermediate branches that were still compressed in the public development-background document.

The measurements below come from specific development documents, hardware, and settings. They are not general-purpose OCR benchmarks.

## 1. The central comparison material was mainly horizontal printed tables

During the successful Marker searchable-PDF experiments, the target table material was explicitly described as being basically horizontal printed type.

Accordingly, the Marker / NDL / Yomitoku / PaddleOCR cell counts, character counts, similarity values, and timing records primarily document development on **Japanese bibliographic and table material set in horizontal print**.

Those experiments should not be generalized by themselves to:

- vertical tables;
- handwritten tables;
- cursive historical scripts;
- image-dominated tables;
- highly irregular multi-column table layouts.

The current pipeline can accept a wider range of source material, but the historical evidence behind the Marker/PaddleOCR selection was centered on horizontal printed table pages.

## 2. The project did not jump directly from Marker to PaddleOCR; NDLOCR-Lite briefly became the preferred recognition engine

Once it was discovered that Marker could extract table structure and cell coordinates quickly with OCR disabled, the design shifted toward using Marker only for structure and delegating recognition to another OCR engine.

At that point, PaddleOCR was not immediately chosen as the primary recognizer.

Based on prior experience with the actual documents, NDLOCR-Lite was believed to provide the best recognition quality. On 2026-06-20, the preferred architecture briefly became:

```text
Marker
  → table regions / rows / columns / cell coordinates

NDLOCR-Lite
  → full-page text recognition

coordinate integration
  → assign NDL text regions to Marker cells

Yomitoku-style renderer
  → reuse the more carefully developed invisible-text placement approach

searchable PDF
```

This design continued work from April 2026, where another hybrid searchable-PDF experiment had combined:

```text
NDLOCR text
+
Yomitoku's finer geometry / PDF placement approach
```

In that earlier work, NDLOCR was treated as strong in recognition but relatively coarse in bounding-box granularity, while Yomitoku offered finer positioning data and a more sophisticated searchable-PDF renderer. That experience directly influenced the June design principle of separating recognition, structure, and PDF rendering into distinct components.

For this reason, the historical sequence should not be simplified to:

```text
Marker → PaddleOCR
```

A more accurate sequence is:

```text
Marker alone
→ split Marker into structure analysis and text recognition
→ consider Marker + NDLOCR-Lite + Yomitoku-style placement
→ compare NDL / Yomitoku / Marker / PaddleOCR on the same material
→ confirm that PaddleOCR alone provides sufficient text + bboxes
→ simplify production around PaddleOCR
```

## 3. PaddleOCR initially entered as a lightweight alternative, not as the assumed accuracy winner

When NDLOCR-Lite was being considered as the main recognizer, PaddleOCR was still mainly a **lightweight Japanese OCR candidate** that could potentially replace Marker/Surya text recognition while providing bounding boxes.

A five-way comparison was then performed. On the representative page, PaddleOCR small produced 214 OCR regions in about 3.81 seconds and had a whole-output string similarity of 0.862 against Marker.

However, the whole-output similarity value was not treated as OCR accuracy, and the evaluation proceeded to image-backed cell comparison.

PaddleOCR became the production center not because the project proved that it was generally more accurate than NDLOCR-Lite, but because one OCR stage could provide the combination required by the final workflow:

```text
practical recognition quality
+
sufficiently fine bounding boxes
+
fast local execution
+
intermediate data directly usable by the image-preserving searchable-PDF renderer
```

That allowed the production pipeline to avoid permanently combining Marker, NDLOCR-Lite, and Yomitoku.

## 4. Re-examining Marker TableCell output produced a 231-cell comparison frame in addition to the earlier 168-cell frame

The earlier layout-only experiment obtained 168 Marker cell coordinates in about four seconds and used those 168 cells as the first image-backed spatial comparison frame.

Later, a different Marker `blocks.json` produced by the normal converter with OCR enabled was inspected more closely. Its structure included:

```text
block_type 27 (TableCell): 231
block_type 1  (Line):        2
block_type 22 (Table):       1
```

The 231 cells matched the table's explicit structure:

```text
21 rows × 11 columns = 231 cells
```

At this stage, it was also discovered that the Marker output format had changed relative to the earlier Span-based assumptions. Reading only the old `text` field produced no usable text; recognized TableCell content was stored in `text_lines`.

A TableCell-aware searchable-PDF rendering test reported, in one run:

```text
TableCell:   212 text items
characters: 815
```

The resulting Marker recognition was again judged to be very good.

Therefore, it is incomplete to summarize the Marker comparison history only through the 168-cell experiment.

## 5. The 168-cell and 231-cell counts are not contradictory

The two counts came from different development stages and output modes.

- **168 cells** — obtained in a layout-only path with Marker OCR disabled. These were used to demonstrate fast structure detection and to build the first spatial comparison view.
- **231 cells** — explicit TableCell objects found later in a different Marker `blocks.json` generated with OCR enabled, corresponding to a 21×11 table structure.

Because the processing mode and Marker output representation differed, these values document different experiments rather than two competing counts of the same output.

Recording this distinction avoids the misleading impression that the project simply changed its claimed number of table cells.

## 6. The 231-TableCell comparison exposed a clear relative separation for PaddleOCR

A later script, `compare_ocr_cells_marker231.py`, used the 231 explicit Marker
TableCells as the comparison frame.

Marker used each `TableCell.text_lines` from `blocks.json`;
Yomitoku-lite / full were mapped from their Markdown table output to the 21×11
structure; and NDL / PaddleOCR text bboxes were spatially assigned to the
Marker TableCells.

The generated comparison artifacts were
`ocr_cell_comparison_marker231.csv`,
`ocr_cell_comparison_marker231.html`, and
`ocr_cell_comparison_marker231_assets/`.

The HTML view displayed original cell crops, Marker, Yomitoku-lite/full, NDL,
PaddleOCR, similarity against Marker, PaddleOCR confidence, and
agreement/disagreement status.

The Marker summary in this comparison HTML was 231 explicit TableCells,
191 nonempty Marker cells, 40 empty cells, and 727 non-whitespace characters.

This is a different measurement from another TableCell-aware processing run
that reported 212 text items and 815 characters.
The historical `212 text items` value must therefore not be rewritten as
“212 text-bearing TableCells.”

### The historically important point was PaddleOCR's relative separation

Mean string similarity against Marker was 87.1% for Yomitoku-lite,
87.9% for Yomitoku-full, 77.6% for NDL, and 96.1% for Paddle-small.

Exact-match rates were 64.7% for Marker × Yomitoku-lite,
66.8% for Marker × Yomitoku-full, 62.0% for Marker × NDL,
and 86.8% for Marker × Paddle-small.

The important historical observation was therefore not merely the absolute
96.1% value.

Under the same Marker-cell comparison frame, PaddleOCR exceeded
Yomitoku-full, Yomitoku-lite, and NDL by 8.2, 9.0, and 18.5 percentage points
respectively in mean similarity, and by 20.0, 22.1, and 24.8 percentage points
respectively in exact-match rate.

Marker was not ground truth, so these values cannot be treated as a universal
OCR-accuracy ranking. However, the conspicuous relative closeness of PaddleOCR
within the shared comparison frame was an important reason it was reclassified
from merely a lightweight alternative recognizer to a candidate worth testing
as the sole OCR engine.

The 231-cell view also contained cases consistent with spatial-assignment
effects, such as neighboring or duplicated text being assigned to one Marker
cell. Such differences should not automatically be classified as recognition
errors.

That distinction also supports the later architecture: because the final
deliverable was an original-image-preserving searchable PDF rather than a
logical reconstruction of the table, PaddleOCR text + bboxes could be used
directly without forcing them through a Marker TableCell layer.

The evaluation itself therefore progressed from whole-output character counts,
to whole-output string similarity, to the image-backed 168-cell comparison,
and finally to comparison using 231 explicit Marker TableCells.

## 7. Historical conclusion

Including these additional findings, the path to the PaddleOCR-centered production architecture is best summarized as:

```text
NDL / Yomitoku difficulties on table-heavy material
→ Azure Document Intelligence gives excellent results but sustained paid use is impractical
→ Marker is tested and its recognition quality is very good
→ image-preserving searchable PDF is successfully built from Marker output
→ Marker text recognition is too heavy for practical multi-page use; MPS OOM also occurs
→ OCRmyPDF / Tesseract is lighter but less accurate on the target material
→ Marker is decomposed into structure analysis and text recognition
→ layout-only Marker is fast
→ Marker + NDLOCR-Lite + Yomitoku-style placement is considered first
→ PaddleOCR is added as a lightweight recognition candidate
→ evaluation is refined through character counts, whole-output similarity, 168-cell comparison, and 231-TableCell comparison
→ PaddleOCR alone is judged sufficient for practical text + bbox output
→ because the deliverable is an image-preserving searchable PDF rather than logical table reconstruction, production is simplified around PaddleOCR
```

The final selection was therefore not a simple OCR-accuracy ranking.

It combined recognition quality, processing cost, bounding-box granularity, ease of connecting OCR output to the searchable-PDF renderer, dependency complexity, maintainability, and the final archival requirement that the original page image remain authoritative.
