# Third-party licenses

This project depends on third-party software and fonts. Those components remain under their own licenses. This file is a practical inventory, not a substitute for the upstream license texts.

## PaddleOCR

- Project: PaddleOCR
- Upstream: PaddlePaddle/PaddleOCR
- License: Apache License 2.0
- Usage here: installed as a Python dependency; the upstream source tree is not bundled in this repository.

## PaddleX

- Project: PaddleX
- Upstream: PaddlePaddle/PaddleX
- License: Apache License 2.0
- Usage here: installed as a Python dependency required by the tested PaddleOCR environment.

## PyMuPDF / MuPDF

- Package used here: PyMuPDF (`pymupdf`)
- Upstream licensing: GNU Affero General Public License (AGPL) and commercial licensing options are offered by Artifex.
- Usage here: installed as a helper dependency for PDF rendering / preprocessing. PyMuPDF or MuPDF source code is not bundled in this repository.

Users, deployers, and redistributors should review the current upstream PyMuPDF/MuPDF license terms for their intended use, especially for redistribution or network/service deployment scenarios.

## Ghostscript

- Program: Ghostscript (`gs`)
- Upstream licensing: GNU Affero General Public License (AGPL) and commercial licensing options are offered by Artifex.
- Usage here: optional external command used only to produce the compressed searchable-PDF variant. Ghostscript is not bundled in this repository.

The main searchable PDF can be produced without Ghostscript; when `gs` is absent, the compression stage is skipped.

## Other Python packages

Packages listed in `requirements-paddle.txt` and `requirements-helper.txt`, including ONNX Runtime, OpenCV, NumPy, Pillow, ReportLab, pypdf, and fontTools, retain their own upstream licenses. Users and redistributors should review those licenses for their intended use.

## Japanese fonts

Font binaries are intentionally not committed to the public repository.

The recommended setup is:

- M PLUS 1p Medium — SIL Open Font License 1.1
- Jigmo / Jigmo2 / Jigmo3 — CC0 1.0

`tools/setup_fonts.sh` can download these fonts into the local ignored `fonts/` directory. The download is an explicit post-clone action; cloning the repository itself does not execute network downloads.

The setup helper uses pinned sources and integrity checks:

- M PLUS 1p Medium is fetched from the Google Fonts repository at fixed commit `5e35378e6bda803962ee6fd257e444a7d459660d`. The expected Git blob IDs for `MPLUS1p-Medium.ttf` and `OFL.txt` are embedded in the setup script and verified after download.
- Jigmo uses the upstream `Jigmo-20250912.zip` release from the author's primary distribution site. The release contains `Jigmo.ttf`, `Jigmo2.ttf`, and `Jigmo3.ttf` and covers Unicode 17.0 CJK Unified Ideographs through Extension J.
- The upstream Jigmo page currently labels the 40-hex value `2fb963ee7bba1d23ccfe81b228422f22da9dc574` as `SHA256`; a SHA-256 digest is 64 hex characters, so the setup helper does not use that value as a SHA-256 integrity check.
- Instead, the setup helper pins the exact upstream archive size (`35,559,738` bytes) and full SHA-256 `5744c7386d129475d87607ca66d043c8793c65448adeaedc921b6931890e5d0b`, independently recorded for the same upstream URL by the Tor Browser build configuration in October 2025.
- Downloaded license text is saved under `fonts/licenses/` when available.

The `fonts/` directory is excluded from Git, so these third-party binaries and downloaded license copies are local setup artifacts rather than files redistributed in this repository's Git history.

The recommended fallback order is intended for character-by-character coverage in the searchable Unicode text layer. If you redistribute font files yourself, include and comply with the corresponding upstream license text.

## Trademark note

PaddleOCR and PaddlePaddle names are used descriptively to identify the upstream OCR software used by this independent project. This repository is not an official PaddlePaddle project and is not endorsed by PaddlePaddle.
