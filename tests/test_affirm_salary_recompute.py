#!/usr/bin/env python3
"""Salary badges recompute from stored Affirm / Greenhouse JD text."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_salary_recompute", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


AFFIRM_JD = (
    "Base pay is part of a total compensation package. "
    "USA base pay range (CA, WA, NY, NJ, CT) per year: 195,000 - 255,000 "
    "USA base pay range (all other U.S. states) per year: 173,000 - 233,000 "
    "#LI-Remote"
)


class AffirmSalaryRecomputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = cls.qj.load_config()
        cls.co = next(c for c in cls.cfg["companies"] if c["id"] == "affirm")

    def test_affirm_extracts_or_band_for_remote_us(self) -> None:
        salary, label = self.qj.affirm_salary_from_detail(
            AFFIRM_JD, self.cfg, location_name="Remote US"
        )
        self.assertIsNotNone(label)
        self.assertIn("173", label or "")
        self.assertIn("233", label or "")
        # Floor is $200K; range straddles → maybe
        self.assertEqual(salary, "maybe")

    def test_recompute_fills_missing_salary_label(self) -> None:
        job = self.qj.Job(
            title="Senior Software Engineer, Backend",
            company_id="affirm",
            url="https://job-boards.greenhouse.io/affirm/jobs/7636414003",
            loc="remote",
            loc_label="Remote US",
            match="good",
            salary="maybe",
            salary_label=None,
            description_text=AFFIRM_JD,
        )
        co = self.qj.CompanyResult(
            id="affirm",
            name="Affirm",
            label="Affirm",
            section="matching",
            jobs=[job],
        )
        n = self.qj.recompute_results_salaries(
            [co], self.cfg, [self.co], only_missing=True
        )
        self.assertEqual(n, 1)
        self.assertTrue(job.salary_label)
        self.assertIn("173", job.salary_label)


if __name__ == "__main__":
    unittest.main()
