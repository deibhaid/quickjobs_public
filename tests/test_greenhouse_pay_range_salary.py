#!/usr/bin/env python3
"""Greenhouse pay-range / locale salary extraction (no hardwired estimates)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_gh_pay", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


PLANET_MULTI_LOCALE = """
Compensation:
The US base salary range for this full-time position at the commencement of employment
is listed below.
California Salary Range $153,000 - $191,300 USD
San Francisco Salary Range $162,600 - $203,200 USD
US National Salary Range $142,800 - $178,500 USD
Canada Salary Range $116,700 - $145,900 CAD
"""

GITLAB_US_RANGE = """
The base salary range for this role's listed level is currently for residents of the
United States only.
United States Salary Range $250,000 - $325,000 USD
How GitLab Supports Full-Time Employees
"""

ROBOTS_TRAILING_PERIOD = (
    "The salary range for this role is $110,000. - $151,000. USD per hour."
)


class GreenhousePayRangeSalaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = {"profile": {"salary_floor": 200000, "home_zip": "00000"}}

    def test_trailing_period_amounts_parse(self) -> None:
        result = self.qj.extract_comp_range_from_text(ROBOTS_TRAILING_PERIOD)
        self.assertEqual(result, ("base", 110000, 151000))

    def test_planet_labs_prefers_us_national_for_or_remote(self) -> None:
        result = self.qj.extract_comp_range_from_text(
            PLANET_MULTI_LOCALE,
            location_name="Remote, United States",
            cfg=self.cfg,
        )
        self.assertEqual(result, ("base", 142800, 178500))

    def test_planet_labs_california_when_location_is_ca(self) -> None:
        result = self.qj.extract_comp_range_from_text(
            PLANET_MULTI_LOCALE,
            location_name="San Francisco, California",
            cfg=self.cfg,
        )
        self.assertEqual(result, ("base", 162600, 203200))

    def test_gitlab_united_states_salary_range(self) -> None:
        salary, label = self.qj.salary_from_detail_text(
            GITLAB_US_RANGE, self.cfg, location_name="United States"
        )
        self.assertEqual(salary, "ok")
        self.assertIn("250", label or "")
        self.assertIn("325", label or "")
        # Posted JD pay — not an estimate provenance suffix.
        self.assertNotRegex(label or "", r"(?i)\best\b")

    def test_locale_bands_skip_cad(self) -> None:
        bands = self.qj.extract_greenhouse_locale_salary_bands(PLANET_MULTI_LOCALE)
        heads = [h.lower() for h, _lo, _hi in bands]
        self.assertTrue(any("national" in h for h in heads))
        self.assertFalse(any("canada" in h for h in heads))


if __name__ == "__main__":
    unittest.main()
