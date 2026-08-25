#!/usr/bin/env python3
"""Per-reason and LinkedIn sampling for job-board-filtered.log."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_filter_log", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FilterRejectLogSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def setUp(self) -> None:
        self.qj.clear_filter_rejects()

    def test_per_reason_cap_keeps_late_reasons(self) -> None:
        for i in range(120):
            self.qj.record_filter_reject("early-co", f"Title {i}", None, "title_tier1")
        self.qj.record_filter_reject("linkedin", "Staff SRE", "https://linkedin.com/jobs/view/1", "jd_block")
        entries = self.qj._filter_reject_log_entries()
        reasons = {e["reason"] for e in entries}
        self.assertIn("jd_block", reasons)
        self.assertTrue(any(e["company"] == "linkedin" for e in entries))
        tier1_rows = [e for e in entries if e["reason"] == "title_tier1"]
        self.assertLessEqual(len(tier1_rows), self.qj.FILTER_REJECT_SAMPLE_MAX_PER_REASON)

    def test_linkedin_reserved_even_when_tier1_fills(self) -> None:
        for i in range(200):
            self.qj.record_filter_reject(
                "linkedin",
                f"LinkedIn title {i}",
                f"https://www.linkedin.com/jobs/view/{i}",
                "title_tier2",
            )
        self.qj.record_filter_reject(
            "linkedin",
            "Principal DevOps Engineer",
            "https://www.linkedin.com/jobs/view/principal-devops",
            "jd_block",
            detail="JD blocklist (ml)",
        )
        entries = self.qj._filter_reject_log_entries()
        jd_rows = [
            e
            for e in entries
            if e["reason"] == "jd_block" and "principal-devops" in e["url"]
        ]
        self.assertEqual(len(jd_rows), 1)


if __name__ == "__main__":
    unittest.main()
