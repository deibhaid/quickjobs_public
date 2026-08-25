#!/usr/bin/env python3
"""Cisco Phenom + Workday share one apply key; cisco-wd consolidates under cisco."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CAREERS = (
    "https://careers.cisco.com/global/en/job/2022910/"
    "Site-Reliability-Engineering-Technical-Leader"
)
WORKDAY = (
    "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/"
    "Irvine-California-US/Site-Reliability-Engineering-Technical-Leader_2022910-1"
)
CANON = "https://careers.cisco.com/global/en/job/2022910"


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_cisco_key", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class CiscoApplyKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = cls.qj.load_config_base()
        cls.by_id = {c["id"]: c for c in cls.cfg["companies"]}

    def test_cisco_dual_rows_configured(self) -> None:
        self.assertEqual(self.by_id["cisco"]["type"], "phenom")
        self.assertEqual(self.by_id["cisco-wd"]["workday_fetch"], "cxs")
        self.assertIn("Cisco_Careers", self.by_id["cisco-wd"]["browse_url"])

    def test_url_variants_share_canonical_key(self) -> None:
        qj = self.qj
        for url in (CAREERS, WORKDAY):
            self.assertEqual(qj.normalize_job_url(url), CANON)
            job = qj.Job(
                company_id="cisco-wd",
                company_name="Cisco (Workday)",
                title="Site Reliability Engineering Technical Leader",
                url=url,
            )
            self.assertEqual(qj.job_apply_key(job), CANON)

    def test_pipeline_migration_merges_variants(self) -> None:
        qj = self.qj
        store = {
            CAREERS: {"status": "applied", "at": "2026-08-24", "updated": "2026-08-24"},
            WORKDAY: {"status": "pass", "at": "2026-08-24", "updated": "2026-08-24"},
        }
        migrated = qj.migrate_cisco_pipeline_keys(store)
        self.assertNotIn(CAREERS, migrated)
        self.assertNotIn(WORKDAY, migrated)
        self.assertIn(CANON, migrated)
        self.assertEqual(migrated[CANON]["status"], "applied")

    def test_consolidate_moves_cisco_wd_under_cisco(self) -> None:
        qj = self.qj
        cisco = qj.CompanyResult(
            id="cisco",
            name="Cisco",
            label="Cisco",
            section="matching",
            jobs=[],
        )
        cisco_wd = qj.CompanyResult(
            id="cisco-wd",
            name="Cisco (Workday)",
            label="Cisco (Workday)",
            section="matching",
            jobs=[
                qj.Job(
                    company_id="cisco-wd",
                    company_name="Cisco (Workday)",
                    title="Site Reliability Engineering Technical Leader",
                    url=WORKDAY,
                    job_id="2022910",
                )
            ],
        )
        moved = qj.consolidate_cisco_family_jobs(
            [cisco, cisco_wd],
            [{"id": "cisco"}, {"id": "cisco-wd"}],
        )
        self.assertEqual(moved, 1)
        self.assertEqual(len(cisco.jobs), 1)
        self.assertEqual(cisco.jobs[0].company_id, "cisco")
        self.assertEqual(cisco_wd.jobs, [])


if __name__ == "__main__":
    unittest.main()
