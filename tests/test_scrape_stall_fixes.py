#!/usr/bin/env python3
"""Stall/orphan timeout and aviation title-tier scrape fixes."""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

DAVID = Path(__file__).resolve().parents[1] / "quickjobs.david.py"


def load_david():
    spec = importlib.util.spec_from_file_location("quickjobs_david", DAVID)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["quickjobs_david"] = mod
    spec.loader.exec_module(mod)
    return mod


class ScrapeStallFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_david()

    def test_company_timeout_same_for_bucketed_and_flat(self) -> None:
        mod = self.mod
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mod._company_timeout_sec(), 600)
            self.assertEqual(mod._company_timeout_sec(bucketed=True), 600)

    def test_company_timeout_env_aliases(self) -> None:
        mod = self.mod
        with mock.patch.dict(os.environ, {"COMPANY_TIMEOUT_SEC": "900"}, clear=True):
            self.assertEqual(mod._company_timeout_sec(bucketed=True), 900)
        with mock.patch.dict(
            os.environ,
            {"QUICKJOBS_COMPANY_TIMEOUT_SEC": "720", "COMPANY_TIMEOUT_SEC": "900"},
            clear=True,
        ):
            self.assertEqual(mod._company_timeout_sec(), 720)

    def test_coerce_positive_int_accepts_numeric_tuple(self) -> None:
        mod = self.mod
        self.assertEqual(mod._coerce_positive_int((30, 120), 60), 120)

    def test_finalize_orphan_skips_under_timeout(self) -> None:
        mod = self.mod
        mod.reset_company_progress(1, scrape_ids={"slow-co"})
        company = {
            "id": "slow-co",
            "name": "Slow",
            "label": "Slow",
            "section": "matching",
        }
        thread = threading.Thread(name="quickjobs-pool-0", target=lambda: None)
        mod._track_worker_company(thread.name, company)
        mod._mark_company_started("slow-co")
        with mock.patch.object(mod, "_company_timeout_sec", return_value=600):
            self.assertFalse(
                mod._finalize_orphaned_worker(
                    thread, {}, bucketed=True, quiet=True
                )
            )

    def test_aviation_pilot_titles_clear_tier2(self) -> None:
        mod = self.mod
        cfg = mod.load_config()
        company = {
            "id": "southwest",
            "sector": "aviation",
            "search_keywords": ["pilot", "first officer", "captain"],
        }
        tier1, tier2, _ = mod.company_title_tiers(company, cfg)
        self.assertIn("pilot", tier1)
        self.assertEqual(tier2, [])
        self.assertIsNone(
            mod.title_filter_fail_reason(
                "Technical Pilot - Flight Test Captain", cfg, company=company
            )
        )
        self.assertIsNone(
            mod.title_filter_fail_reason(
                "Flight Ops Flight Instructor - HDQ", cfg, company=company
            )
        )


if __name__ == "__main__":
    unittest.main()
