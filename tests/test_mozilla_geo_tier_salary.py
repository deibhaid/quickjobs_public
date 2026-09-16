#!/usr/bin/env python3
"""Mozilla US geographic hiring tiers: Portland / OR → Tier 2 (not Tier 1)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MOZILLA_STAFF_OPS_PAY = """
Hiring Ranges:
US Tier 1 Locations $163,000 — $218,000 USD
US Tier 2 Locations $150,000 — $200,000 USD
US Tier 3 Locations $139,000 — $185,000 USD
"""


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_mozilla_tiers", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class MozillaGeoTierSalaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()
        cls.cfg = cls.qj.load_config()

    def test_portland_metro_profile_is_tier_2(self) -> None:
        self.assertEqual(self.qj.profile_home_us_state(self.cfg), "OR")
        self.assertEqual(
            self.qj.mozilla_us_geo_tier_for_profile("Remote US", self.cfg),
            2,
        )
        self.assertEqual(
            self.qj.mozilla_us_geo_tier_for_profile("Portland, OR", self.cfg),
            2,
        )

    def test_tier1_cities(self) -> None:
        for loc in (
            "San Francisco, CA",
            "San Jose, CA",
            "New York City, NY",
            "Remote - NYC",
        ):
            with self.subTest(loc=loc):
                self.assertEqual(
                    self.qj.mozilla_us_geo_tier_for_profile(loc, self.cfg),
                    1,
                )

    def test_extracts_us_tier_bands(self) -> None:
        bands = self.qj.extract_mozilla_us_tier_bands(MOZILLA_STAFF_OPS_PAY)
        self.assertEqual(bands[1], (163000, 218000))
        self.assertEqual(bands[2], (150000, 200000))
        self.assertEqual(bands[3], (139000, 185000))

    def test_oregon_picks_tier_2_not_tier_1(self) -> None:
        salary, label = self.qj.mozilla_salary_from_detail(
            MOZILLA_STAFF_OPS_PAY,
            self.cfg,
            location_name="Remote US",
        )
        self.assertIn(salary, ("ok", "maybe", "low"))
        self.assertIn("150K", label or "")
        self.assertIn("200K", label or "")
        self.assertNotIn("163K", label or "")
        self.assertNotIn("218K", label or "")
        self.assertNotIn("139K", label or "")

    def test_greenhouse_router_uses_mozilla_heuristic(self) -> None:
        company = {"id": "mozilla", "board": "mozilla"}
        salary, label = self.qj.greenhouse_salary_from_detail(
            company,
            "Staff Operations Engineer",
            MOZILLA_STAFF_OPS_PAY,
            self.cfg,
            location_name="Remote US",
        )
        self.assertIn("150K", label or "")
        self.assertIn("200K", label or "")
        self.assertNotIn("163K", label or "")

    def test_company_staff_estimate_is_tier_2(self) -> None:
        co = next(c for c in self.cfg["companies"] if c["id"] == "mozilla")
        label = self.qj.company_salary_label_for_title(co, "Staff Operations Engineer")
        self.assertEqual(label, "$150K–$200K · est.")


if __name__ == "__main__":
    unittest.main()
