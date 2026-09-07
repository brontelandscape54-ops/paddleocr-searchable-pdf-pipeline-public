# Development Background and Design Rationale

[日本語](DEVELOPMENT_BACKGROUND.md) | English

This document explains, for public users, how PaddleOCR Searchable PDF Pipeline grew out of practical OCR work, which alternatives were compared, which failures were encountered, and why the current architecture looks the way it does.

This project does not propose a new OCR model. It packages existing PaddleOCR components into a reproducible workflow for real-world OCR archiving of Japanese historical documents, classical materials, institutional publications, and similarly difficult page layouts.

The timings, character counts, cell counts, and similarity values below were measured on specific development material, hardware, and settings. They are **not** intended as general-purpose OCR benchmarks. The purpose of the experiments was practical: to determine which architecture could reliably support continued OCR archiving of the documents that motivated the project.

## 1. Starting point: ordinary text pages worked, table-heavy pages were harder

The project began in practical work to create searchable OCR archives from Japanese documents.

NDL Classical OCR Lite and Yomitoku were useful for many ordinary text pages, but some pages containing bibliographic lists and other tables were harder to process satisfactorily, especially when text placement and page layout mattered.

The problem was not simply whether OCR could recognize any characters at all. For archival use, several requirements needed to hold at the same time:

- preserve the visual appearance of tables, rules, figures, and other page elements;
- make text inside tables searchable whenever possible;
- keep old forms, variant characters, and CJK extension characters as Unicode text in the PDF;
- process many pages without manual reconstruction;
- retain searchable text after PDF compression;
- remain usable without depending permanently on a paid cloud service.

Azure AI Document Intelligence Layout was tested first on representative material and produced very good table results. However, the free allowance was too limited for sustained large-scale use, so the project shifted toward free or local workflows.

This led to experiments with Marker, PaddleOCR, OCRmyPDF/Tesseract, and comparisons with the already-used NDL Classical OCR Lite and Yomitoku workflows.

## 2. The target output was not Markdown or table reconstruction, but an image-preserving searchable PDF

From an early stage, converting tables into Markdown or CSV was not the primary goal.

The desired artifact was a PDF that kept the source page visually authoritative while making recognized text searchable and copyable.

The basic design therefore became:

```text
original page image
+
invisible Unicode OCR text layer
```

With this approach, imperfect OCR or layout analysis does not redraw or destroy the original visual information. Elements such as the following remain present in the page image:

- table grids and ruled lines;
- illustrations and figures;
- seals;
- marginal notes;
- unusual line arrangements;
- complex layouts specific to historical material.

This requirement was already present during the Marker experiments and was later carried directly into the PaddleOCR production design.

## 3. Early Marker experiments: strong recognition quality, high operational cost

Marker was tested as a local option with strong table handling.

Where Marker recognition succeeded, the OCR quality was judged to be very good. Marker was therefore **not rejected because of poor recognition accuracy**.

The problem was practical cost on the Apple Silicon laptop used for development. Different one-page runs took several minutes and, in some cases, close to ten minutes. Some table-recognition components also fell back from MPS to CPU.

When multi-page PDFs were processed directly, the workflow also encountered MPS backend out-of-memory failures. This made unmodified Marker unsuitable as the everyday engine for larger batches on the test machine.

Marker was not abandoned immediately, because its quality remained attractive. The next phase therefore focused on identifying which parts were expensive and whether the useful parts could be retained.

## 4. A searchable PDF was successfully built from Marker `blocks.json`

Marker was oriented toward structured outputs such as Markdown, JSON, and HTML rather than directly producing the image-preserving searchable PDF required by this project.

Its debug `blocks.json` output was therefore inspected. Text / Line / Span-style blocks contained recognized strings and bounding boxes, which made it possible to build a post-processing renderer in ReportLab.

The process was approximately:

```text
Marker
→ blocks.json
→ extract text + bbox
→ convert top-left coordinates to PDF bottom-left coordinates
→ fit invisible text to each bbox
→ searchable PDF
```

A one-page test placed 213 spans and successfully produced both a normal searchable PDF and a visible-debug PDF for checking alignment. The visual alignment and search layer were good.

This is important historically: Marker was **not** discarded because it could not produce a useful searchable PDF. A working image-preserving searchable-PDF path was demonstrated with Marker output.

## 5. OCRmyPDF / Tesseract was tried as a lighter detour, but recognition was not good enough on the target material

Because multi-page Marker processing was too heavy, OCRmyPDF / Tesseract was also tested as a simpler and lighter searchable-PDF route.

On the Japanese table material being processed at the time, however, recognition quality was judged to be noticeably worse than Marker. The project therefore did not simply replace Marker with a lightweight off-the-shelf searchable-PDF tool. Instead, it returned to the question of whether **the useful parts of Marker could be kept while replacing the expensive text-recognition stage with another OCR engine**.

That detour helped motivate the later architectural separation between layout/table structure and text recognition.

## 6. Page splitting, downscaling, and CPU execution still left text recognition as the bottleneck

To avoid multi-page memory failures, the workflow was changed to render one PDF page at a time, limit image dimensions, use CPU execution, and restrict thread counts.

An OCR-only converter was also tested, but at the time it did not emit the `blocks.json` data required by the searchable-PDF renderer in some runs, so the normal converter still had to be used.

On a representative table page, the Surya text-recognition phase produced the following log:

```text
Recognizing Text: 224/224
elapsed time: about 12 min 20 s
```

This clarified that not every part of Marker was equally expensive. The **text-recognition stage was the main bottleneck**.

### How the development timing records were interpreted

Several development runs, under different settings and processing paths, left the following representative timing records:

| Run | Example development timing | What it indicated at the time |
| --- | ---: | --- |
| Marker normal processing example | about 605 s | some one-page runs were already too heavy for routine use |
| Marker JSON-oriented example | about 458 s | JSON output did not make the workflow lightweight |
| Marker / Surya text recognition | about 12 min 20 s for 224 regions | text recognition was the dominant bottleneck |
| Marker with OCR disabled / TableCell detection | about 4 s for 168 cells | table-structure detection itself was fast |
| PaddleOCR small example | about 3.81 s | promising as a practical lightweight recognizer |

**Important:** this is not a controlled same-input, same-resolution, same-stage speed benchmark. These values come from different development runs and are presented only to explain how the bottleneck was identified and why a different architecture was explored.

The next design therefore separated table structure from text recognition.

## 7. Marker became very fast when used only for table structure

Using Marker TableConverter with OCR disabled, the project tested extracting only table regions, row/column structure, and TableCell bounding boxes.

On one real page, Marker obtained **168 cell coordinates in about four seconds**.

That led to the following hybrid design:

```text
Marker
  → table structure / TableCell bboxes

another OCR engine
  → recognize the whole page once

coordinate assignment
  → assign OCR boxes to Marker cells

original image + invisible text
  → searchable PDF
```

Rather than OCRing 168 cell crops independently, the full page could be recognized once and OCR bounding boxes assigned spatially to the relevant cells. This also made multi-line cells easier to handle.

At this point it was clear that Marker remained useful for structure, even though its own text-recognition stage was too expensive for the intended workflow.

## 8. NDL / Yomitoku / Marker / PaddleOCR were compared on the same table page

To select the text-recognition engine, outputs from five approaches were compared on the same representative table page:

```text
Marker
NDL Classical OCR Lite
Yomitoku-lite
Yomitoku-full
PaddleOCR small
```

The normalized final outputs were first compared by non-whitespace character count, Japanese characters, kanji, kana, Latin letters, digits, and line count.

```text
tool              nonspace   Japanese   kanji   kana   Latin   digits   lines
----------------------------------------------------------------------------
Marker                 754        435     416     19      48      188      44
NDL                    836        407     396     11      31      200     213
Yomitoku-lite          823        423     412     11      29      200      38
Yomitoku-full          813        432     420     12      20      202      38
Paddle-small           717        425     413     12      19      202     214
```

These values were not interpreted as “more characters means better OCR.” Different engines segment lines, cells, punctuation, and mixed alphanumeric text differently. The table was used mainly to reveal differences in output behavior.

## 9. Whole-output string similarity was also measured, but not treated as an accuracy score

Normalized final strings were compared with a string-similarity measure as an additional diagnostic.

```text
Marker vs NDL:           0.176
Marker vs Yomitoku-lite: 0.832
Marker vs Yomitoku-full: 0.851
Marker vs Paddle-small:  0.862
NDL vs Yomitoku-lite:    0.197
NDL vs Yomitoku-full:    0.204
NDL vs Paddle-small:     0.179
Yomitoku-lite vs full:   0.951
Yomitoku-lite vs Paddle: 0.842
Yomitoku-full vs Paddle: 0.859
```

In this diagnostic, PaddleOCR small produced the final string most similar to Marker.

However, this was **not** treated as an OCR-accuracy metric. A whole-string comparison is strongly affected by reading order, line breaks, whether a tool outputs by line or by cell, and how text is concatenated.

Because of those limitations, the project moved to spatial, cell-level comparison.

## 10. A 168-cell comparison table was built with the original cell image beside every OCR output

Marker's 168 detected cells were used as a spatial frame. For each cell, an HTML/CSV comparison view displayed the original image crop alongside text from the OCR engines.

The comparison view included approximately:

```text
original cell image
majority agreement
Marker
Yomitoku-lite
Yomitoku-full
NDL
Paddle-small
```

Cells were color-coded to distinguish full agreement, missing output, and textual disagreement. PaddleOCR entries also included the mean confidence of the OCR regions assigned to that cell.

Majority agreement was **not** treated as ground truth. The original cell image remained the reference, since several OCR engines can make the same mistake.

This image-backed comparison was much more informative than total-character counts or whole-document string similarity because it showed exactly what each engine read from each location.

## 11. The evaluation method itself was refined step by step

The project did not try to rank OCR engines with a single number. The comparison method evolved as the limitations of each earlier method became clear:

```text
character-count / character-type comparison
↓
whole-output string similarity
↓
recognition that reading order and line breaks distort whole-string scores
↓
168 Marker cells + original image crops in an HTML/CSV comparison
↓
spatial assignment of OCR boxes into Marker TableCells
↓
text comparison within corresponding cells
```

A particularly important rule was that **majority agreement among OCR engines was not treated as ground truth**. Multiple engines can make the same mistake, so the original image crop remained visible beside every cell result for human verification.

This made it possible to avoid treating whole-output similarity as “accuracy” and instead examine what happened at each location in the actual source page.

## 12. A 231-TableCell comparison made PaddleOCR's relative separation much clearer

The evaluation was refined again using 21 rows × 11 columns = 231 explicit
Marker TableCells found in a later Marker `blocks.json`.

This was a different stage from the earlier 168-cell comparison.
The 168-cell frame came from a layout-only path with Marker OCR disabled,
whereas the 231 cells were explicit TableCells observed in a different
Marker output with OCR enabled.

In the 231-cell comparison, Marker used each `TableCell.text_lines`,
Yomitoku-lite / full were mapped to the 21×11 Markdown-table structure,
and NDL / PaddleOCR text bboxes were spatially assigned to Marker cells.

A one-page PaddleOCR test had produced:

- 214 OCR regions;
- 726 characters;
- mean confidence 0.9741.

Mean string similarity against Marker in the 231-cell comparison was:

| OCR | Mean string similarity against Marker |
| --- | ---: |
| Yomitoku-lite | 87.1% |
| Yomitoku-full | 87.9% |
| NDL | 77.6% |
| Paddle-small | 96.1% |

Exact-match rates were:

| OCR pair | Exact / both nonempty | Exact rate |
| --- | ---: | ---: |
| Marker × Yomitoku-lite | 121 / 187 | 64.7% |
| Marker × Yomitoku-full | 125 / 187 | 66.8% |
| Marker × NDL | 114 / 184 | 62.0% |
| Marker × Paddle-small | 158 / 182 | 86.8% |

The historically important observation was therefore not merely the absolute
96.1% value. Under the same Marker-cell comparison frame, PaddleOCR exceeded
Yomitoku-full, Yomitoku-lite, and NDL by 8.2, 9.0, and 18.5 percentage points
respectively in mean similarity, and by 20.0, 22.1, and 24.8 percentage points
respectively in exact-match rate.

Marker was not ground truth. Marker itself could be wrong, and majority
agreement among OCR systems was not assumed to be correct. These figures are
therefore not a general OCR-accuracy ranking; they document relative behavior
on one specific Japanese table page under the development configuration.

Spatially assigning NDL / PaddleOCR bboxes into Marker cells also introduced
another possible error surface: neighboring or duplicated text could be placed
into the same comparison cell. Such differences were therefore not treated
automatically as pure recognition errors.

Even with those limitations, this comparison was an important reason to test
whether **PaddleOCR alone could provide practical recognition plus usable
bounding boxes**. Because the final deliverable was an original-image-preserving
searchable PDF rather than a logical reconstruction of the table, the
Marker-TableCell reassignment stage could also be removed from production.

## 13. Why the Marker + PaddleOCR hybrid was not kept as the production architecture

By this stage, a Marker + PaddleOCR hybrid was technically feasible.

Marker had clear strengths:

- strong recognition quality where its OCR succeeded;
- useful TableCell structures;
- fast table-cell detection when OCR was disabled;
- enough positional information in `blocks.json` to build a searchable PDF.

But the hybrid architecture required maintaining several stages:

```text
Marker table structure
+
PaddleOCR recognition
+
coordinate conversion
+
cell assignment
+
PDF rendering
```

The final product requirement, however, was not perfect logical reconstruction of a table into Excel or HTML. It was to **preserve the original page while making table text searchable**.

Once PaddleOCR alone produced sufficiently good text and bounding boxes, the production pipeline no longer needed TableCell structure for every page.

The architecture could therefore be simplified to:

```text
page image
→ PaddleOCR
→ text + bbox
→ invisible Unicode text over the original page
→ searchable PDF
```

Marker was therefore not rejected because its quality was poor. It was left out of the production path because **PaddleOCR alone was sufficient for the final requirement and allowed a simpler, lighter, and easier-to-maintain architecture**.

## 14. Calling PaddleOCR was only one part of the practical pipeline

Character recognition alone was not enough for an archival workflow. The surrounding processing gradually became part of the project.

The current flow is:

```text
PDF / image / image folder
→ OCR-safe handling of oversized PDF pages
→ page images
→ PaddleOCR
→ per-page compact JSON / TXT
→ merged TXT / Markdown / JSON / JSONL
→ searchable PDF generation
→ page merge
→ extracted-text verification
→ optional Ghostscript compression
→ post-compression text-retention verification
```

Per-page JSON is retained so that PDF rendering, font handling, and verification can be improved later without rerunning OCR.

## 15. Japanese fonts, variant characters, and rare CJK code points

A correct OCR string can still be lost from a searchable PDF if the embedded font does not contain the required Unicode code point.

The project therefore moved to character-by-character font selection based on each TTF's cmap.

During public-release preparation, font provenance, redistribution conditions, reproducibility, and supplementary-plane CJK coverage were reviewed again. The current standard fallback stack is:

```text
MPLUS1p-Medium.ttf
→ Jigmo.ttf
→ Jigmo2.ttf
→ Jigmo3.ttf
```

A real 10-page Japanese historical-document OCR result was compared across the previous and Jigmo-based fallback configurations. Both produced:

```text
M PLUS occurrences: 7870
fallback occurrences: 14
fallback unique characters: 9
unsupported characters: 0
```

A real supplementary-plane character, `U+20000`, was also rendered through the production PDF path using Jigmo2 and extracted exactly with pypdf.

## 16. Ghostscript compression and ReportLab ToUnicode CMaps

For archival use, creating a searchable PDF is not enough if compression later damages its text layer.

Early tests exposed Ghostscript CMap warnings, so the pipeline added explicit post-compression text verification.

Later, ReportLab ToUnicode CMap compatibility was improved by:

- splitting `beginbfchar` mappings into blocks of at most 100 entries;
- encoding Unicode destinations above U+FFFF as UTF-16BE surrogate pairs.

The fix is applied at runtime and does not modify installed site-packages.

After this change, a real 10-page document yielded 7,766 extracted characters from the normal searchable PDF and 7,766/7,766 after 150-dpi Ghostscript compression, with retention ratio 1.000. Ghostscript also parsed both versions without the earlier CMap warning.

## 17. Data size and restartability

Saving raw PaddleOCR results directly to JSON can produce very large files because image arrays and other intermediate data may be included.

The project therefore introduced a `compact-v1` JSON format containing only the data needed downstream, such as recognized text, confidence values, bounding boxes, and polygons.

In an early five-page test:

```text
per-page JSON total: 961.3 MiB → 129.3 KiB
whole job:            2.4 GB → 15 MB
aggregation time:     47.86 s → 0.04 s
```

Keeping per-page compact JSON also makes it possible to improve PDF rendering, fonts, or compression without rerunning OCR.

## 18. Preserve pages with zero OCR text

Pages dominated by paintings, photographs, or blank areas can legitimately produce zero OCR text.

An early implementation treated such pages as errors. For archival material, however, dropping the page would be worse than having no searchable text on it.

The current renderer therefore keeps zero-text pages as image-only PDF pages, preserving page count and order.

## 19. Public-release work improved reproducibility

Preparing a public repository was not only a matter of removing private information. It was also used as an opportunity to test whether a third party could reproduce the workflow from a clean checkout.

The public-release work added or formalized:

- one-command setup with `tools/setup.sh`;
- separate PaddleOCR and helper Python environments;
- pinned dependencies;
- M PLUS / Jigmo font retrieval with integrity checks;
- third-party licensing documentation;
- PDF/CMap regression tests;
- a real `U+20000` supplementary-plane PDF validation;
- privacy and static smoke tests for the exported tree;
- an allowlist-based export from the private canonical repository.

A clean exported tree was tested from fresh local environments, successfully completing environment creation, font retrieval, regression tests, supplementary-plane PDF validation, and the static smoke test.

## 20. Current scope and limitations

The value of this repository is not in reinventing PaddleOCR itself. It is in turning practical lessons from Japanese-document OCR work into a reusable workflow covering:

```text
OCR-safe input
→ recognition
→ structured intermediate outputs
→ rare-CJK font fallback
→ original-image-preserving searchable PDF
→ CMap compatibility
→ compression
→ post-compression verification
→ reproducible fresh setup
```

The project also has clear limits:

- it is not a dedicated engine for reconstructing tables as perfect CSV/Excel row-column-cell structures;
- it does not claim that PaddleOCR is superior to all other OCR engines on every Japanese document;
- the comparison values above are development measurements on particular material and settings, not general benchmarks;
- Linux has not yet been fully validated end to end;
- it does not automatically correct OCR recognition errors after recognition.

The pipeline is particularly suited to cases where the **original page appearance should remain authoritative, while as much text as possible—including text inside tables and uncommon CJK characters—should become searchable**.

---

For technical usage, see the [README](../README_en.md).