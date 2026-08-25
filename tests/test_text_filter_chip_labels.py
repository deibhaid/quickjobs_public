#!/usr/bin/env python3
"""Text filter chips show scope + mode in the label (Title Contains: …)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_text_filter", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def text_filter_chip_label(chip: dict) -> str:
    title_on = chip.get("scopeTitle", True) is not False
    desc_on = bool(chip.get("scopeDesc"))
    if title_on and desc_on:
        scope_part = "Title/Description"
    elif desc_on:
        scope_part = "Description"
    else:
        scope_part = "Title"
    both = title_on and desc_on
    if chip.get("mode") == "not":
        mode_part = "Don't Contain" if both else "Doesn't Contain"
    else:
        mode_part = "Contain" if both else "Contains"
    return f"{scope_part} {mode_part}: {chip['text']}"


class TextFilterChipLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")

    def test_board_js_has_chip_label_helper(self) -> None:
        self.assertIn("function textFilterChipLabel", self.src)
        self.assertIn("textFilterChipLabel(chip)", self.src)
        self.assertNotIn("Contains: ' + chip.text", self.src)

    def test_label_examples(self) -> None:
        self.assertEqual(
            text_filter_chip_label({"mode": "contains", "text": "principal", "scopeTitle": True, "scopeDesc": False}),
            "Title Contains: principal",
        )
        self.assertEqual(
            text_filter_chip_label({"mode": "not", "text": "principal", "scopeTitle": True, "scopeDesc": False}),
            "Title Doesn't Contain: principal",
        )
        self.assertEqual(
            text_filter_chip_label({"mode": "contains", "text": "principal", "scopeTitle": True, "scopeDesc": True}),
            "Title/Description Contain: principal",
        )
        self.assertEqual(
            text_filter_chip_label({"mode": "not", "text": "principal", "scopeTitle": True, "scopeDesc": True}),
            "Title/Description Don't Contain: principal",
        )


if __name__ == "__main__":
    unittest.main()
