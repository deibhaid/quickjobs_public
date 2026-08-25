#!/usr/bin/env python3
"""Legend match filters use cumulative ceiling (strong ⊂ good ⊂ stretch)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

LEGEND_MATCH_KEYS = frozenset({"strong", "good", "stretch"})
LEGEND_MATCH_CUMULATIVE_RANK = {"strong": 0, "good": 1, "stretch": 2}


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_legend_ceiling", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def legend_match_ceiling_from_pressed(keys: set[str]) -> str | None:
    match_keys = [k for k in keys if k in LEGEND_MATCH_KEYS]
    if not match_keys:
        return None
    if "stretch" in match_keys:
        return "stretch"
    if "good" in match_keys:
        return "good"
    if "strong" in match_keys:
        return "strong"
    return None


def legend_match_keys_for_ceiling(ceiling: str | None) -> list[str]:
    if not ceiling:
        return []
    if ceiling == "stretch":
        return ["strong", "good", "stretch"]
    if ceiling == "good":
        return ["strong", "good"]
    return ["strong"]


def next_legend_match_ceiling_on_click(key: str, ceiling: str | None) -> str | None:
    if not ceiling:
        return key
    if key == ceiling:
        if ceiling == "stretch":
            return "good"
        if ceiling == "good":
            return "strong"
        return None
    return key


def entry_matches_ceiling(entry: dict, ceiling: str | None) -> bool:
    if not ceiling:
        return True
    tier = entry.get("match") or "good"
    tier_rank = LEGEND_MATCH_CUMULATIVE_RANK.get(tier, 1)
    ceiling_rank = LEGEND_MATCH_CUMULATIVE_RANK[ceiling]
    return tier_rank <= ceiling_rank


class LegendMatchCeilingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")

    def test_board_js_has_ceiling_helpers(self) -> None:
        for name in (
            "function legendMatchCeilingFromPressed",
            "function applyLegendMatchCeiling",
            "function nextLegendMatchCeilingOnClick",
            "function jobMatchesLegendMatchCeiling",
        ):
            self.assertIn(name, self.src)

    def test_board_js_has_no_legend_filter_mode_dropdown(self) -> None:
        self.assertNotIn('id="legend-filter-mode"', self.src)
        self.assertNotIn("function legendFilterMode()", self.src)

    def test_match_filters_ignore_legend_filter_mode(self) -> None:
        chunk = self.src[
            self.src.index("function jobMatchesLegendMatchFilters")
            : self.src.index("function jobMatchesLegendLocationFilters")
        ]
        self.assertIn("jobMatchesLegendMatchCeiling", chunk)
        self.assertNotIn("legendFilterMode()", chunk)

    def test_ceiling_button_states(self) -> None:
        self.assertEqual(
            legend_match_keys_for_ceiling("stretch"),
            ["strong", "good", "stretch"],
        )
        self.assertEqual(legend_match_keys_for_ceiling("good"), ["strong", "good"])
        self.assertEqual(legend_match_keys_for_ceiling("strong"), ["strong"])
        self.assertEqual(legend_match_keys_for_ceiling(None), [])

    def test_click_snap_down_and_step_down(self) -> None:
        # Select stretch → all three on
        self.assertEqual(next_legend_match_ceiling_on_click("stretch", None), "stretch")
        # Good while stretch → snap to good (drops stretch)
        self.assertEqual(next_legend_match_ceiling_on_click("good", "stretch"), "good")
        # Strong while good → snap to strong only
        self.assertEqual(next_legend_match_ceiling_on_click("strong", "good"), "strong")
        # Strong while stretch → strong only
        self.assertEqual(next_legend_match_ceiling_on_click("strong", "stretch"), "strong")
        # Click current ceiling steps down one tier
        self.assertEqual(next_legend_match_ceiling_on_click("stretch", "stretch"), "good")
        self.assertEqual(next_legend_match_ceiling_on_click("good", "good"), "strong")
        self.assertEqual(next_legend_match_ceiling_on_click("strong", "strong"), None)

    def test_cumulative_visibility(self) -> None:
        strong = {"match": "strong"}
        good = {"match": "good"}
        stretch = {"match": "stretch"}
        self.assertTrue(entry_matches_ceiling(strong, "strong"))
        self.assertFalse(entry_matches_ceiling(good, "strong"))
        self.assertTrue(entry_matches_ceiling(strong, "good"))
        self.assertTrue(entry_matches_ceiling(good, "good"))
        self.assertFalse(entry_matches_ceiling(stretch, "good"))
        self.assertTrue(entry_matches_ceiling(stretch, "stretch"))

    def test_restore_normalizes_legacy_pressed(self) -> None:
        # Old boards might persist only "good" pressed; ceiling is good → strong+good lit.
        ceiling = legend_match_ceiling_from_pressed({"good"})
        self.assertEqual(ceiling, "good")
        self.assertEqual(legend_match_keys_for_ceiling(ceiling), ["strong", "good"])


if __name__ == "__main__":
    unittest.main()
