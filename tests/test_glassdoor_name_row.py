#!/usr/bin/env python3
"""Glassdoor rating · name row alignment when rating is missing."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_gd_name_row", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class GlassdoorNameRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_missing_rating_still_emits_bullet_when_reserved(self) -> None:
        qj = self.qj
        html = qj.format_glassdoor_name_row(
            "EggAI",
            {},
            careers_url="https://example.com/careers",
            reserve_rating_column=True,
        )
        self.assertIn("company-gd-rating-empty", html)
        self.assertIn('company-gd-sep"', html)
        self.assertIn("·", html)
        self.assertIn("EggAI", html)
        # Empty rating column comes before the bullet and name.
        empty_at = html.index("company-gd-rating-empty")
        sep_at = html.index("company-gd-sep")
        name_at = html.index("company-name-text")
        self.assertLess(empty_at, sep_at)
        self.assertLess(sep_at, name_at)

    def test_with_rating_keeps_bullet(self) -> None:
        qj = self.qj
        html = qj.format_glassdoor_name_row(
            "Acme",
            {"glassdoor_rating": "3.8", "glassdoor_url": "https://glassdoor.com/x"},
            reserve_rating_column=True,
        )
        self.assertIn("3.8★", html)
        self.assertIn("company-gd-sep", html)
        self.assertNotIn("company-gd-rating-empty", html)

    def test_company_name_row_css_uses_block_flex_nowrap(self) -> None:
        src = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")
        self.assertIn(".company-name-row {{", src)
        self.assertIn("flex-flow: row nowrap", src)
        self.assertNotIn("display: inline-flex;\n      flex-wrap: wrap;", src)


if __name__ == "__main__":
    unittest.main()
