#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from paddle_json_to_searchable_pdf import make_pdf


class EmptyOcrPageTest(unittest.TestCase):
    def test_empty_ocr_page_becomes_image_only_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "page.png"
            json_path = root / "page.json"
            output_path = root / "page.pdf"

            Image.new("RGB", (320, 240), "white").save(image_path)
            json_path.write_text(
                json.dumps(
                    {
                        "rec_texts": [],
                        "rec_scores": [],
                        "rec_boxes": [],
                        "rec_polys": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            make_pdf(
                image_path=image_path,
                json_path=json_path,
                output_path=output_path,
                debug_visible=False,
                font_paths=[],
            )

            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 0)

            reader = PdfReader(str(output_path))
            self.assertEqual(len(reader.pages), 1)
            self.assertEqual(reader.pages[0].extract_text() or "", "")


if __name__ == "__main__":
    unittest.main()
