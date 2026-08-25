#!/usr/bin/env python3
"""Board-wide search_keywords_extra for Distinguished / lead IC titles."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_search_extra", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class SearchKeywordsExtraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = cls.qj.load_config()
        cls.base = cls.qj.load_config_base()

    def test_extra_keywords_configured(self) -> None:
        extra = self.base.get("search_keywords_extra") or []
        lower = [str(x).lower() for x in extra]
        self.assertIn("distinguished engineer", lower)
        self.assertIn("sr lead software engineer", lower)
        self.assertIn("lead software engineer", lower)

    def test_company_search_queries_prefers_extras(self) -> None:
        co = {"id": "acme", "search_keywords": ["devops", "platform engineer"]}
        queries = self.qj.company_search_queries(co, self.cfg)
        self.assertEqual(queries[0].lower(), "distinguished engineer")
        self.assertIn("devops", queries)
        # Deduped: capitalone already lists distinguished; still one copy at front.
        co2 = next(c for c in self.cfg["companies"] if c["id"] == "capitalone")
        q2 = self.qj.company_search_queries(co2, self.cfg)
        self.assertEqual(q2.count("distinguished engineer"), 1)

    def test_skip_search_keywords_extra(self) -> None:
        co = {
            "id": "acme",
            "search_keywords": ["devops"],
            "skip_search_keywords_extra": True,
        }
        queries = self.qj.company_search_queries(co, self.cfg)
        self.assertEqual(queries, ["devops"])

    def test_workday_detail_budgets_raised(self) -> None:
        low = []
        for c in self.base["companies"]:
            is_wd = (
                c.get("playwright_kind") == "workday"
                or c.get("workday_fetch")
                or "myworkdayjobs.com" in str(c.get("browse_url") or "").lower()
            )
            if not is_wd:
                continue
            if int(c.get("max_details") or 0) < 48:
                low.append(c["id"])
        self.assertEqual(low, [], msg=f"Workday companies still under 48 details: {low}")


if __name__ == "__main__":
    unittest.main()
