#!/usr/bin/env python3
"""Legend location filters: inclusive Remote US / Oregon / local + OR union."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("qj_legend_loc_inclusive", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _legend_location_or_match(entry: dict, loc_keys: list[str]) -> bool:
    """Mirror board JS: per-key remote/RFH in-office block; OR unions keys."""

    def work_model_blocks(wm: str) -> bool:
        return wm in {"in-office", "onsite", "on-site"}

    def matches_key(key: str) -> bool:
        wm = str(entry.get("wm") or "")
        if key in {"remote", "remote-from-home"}:
            if entry.get("nus") or entry.get("rfh"):
                pass
            elif work_model_blocks(wm):
                return False
        if key == "remote":
            return bool(entry.get("nus"))
        if key == "remote-from-home":
            return bool(entry.get("rfh"))
        if key == "remote-intl":
            return entry.get("loc") == "remote-intl"
        if key == "local":
            return entry.get("loc") == "local"
        return False

    if not loc_keys:
        return True
    return any(matches_key(k) for k in loc_keys)


class LegendLocationInclusiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()
        cls.cfg = {
            "profile": {
                "home_zip": "00000",
                "local_radius_miles": 50,
                "home_state": "OR",
            }
        }

    def _flags(self, location: str, *, title: str = "Engineer") -> dict:
        mod = self.qj
        loc, label = mod.classify_location_with_fallback(
            location, "us", "", self.cfg, title=title
        )
        job = mod.Job(
            title=title,
            company_id="x",
            url="https://example.com/1",
            loc=loc or "",
            loc_label=label or location,
            meta=location,
        )
        return {
            "loc": loc,
            "wm": "in-office" if loc == "local" else "remote",
            "nus": mod.job_is_nationwide_us_remote(job, self.cfg),
            "rfh": mod.job_is_remote_workable_from_home(job, self.cfg),
            "label": label,
        }

    def test_oregon_remote_suffix_is_remote_from_home_not_remote_us(self) -> None:
        flags = self._flags("Remote - Oregon")
        self.assertEqual(flags["loc"], "remote")
        self.assertFalse(flags["nus"])
        self.assertTrue(flags["rfh"])

    def test_oregon_plus_washington_remote_is_inclusive_rfh(self) -> None:
        flags = self._flags("Remote - Oregon, Washington")
        self.assertEqual(flags["loc"], "remote")
        self.assertFalse(flags["nus"])
        self.assertTrue(flags["rfh"])
        allowed = self.qj.extract_state_limited_remote_allowed_states(
            "Remote - Oregon, Washington"
        )
        self.assertEqual(allowed, frozenset({"OR", "WA"}))

    def test_california_only_remote_still_excluded(self) -> None:
        flags = self._flags("Remote - California")
        self.assertEqual(flags["loc"], "excluded")
        self.assertFalse(flags["nus"])
        self.assertFalse(flags["rfh"])

    def test_local_multi_site_with_portland_is_inclusive(self) -> None:
        for label in (
            "Portland, OR; San Francisco, CA",
            "Portland, OR / Seattle, WA",
            "Hybrid - Portland, OR and San Francisco, CA",
        ):
            with self.subTest(label=label):
                flags = self._flags(label)
                self.assertEqual(flags["loc"], "local", msg=label)
                self.assertFalse(flags["nus"])
                self.assertFalse(flags["rfh"])

    def test_selecting_all_three_is_union(self) -> None:
        """Remote US + Oregon + local → any matching category (OR), not intersection."""
        keys = ["remote", "remote-from-home", "local"]
        us = self._flags("Remote US")
        oregon = self._flags("Remote - Oregon")
        local = self._flags("Portland, OR")
        california = self._flags("Remote - California")
        sf = self._flags("San Francisco, CA")

        self.assertTrue(us["nus"] and not us["rfh"])
        self.assertTrue(oregon["rfh"] and not oregon["nus"])
        self.assertEqual(local["loc"], "local")

        self.assertTrue(_legend_location_or_match(us, keys))
        self.assertTrue(_legend_location_or_match(oregon, keys))
        self.assertTrue(_legend_location_or_match(local, keys))
        self.assertFalse(_legend_location_or_match(california, keys))
        self.assertFalse(_legend_location_or_match(sf, keys))

        # Alone, Remote US must not pull Oregon-only remote.
        self.assertFalse(_legend_location_or_match(oregon, ["remote"]))
        self.assertTrue(_legend_location_or_match(oregon, ["remote-from-home"]))
        # Alone, Oregon must not pull nationwide US remote.
        self.assertFalse(_legend_location_or_match(us, ["remote-from-home"]))
        self.assertTrue(_legend_location_or_match(us, ["remote"]))

    def test_us_remote_is_nus_not_rfh(self) -> None:
        for label in (
            "Remote US",
            "Remote - United States",
            "Remote Nationwide",
            "Canada, United States, Remote",
        ):
            with self.subTest(label=label):
                flags = self._flags(label)
                self.assertTrue(flags["nus"], msg=label)
                self.assertFalse(flags["rfh"], msg=label)

    def test_portland_metro_area_prose_is_local(self) -> None:
        """LinkedIn-style metro labels must count as ≤50 mi local, not excluded."""
        for label in (
            "Portland, Oregon Metropolitan Area",
            "Greater Portland Metropolitan Area",
            "Portland, OR / Seattle, WA",
        ):
            with self.subTest(label=label):
                flags = self._flags(label)
                self.assertEqual(flags["loc"], "local", msg=label)
                self.assertFalse(flags["nus"], msg=label)

    def test_remote_us_is_not_local(self) -> None:
        flags = self._flags("Remote US")
        self.assertEqual(flags["loc"], "remote")
        self.assertNotEqual(flags["loc"], "local")


if __name__ == "__main__":
    unittest.main()
