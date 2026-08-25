#!/usr/bin/env python3
"""Scrape failure recording: one canonical row per company per run."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

DAVID = Path(__file__).resolve().parents[1] / "quickjobs.david.py"


def load_david():
    spec = importlib.util.spec_from_file_location("quickjobs_david", DAVID)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["quickjobs_david"] = mod
    spec.loader.exec_module(mod)
    return mod


class ScrapeFailureDedupeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_david()

    def setUp(self) -> None:
        self.mod.begin_scrape_failure_run()

    def test_stall_abort_wins_over_orphaned_fetch(self) -> None:
        mod = self.mod
        mod.record_scrape_failure(
            "hawaiian-airlines",
            "orphaned_fetch",
            worker="quickjobs-company-hawaiian-airlines",
            error="daemon still running",
            elapsed_sec=95.0,
        )
        mod.record_scrape_failure(
            "hawaiian-airlines",
            "stall_abort",
            error="idle stall",
            elapsed_sec=125.0,
        )
        rows = mod._dedupe_run_failure_rows(mod._CURRENT_RUN_SCRAPE_FAILURES)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["company_id"], "hawaiian-airlines")
        self.assertEqual(rows[0]["failure_type"], "stall_abort")

    def test_duplicate_stall_abort_not_duplicated(self) -> None:
        mod = self.mod
        mod.record_scrape_failure("atlas-air", "stall_abort", error="first")
        mod.record_scrape_failure("atlas-air", "stall_abort", error="second")
        rows = mod._dedupe_run_failure_rows(mod._CURRENT_RUN_SCRAPE_FAILURES)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["failure_type"], "stall_abort")

    def test_run_block_prefers_canonical_failure(self) -> None:
        mod = self.mod
        mod.record_scrape_failure("avelo-airlines", "orphaned_fetch", error="orphan")
        mod.record_scrape_failure("avelo-airlines", "stall_abort", error="stall")
        failures = mod._dedupe_run_failure_rows(list(mod._CURRENT_RUN_SCRAPE_FAILURES))
        self.assertEqual(
            [(row["company_id"], row["failure_type"]) for row in failures],
            [("avelo-airlines", "stall_abort")],
        )


if __name__ == "__main__":
    unittest.main()
