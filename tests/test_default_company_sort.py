#!/usr/bin/env python3
"""Default listing sort is posting date newest→oldest (Clear resets to same)."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")


class DefaultCompanySortTests(unittest.TestCase):
    def test_html_marks_date_sort_active(self) -> None:
        self.assertIn(
            'class="company-sort-btn active" data-company-sort="date"',
            SRC,
        )
        self.assertNotIn(
            'class="company-sort-btn active" data-company-sort="salary"',
            SRC,
        )

    def test_js_default_and_clear_use_date_desc(self) -> None:
        self.assertIn("let activeCompanySort = 'date';", SRC)
        self.assertIn("let companySortAsc = false;", SRC)
        self.assertIn("activeCompanySort = 'date';", SRC)
        # Clear path must not reintroduce salary as the reset default.
        clear_fn = SRC.split("function resetFilterBarToDefaults()", 1)[1].split(
            "function clearLegendFilters()", 1
        )[0]
        self.assertIn("activeCompanySort = 'date';", clear_fn)
        self.assertNotIn("activeCompanySort = 'salary';", clear_fn)

    def test_rating_sort_hides_employer_browse_links(self) -> None:
        self.assertIn("function syncEmployerBrowseLinks(root)", SRC)
        self.assertIn("activeCompanySort === 'rating'", SRC)
        self.assertIn("is-hidden-for-rating-sort", SRC)
        self.assertIn("Browse all .+ remote roles", SRC)

    def test_stability_hide_controls_are_removed(self) -> None:
        self.assertNotIn(">Stability</h2>", SRC)
        self.assertNotIn("Hide layoff-prone employers", SRC)
        self.assertNotIn("Hide applied / screen / rejected / ghosted", SRC)
        self.assertNotIn('id="hide-layoff-prone"', SRC)
        self.assertNotIn('id="hide-applied"', SRC)


if __name__ == "__main__":
    unittest.main()
