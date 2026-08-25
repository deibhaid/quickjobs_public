#!/usr/bin/env python3
"""Tests for geo + US-remote compound location strings (Greenhouse / Pinterest)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("quickjobs_david", ROOT / "quickjobs.david.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["quickjobs_david"] = mod
assert spec.loader is not None
spec.loader.exec_module(mod)


class GeoPlusUsRemoteLocationTests(unittest.TestCase):
    def test_detects_pinterest_style_location(self) -> None:
        loc = "San Francisco, CA, US; Remote, US"
        self.assertTrue(mod.location_is_geo_plus_us_nationwide_remote(loc))
        self.assertTrue(mod.location_has_mixed_remote_and_onsite_us(loc))

    def test_normalize_preserves_mixed_segments(self) -> None:
        loc = "San Francisco, CA, US; Remote, US"
        self.assertEqual(mod.normalize_board_location_name(loc), loc)

    def test_classifies_as_remote_us_after_normalize(self) -> None:
        loc = "San Francisco, CA, US; Remote, US"
        norm = mod.normalize_board_location_name(loc)
        cfg = mod.load_config()
        job_loc, label = mod.classify_location_with_fallback(norm, "us", "", cfg)
        self.assertEqual(job_loc, "remote")
        self.assertIn("Remote, US", label or "")

    def test_sf_only_still_excluded(self) -> None:
        loc = "San Francisco, CA, US"
        cfg = mod.load_config()
        job_loc, _ = mod.classify_location_with_fallback(loc, "us", "", cfg)
        self.assertEqual(job_loc, "excluded")

    def test_remote_us_segment_is_nationwide(self) -> None:
        self.assertTrue(mod.location_has_us_nationwide_remote_segment("Remote, US"))
        self.assertTrue(mod.location_has_us_nationwide_remote_segment("USA, Remote"))
        loc = "San Francisco, CA, US; Remote, US"
        self.assertTrue(mod.location_is_geo_plus_us_nationwide_remote(loc))

    def test_aarhus_denmark_not_split_into_fake_us(self) -> None:
        """City names ending in 'us' must not become US country-code glue."""
        loc = "Aarhus, Denmark; Remote - Denmark"
        self.assertEqual(
            mod._split_glued_us_country_locations(loc),
            loc,
        )
        self.assertEqual(mod.normalize_board_location_name(loc), loc)
        self.assertNotIn("US,", mod.sanitize_loc_label_for_badge(loc).upper().replace("AARHUS", ""))
        cfg = mod.load_config()
        norm = mod.normalize_board_location_name(loc)
        job_loc, label = mod.classify_location_with_fallback(
            norm,
            "us",
            "",
            cfg,
            title="Senior Solutions Engineer",
        )
        self.assertEqual(job_loc, "excluded")
        self.assertTrue(
            label and ("Denmark" in label or "Remote" in label),
            label,
        )

    def test_glued_uppercase_us_country_still_splits(self) -> None:
        glued = "RemoteUS, CA, San Jose"
        self.assertEqual(
            mod._split_glued_us_country_locations(glued),
            "Remote; US, CA, San Jose",
        )

    def test_hillsborough_nh_is_not_portland_hillsboro(self) -> None:
        """Substring 'hillsboro' must not match Hillsborough County, NH."""
        cfg = {"profile": {"home_zip": "00000", "local_radius_miles": 50}}
        self.assertFalse(mod.location_within_local_radius("Hillsborough County, NH", cfg))
        self.assertFalse(mod.portland_metro_marker_in_text("Hillsborough County, NH"))
        self.assertTrue(mod.location_within_local_radius("Hillsboro, OR", cfg))
        self.assertTrue(mod.portland_metro_marker_in_text("Hillsboro, OR"))
        self.assertTrue(mod.location_within_local_radius("Example City, OR", cfg))


if __name__ == "__main__":
    unittest.main()
