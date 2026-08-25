#!/usr/bin/env python3
"""Legend location OR must union remote + local (not drop in-office locals)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_legend_or", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _legend_location_or_match(entry: dict, loc_keys: list[str]) -> bool:
    """Mirror fixed board JS: per-key remote/RFH in-office block; OR unions keys."""

    def work_model_blocks(wm: str) -> bool:
        return wm in {"in-office", "onsite", "on-site"}

    def matches_key(key: str) -> bool:
        wm = str(entry.get("wm") or "")
        if key in {"remote", "remote-from-home"} and work_model_blocks(wm):
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


class LegendLocationOrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.src = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")

    def test_board_js_does_not_preblock_location_pass(self) -> None:
        """Aggregate location filters must not call *BlockedFromRemote*(..., locKeys)."""
        for name in (
            "function jobMatchesLegendLocationFilters",
            "function entryMatchesLegendLocationFilters",
        ):
            start = self.src.index(name)
            chunk = self.src[start : start + 450]
            self.assertNotIn(
                "BlockedFromRemoteLegendFilters(",
                chunk,
                msg=f"{name} must not pre-block the whole location pass",
            )
            self.assertIn(".some(key =>", chunk)

    def test_or_remote_plus_local_includes_in_office_local(self) -> None:
        local_office = {
            "loc": "local",
            "wm": "in-office",
            "nus": False,
            "rfh": False,
        }
        remote_us = {"loc": "remote", "wm": "remote", "nus": True, "rfh": False}
        # Bug: remote+local OR used to drop in-office locals.
        self.assertTrue(
            _legend_location_or_match(local_office, ["remote", "local"])
        )
        self.assertTrue(_legend_location_or_match(remote_us, ["remote", "local"]))
        self.assertFalse(_legend_location_or_match(local_office, ["remote"]))
        self.assertTrue(_legend_location_or_match(local_office, ["local"]))


if __name__ == "__main__":
    unittest.main()
