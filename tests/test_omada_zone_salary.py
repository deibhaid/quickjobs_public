#!/usr/bin/env python3
"""Omada Health Zone 1/2/3 salary bands pick profile home state (OR → Zone 2)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

OMADA_ZONE_PAY = """
Below is a summary of salary ranges, by geographic zone, for this role.
Zone 1: $179,400 - $224,300
Zone 2: $171,600 - $214,500
Zone 3: $156,000 - $195,000
Please note that zones may be updated as market data changes.
"""


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_omada_zones", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class OmadaZoneSalaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()
        cls.cfg = cls.qj.load_config()

    def test_oregon_is_zone_2(self) -> None:
        self.assertEqual(self.qj.omada_zone_for_state("OR"), 2)
        self.assertEqual(self.qj.profile_home_us_state(self.cfg), "OR")

    def test_extracts_simple_numeric_zones(self) -> None:
        bands = self.qj.extract_simple_numeric_zone_bands(OMADA_ZONE_PAY)
        self.assertEqual(bands[1], (179400, 224300))
        self.assertEqual(bands[2], (171600, 214500))
        self.assertEqual(bands[3], (156000, 195000))

    def test_oregon_picks_zone_2_band(self) -> None:
        salary, label = self.qj.omada_salary_from_detail(
            OMADA_ZONE_PAY,
            self.cfg,
            location_name="Remote, USA",
        )
        self.assertIn(salary, ("ok", "maybe"))
        self.assertIn("171.6K", label or "")
        self.assertIn("214.5K", label or "")
        self.assertNotIn("156K", label or "")
        self.assertNotIn("224.3K", label or "")

    def test_greenhouse_router_uses_omada_heuristic(self) -> None:
        company = {"id": "omada-health", "board": "omadahealth"}
        salary, label = self.qj.greenhouse_salary_from_detail(
            company,
            "Senior Software Engineer",
            OMADA_ZONE_PAY,
            self.cfg,
            location_name="Remote, USA",
        )
        self.assertIn(salary, ("ok", "maybe"))
        self.assertIn("171.6K", label or "")

    def test_does_not_span_all_zones_via_generic_extractor_alone(self) -> None:
        # Generic path still spans; Omada path must be used for the board badge.
        spanned = self.qj.extract_zone_salary_extents(OMADA_ZONE_PAY)
        self.assertEqual(spanned, (156000, 224300))


if __name__ == "__main__":
    unittest.main()
