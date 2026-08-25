#!/usr/bin/env python3
"""Text filter chips combine with OR (any) or AND (all)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_text_combine", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def combine_mode_from_select(select_value: str | None, stored: str = "or") -> str:
    """Mirror board JS: dropdown wins when present."""
    if select_value is not None:
        return "and" if select_value == "and" else "or"
    return "and" if stored == "and" else "or"


def combine_mode_from_select_legacy_bug(select_value: str | None, stored: str = "or") -> str:
    """Old JS only read select for 'and', not 'or'."""
    if select_value == "and":
        return "and"
    return "and" if stored == "and" else "or"


def chips_match(title: str, chips: list[dict], combine: str) -> bool:
    """Mirror board JS: Contains chips use combine; Doesn't Contain always AND."""
    entry = {"title": title, "cn": "", "ll": "", "lm": ""}

    def fields_for_chip(chip: dict) -> list[str]:
        out = []
        if chip.get("scopeTitle", True) is not False:
            out.append(entry["title"])
        out.extend([entry["cn"], entry["ll"], entry["lm"]])
        return out

    def chip_matches(chip: dict) -> bool:
        terms = [chip["text"]]
        fields = fields_for_chip(chip)
        if chip.get("mode") == "not":
            return all(
                not any(term.lower() in str(f or "").lower() for term in terms)
                for f in fields
            )
        return any(
            any(term.lower() in str(f or "").lower() for term in terms) for f in fields
        )

    if not chips:
        return True
    include = [c for c in chips if c.get("mode") != "not"]
    exclude = [c for c in chips if c.get("mode") == "not"]
    if include:
        if combine == "and":
            if not all(chip_matches(c) for c in include):
                return False
        elif not any(chip_matches(c) for c in include):
            return False
    if exclude:
        return all(chip_matches(c) for c in exclude)
    return True


class TextFilterCombineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")

    def test_board_js_has_combine_helpers(self) -> None:
        for name in (
            "function textFilterCombineMode",
            "function textFilterChipsMatchEntry",
            "function textFilterChipsByMode",
            "text-filter-combine-mode",
        ):
            self.assertIn(name, self.src)

    def test_or_matches_any_chip(self) -> None:
        chips = [
            {"mode": "contains", "text": "manage", "scopeTitle": True, "scopeDesc": True},
            {"mode": "contains", "text": "principal", "scopeTitle": True, "scopeDesc": False},
        ]
        self.assertTrue(chips_match("Engineering Manager", chips, "or"))
        self.assertTrue(chips_match("Principal Engineer", chips, "or"))
        self.assertFalse(chips_match("Staff Engineer", chips, "or"))

    def test_and_requires_all_chips(self) -> None:
        chips = [
            {"mode": "contains", "text": "manage", "scopeTitle": True, "scopeDesc": False},
            {"mode": "contains", "text": "engineer", "scopeTitle": True, "scopeDesc": False},
        ]
        self.assertTrue(chips_match("Engineering Manager", chips, "and"))
        self.assertTrue(chips_match("Engineering Manager", chips, "or"))
        self.assertFalse(chips_match("Manager", chips, "and"))
        self.assertTrue(chips_match("Manager", chips, "or"))
        self.assertFalse(chips_match("Software Engineer", chips, "and"))

    def test_exclude_always_and_with_or_includes(self) -> None:
        """Doesn't Contain must narrow results, not add listings via OR."""
        chips = [
            {"mode": "contains", "text": "principal", "scopeTitle": True, "scopeDesc": False},
            {"mode": "contains", "text": "senior", "scopeTitle": True, "scopeDesc": False},
            {"mode": "not", "text": "manager", "scopeTitle": True, "scopeDesc": False},
        ]
        self.assertTrue(chips_match("Principal Engineer", chips, "or"))
        self.assertFalse(chips_match("Engineering Manager", chips, "or"))
        # Without include match, exclusion alone must not admit the row.
        self.assertFalse(chips_match("Software Engineer", chips, "or"))
        self.assertTrue(chips_match("Senior Staff Engineer", chips, "or"))

    def test_exclude_only_filters(self) -> None:
        chips = [
            {"mode": "not", "text": "manager", "scopeTitle": True, "scopeDesc": False},
        ]
        self.assertTrue(chips_match("Principal Engineer", chips, "or"))
        self.assertFalse(chips_match("Engineering Manager", chips, "or"))

    def test_combine_mode_reads_or_from_select(self) -> None:
        self.assertEqual(combine_mode_from_select("or", stored="and"), "or")
        self.assertEqual(combine_mode_from_select("and", stored="or"), "and")
        self.assertEqual(combine_mode_from_select_legacy_bug("or", stored="and"), "and")


if __name__ == "__main__":
    unittest.main()
