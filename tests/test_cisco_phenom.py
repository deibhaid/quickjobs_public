#!/usr/bin/env python3
"""Cisco careers uses Phenom widgets API (not Playwright jobs.cisco.com)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_cisco_phenom", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class CiscoPhenomConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = cls.qj.load_config_base()
        cls.cisco = next(c for c in cls.cfg["companies"] if c["id"] == "cisco")

    def test_cisco_is_phenom_on_careers_cisco(self) -> None:
        self.assertEqual(self.cisco["type"], "phenom")
        self.assertEqual(self.cisco["phenom_refnum"], "CISCISGLOBAL")
        self.assertIn("careers.cisco.com", self.cisco["phenom_base"])
        self.assertNotEqual(self.cisco.get("playwright_kind"), "cisco")
        self.assertNotIn("jobs.cisco.com", str(self.cisco.get("browse_url") or ""))

    def test_phenom_job_url_for_sre_leader(self) -> None:
        url = self.qj.phenom_job_url(
            self.cisco,
            {
                "jobId": "2022910",
                "title": "Site Reliability Engineering Technical Leader",
                "applyUrl": "",
            },
        )
        self.assertIn("/job/2022910/", url)
        self.assertIn("careers.cisco.com", url)


if __name__ == "__main__":
    unittest.main()
