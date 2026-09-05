#!/usr/bin/env python3
from __future__ import annotations

import re
import unittest

from paddle_json_to_searchable_pdf import (
    REPORTLAB_BFCHAR_BLOCK_LIMIT,
    make_to_unicode_cmap_compliant,
)


class ReportLabCMapChunkingTest(unittest.TestCase):
    def test_large_subset_is_split_into_blocks_of_at_most_100(self) -> None:
        subset = list(range(205))
        cmap = make_to_unicode_cmap_compliant("TestFont", subset)

        counts = [
            int(value)
            for value in re.findall(r"(?m)^(\d+) beginbfchar$", cmap)
        ]

        self.assertEqual(counts, [100, 100, 5])
        self.assertTrue(all(count <= REPORTLAB_BFCHAR_BLOCK_LIMIT for count in counts))
        self.assertEqual(cmap.count("endbfchar"), 3)

    def test_mapping_contents_are_preserved(self) -> None:
        subset = [0x0041, 0x3042, 0x9FA5]
        cmap = make_to_unicode_cmap_compliant("TestFont", subset)

        self.assertIn("<00> <0041>", cmap)
        self.assertIn("<01> <3042>", cmap)
        self.assertIn("<02> <9FA5>", cmap)

    def test_supplementary_plane_mapping_uses_utf16be_surrogate_pair(self) -> None:
        subset = [0x0041, 0x20000]
        cmap = make_to_unicode_cmap_compliant("TestFont", subset)

        self.assertIn("<00> <0041>", cmap)
        self.assertIn("<01> <D840DC00>", cmap)
        self.assertNotIn("<01> <20000>", cmap)

    def test_small_subset_remains_single_block(self) -> None:
        subset = list(range(20))
        cmap = make_to_unicode_cmap_compliant("TestFont", subset)
        self.assertIn("20 beginbfchar", cmap)
        self.assertEqual(cmap.count("beginbfchar"), 1)


if __name__ == "__main__":
    unittest.main()
