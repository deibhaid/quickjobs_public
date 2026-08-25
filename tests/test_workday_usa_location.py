#!/usr/bin/env python3
"""Workday long-form US locations (United States of America) classify correctly."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_workday_usa_loc", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestWorkdayUsaLocation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_part_is_country_united_states_of_america(self) -> None:
        self.assertTrue(self.qj._part_is_country_name("United States of America"))
        self.assertTrue(self.qj.country_part_is_us("United States of America"))

    def test_vancouver_washington_usa_is_local_city_state(self) -> None:
        loc = "Vancouver, Washington, United States of America"
        self.assertTrue(self.qj.segment_names_city_state_site(loc))
        self.assertTrue(self.qj.location_names_city_state_site(loc))
        classified = self.qj.classify_city_state_site(loc)
        self.assertIsNotNone(classified)
        kind, _label = classified
        self.assertEqual(kind, "local")
        frag = self.qj.segment_to_city_state_fragment(loc)
        self.assertEqual(frag, "Vancouver, WA")

    def test_short_vancouver_wa_still_local(self) -> None:
        loc = "Vancouver, WA"
        classified = self.qj.classify_city_state_site(loc)
        self.assertIsNotNone(classified)
        self.assertEqual(classified[0], "local")

    def test_usa_comma_state_remote_parses(self) -> None:
        self.assertEqual(
            self.qj.parse_us_country_state_segment("USA, VA, Remote"),
            ("US", "VA", "Remote"),
        )
        self.assertEqual(
            self.qj.parse_us_country_state_segment("USA.MD.Remote"),
            ("US", "MD", "Remote"),
        )
        self.assertEqual(
            self.qj.parse_us_country_state_segment("USA.VA.Reston"),
            ("US", "VA", "Reston"),
        )

    def test_workday_federal_va_md_remote_excluded_for_oregon(self) -> None:
        """Reston/DC offices + VA/MD remote only is not nationwide US remote."""
        loc = (
            "USA.VA.Reston; USA.DC.Home Office Washington DC Metro; "
            "USA, VA, Remote; USA, DC, Home Office; USA, MD, Remote"
        )
        self.assertEqual(
            self.qj.extract_workday_state_locked_remote_states(loc),
            frozenset({"VA", "MD"}),
        )
        self.assertTrue(self.qj.workday_has_state_locked_remote_only(loc))
        self.assertFalse(self.qj.location_is_geo_plus_us_nationwide_remote(loc))
        cfg = self.qj.load_config()
        self.assertEqual(self.qj.profile_home_us_state(cfg), "OR")
        job_loc, label = self.qj.classify_location_with_fallback(
            loc,
            "us",
            "",
            cfg,
            title="Enterprise Architect & Technical Advisor (US Federal)",
        )
        self.assertEqual(job_loc, "excluded")
        self.assertIn("Remote in", label or "")

    def test_home_state_remote_still_matches_profile(self) -> None:
        loc = "USA, OR, Remote; USA.OR.Portland"
        cfg = self.qj.load_config()
        self.assertTrue(self.qj.workday_remote_matches_profile(loc, cfg))
        job_loc, _ = self.qj.classify_location_with_fallback(
            loc, "us", "", cfg, title="Platform Engineer"
        )
        self.assertEqual(job_loc, "remote")

    def test_us_dash_remote_is_nationwide_not_region_locked(self) -> None:
        """Alteryx-style ``US - Remote`` must not match Country - Remote non-US rule."""
        for loc in ("US - Remote", "USA - Remote", "U.S. - Remote"):
            self.assertFalse(
                self.qj.is_region_locked_non_us(loc.lower()),
                msg=loc,
            )
            self.assertTrue(
                self.qj.segment_is_us_country_remote(loc),
                msg=loc,
            )
            self.assertTrue(
                self.qj.location_has_us_nationwide_remote_segment(loc),
                msg=loc,
            )

    def test_us_dash_remote_with_li_remote_tag_stays_remote(self) -> None:
        """``#LI-REMOTE`` must not flip Workday ``US - Remote`` into excluded."""
        cfg = self.qj.load_config()
        for loc in ("US - Remote", "USA - Remote"):
            job_loc, label = self.qj.classify_location_with_fallback(
                loc,
                "",
                "remote",
                cfg,
                title="Principal, Cloud Platform Architect",
                description_text=(
                    "This position is remote-friendly. #LI-EM1 #LI-REMOTE "
                    "Apply at alteryx.com/careers"
                ),
            )
            self.assertEqual(job_loc, "remote", msg=loc)
            self.assertEqual(label, loc)

    def test_poland_dash_remote_still_region_locked(self) -> None:
        self.assertTrue(self.qj.is_region_locked_non_us("poland - remote"))
        cfg = self.qj.load_config()
        job_loc, _ = self.qj.classify_location_with_fallback(
            "Poland - Remote",
            "",
            "remote",
            cfg,
            title="Platform Engineer",
            description_text="#LI-REMOTE",
        )
        self.assertEqual(job_loc, "excluded")


if __name__ == "__main__":
    unittest.main()
