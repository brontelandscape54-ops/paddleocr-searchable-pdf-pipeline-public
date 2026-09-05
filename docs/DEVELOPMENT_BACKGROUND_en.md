# Development Background and Design Rationale

[日本語](DEVELOPMENT_BACKGROUND.md) | English

This document explains, for public users, how PaddleOCR Searchable PDF Pipeline grew out of practical OCR work, which alternatives were compared, which failures were encountered, and why the current architecture looks the way it does.

This project does not propose a new OCR model. It packages existing PaddleOCR components into a reproducible workflow for real-world OCR archiving of Japanese historical documents, classical materials, institutional publications, and similarly difficult page layouts.

## 1. Starting point: ordinary text pages worked, table-heavy pages were harder

The project began in practical work to create searchable OCR archives from Japanese documents.

NDL Classical OCR Lite and Yomitoku were useful for many ordinary text pages, but some pages containing bibliographic lists and other tables were harder to process satisfactorily, especially when text placement and page layout mattered.

The problem was not simply whether OCR could recognize any characters at all. For archival use, several requirements need to hold at the same time:

- preserve the visual appearance of tables, rules, figures, and other page elements;
- make text inside tables searchable whenever possible;
- keep old forms, variant characters, and CJK extension characters as Unicode text in the PDF;
- process many pages without manual reconstruction;
- retain searchable text after PDF compression.

This led to comparative experiments with tools including Marker and PaddleOCR.

## 2. Using Marker cell boundaries as a comparison frame

Marker was useful for obtaining table-cell boundaries and TableCell structures.

Those boundaries were therefore used as a comparison frame: OCR bounding boxes from different engines were assigned to the corresponding Marker cells, and the text inside each cell was compared.

This was not intended as a general benchmark proving that one engine is always better than another. It was a practical test on the Japanese table material that motivated this project.

A one-page PaddleOCR test produced:

```text
OCR lines: 214
characters: 726
mean confidence: 0.9741
```

When PaddleOCR character boxes were assigned to Marker cell boundaries, 158 of 182 cells containing text on both sides matched exactly, with an average string similarity of about 96.1%.

For that material, the result was good enough to justify building a production workflow around PaddleOCR.

**Important:** this did not evaluate PaddleOCR's standalone table-structure reconstruction capability. The production pipeline is not primarily designed to reconstruct tables as spreadsheet-style row/column/cell data.

## 3. Preserve the page instead of reconstructing it

For historical-document work, reconstructing a page from OCR output can lose information when recognition or layout analysis is imperfect.

The searchable-PDF design therefore keeps the original page image as the visible layer and places OCR text above it as an invisible Unicode text layer.

This preserves visual elements such as:

- table grids and ruled lines;
- illustrations and figures;
- seals;
- marginal notes;
- unusual line arrangements;
- complex historical-document layouts.

The OCR-recognized text can still be searched and copied.

This is what the repository means when it says that it works well with tables and complex layouts: **it preserves them visually while making recognized text searchable**, rather than promising perfect logical table reconstruction.

## 4. Calling PaddleOCR was only one part of the practical pipeline

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

## 5. Japanese fonts, variant characters, and rare CJK code points

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

## 6. Ghostscript compression and ReportLab ToUnicode CMaps

For archival use, creating a searchable PDF is not enough if compression later damages its text layer.

Early tests exposed Ghostscript CMap warnings, so the pipeline added explicit post-compression text verification.

Later, ReportLab ToUnicode CMap compatibility was improved by:

- splitting `beginbfchar` mappings into blocks of at most 100 entries;
- encoding Unicode destinations above U+FFFF as UTF-16BE surrogate pairs.

The fix is applied at runtime and does not modify installed site-packages.

After this change, a real 10-page document yielded 7,766 extracted characters from the normal searchable PDF and 7,766/7,766 after 150-dpi Ghostscript compression, with retention ratio 1.000. Ghostscript also parsed both versions without the earlier CMap warning.

## 7. Data size and restartability

Saving raw PaddleOCR results directly to JSON can produce very large files because image arrays and other intermediate data may be included.

The project therefore introduced a `compact-v1` JSON format containing only the data needed downstream, such as recognized text, confidence values, bounding boxes, and polygons.

In an early five-page test:

```text
per-page JSON total: 961.3 MiB → 129.3 KiB
whole job:            2.4 GB → 15 MB
aggregation time:     47.86 s → 0.04 s
```

Keeping per-page compact JSON also makes it possible to improve PDF rendering, fonts, or compression without rerunning OCR.

## 8. Preserve pages with zero OCR text

Pages dominated by paintings, photographs, or blank areas can legitimately produce zero OCR text.

An early implementation treated such pages as errors. For archival material, however, dropping the page would be worse than having no searchable text on it.

The current renderer therefore keeps zero-text pages as image-only PDF pages, preserving page count and order.

## 9. Public-release work improved reproducibility

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

## 10. Current scope and limitations

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
- Linux has not yet been fully validated end to end;
- it does not automatically correct OCR recognition errors after recognition.

The pipeline is particularly suited to cases where the **original page appearance should remain authoritative, while as much text as possible—including text inside tables and uncommon CJK characters—should become searchable**.

---

For technical usage, see the [README](../README_en.md).
