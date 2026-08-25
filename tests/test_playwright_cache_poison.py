#!/usr/bin/env python3
"""Playwright empty-cache poison + suspicious zero-yield guards."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_pw_cache", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class PlaywrightCachePoisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_refuse_link_but_empty_cache_payload(self) -> None:
        self.assertFalse(
            self.qj._playwright_cache_payload_usable(
                {"link_count": 220, "results": []}
            )
        )
        self.assertTrue(
            self.qj._playwright_cache_payload_usable(
                {"link_count": 2, "results": [{"url": "https://example.com/job/1"}]}
            )
        )
        self.assertTrue(
            self.qj._playwright_cache_payload_usable({"link_count": 0, "results": []})
        )

    def test_suspicious_zero_for_playwright_empty_and_stall(self) -> None:
        Co = self.qj.CompanyResult
        empty_pw = Co(
            id="google",
            name="Google",
            label="Google",
            section="matching",
            jobs=[],
            search_note="Playwright google (34 queries, 0 details, 0 parsed)",
        )
        self.assertTrue(self.qj.company_result_suspicious_zero_yield(empty_pw))
        stall = Co(
            id="cisco",
            name="Cisco",
            label="Cisco",
            section="matching",
            jobs=[],
            search_note="Stall abort after 120s (in-flight drop cap 90s; raise QUICKJOBS_STALL_TIMEOUT_SEC or retry --only)",
        )
        self.assertTrue(self.qj.company_result_suspicious_zero_yield(stall))


class SmartRecruitersConfigRetypeTests(unittest.TestCase):
    def test_visa_docusign_thales_leave_smartrecruiters(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "_shared"))
        import config_bundle  # noqa: E402

        cfg = config_bundle.load_base_bundle(REPO_ROOT / "quickjobs.base.json")
        by = {c["id"]: c for c in cfg["companies"] if isinstance(c, dict) and c.get("id")}
        self.assertEqual(by["visa"]["type"], "playwright")
        self.assertEqual(by["visa"].get("workday_fetch"), "cxs")
        self.assertNotIn("smartrecruiters_id", by["visa"])
        self.assertEqual(by["docusign-inc"]["type"], "icims")
        self.assertNotIn("smartrecruiters_id", by["docusign-inc"])
        self.assertEqual(by["thales-usa"]["type"], "playwright")
        self.assertEqual(by["thales-usa"].get("workday_fetch"), "cxs")


if __name__ == "__main__":
    unittest.main()
