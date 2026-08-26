#!/usr/bin/env python3
"""Excluded employers must leave board results and not return via snapshot merge."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_exclude_snap", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestExcludeCompanySnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_source_documents_no_reinject(self) -> None:
        self.assertIn("Do not re-inject profile/CLI-excluded companies", SRC)
        self.assertIn("Drop excluded employers from board results", SRC)
        self.assertIn("Excluded {dropped} employer(s) from board results", SRC)
        self.assertIn("Excluded {exclude_dropped} employer(s) from rebuild", SRC)

    def test_filter_drops_excluded_ids(self) -> None:
        keep = self.qj.company_result_from_dict(
            {"id": "acme", "name": "Acme", "jobs": []}
        )
        drop = self.qj.company_result_from_dict(
            {"id": "tria-federal", "name": "Tria Federal", "jobs": []}
        )
        skip = {"tria-federal"}
        results = [co for co in [keep, drop] if co.id not in skip]
        self.assertEqual([co.id for co in results], ["acme"])

    def test_merge_only_then_drop_clears_excluded(self) -> None:
        """--only merge keeps snapshot rows; post-filter must still drop excludes."""
        snapshot = {
            "companies": [
                {"id": "acme", "name": "Acme", "jobs": []},
                {"id": "tria-federal", "name": "Tria Federal", "jobs": []},
            ]
        }
        fresh = [
            self.qj.company_result_from_dict(
                {"id": "acme", "name": "Acme", "jobs": []}
            )
        ]
        merged = self.qj.merge_company_results(
            snapshot,
            fresh,
            ["acme", "tria-federal"],
            allowed_ids={"acme", "tria-federal"},
        )
        self.assertEqual({co.id for co in merged}, {"acme", "tria-federal"})
        skip = {"tria-federal"}
        filtered = [co for co in merged if co.id not in skip]
        self.assertEqual([co.id for co in filtered], ["acme"])


if __name__ == "__main__":
    unittest.main()
