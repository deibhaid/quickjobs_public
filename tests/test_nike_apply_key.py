#!/usr/bin/env python3
"""Nike careers + Workday URLs share one apply key and pipeline row."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CAREERS = "https://careers.nike.com/senior-principal-software-engineer/job/R-88271"
WORKDAY = (
    "https://nike.wd1.myworkdayjobs.com/nke/job/"
    "Beaverton-Oregon/Senior-Principal-Software-Engineer_R-88271"
)
WORKDAY_EN = (
    "https://nike.wd1.myworkdayjobs.com/en-US/nke/job/"
    "Beaverton-Oregon/Senior-Principal-Software-Engineer_R-88271"
)
CANON = "https://careers.nike.com/job/R-88271"


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_nike_key", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class NikeApplyKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_url_variants_share_canonical_key(self) -> None:
        qj = self.qj
        for url in (CAREERS, WORKDAY, WORKDAY_EN):
            self.assertEqual(qj.normalize_job_url(url), CANON)
            job = qj.Job(
                company_id="nike-it",
                company_name="Nike (IT)",
                title="Senior Principal Software Engineer",
                url=url,
            )
            self.assertEqual(qj.job_apply_key(job), CANON)

    def test_pipeline_migration_merges_variants(self) -> None:
        qj = self.qj
        store = {
            CAREERS: {"status": "applied", "at": "2026-08-22", "updated": "2026-08-22"},
            WORKDAY: {"status": "pass", "at": "2026-08-23", "updated": "2026-08-23"},
        }
        migrated = qj.migrate_nike_pipeline_keys(store)
        self.assertNotIn(CAREERS, migrated)
        self.assertNotIn(WORKDAY, migrated)
        self.assertIn(CANON, migrated)
        self.assertEqual(migrated[CANON]["status"], "pass")

    def test_consolidate_moves_nike_it_under_nike(self) -> None:
        qj = self.qj
        nike = qj.CompanyResult(
            id="nike",
            name="Nike",
            label="Nike",
            section="local",
            jobs=[],
        )
        nike_it = qj.CompanyResult(
            id="nike-it",
            name="Nike (IT)",
            label="Nike (IT)",
            section="matching",
            jobs=[
                qj.Job(
                    company_id="nike-it",
                    company_name="Nike (IT)",
                    title="Senior Principal Software Engineer",
                    url=WORKDAY,
                )
            ],
        )
        companies = [
            {"id": "nike", "name": "Nike", "section": "local"},
            {"id": "nike-it", "name": "Nike (IT)", "section": "matching"},
        ]
        moved = qj.consolidate_nike_family_jobs([nike, nike_it], companies)
        self.assertEqual(moved, 1)
        self.assertEqual(len(nike_it.jobs), 0)
        self.assertEqual(len(nike.jobs), 1)
        self.assertEqual(nike.jobs[0].company_id, "nike")
        self.assertEqual(qj.job_apply_key(nike.jobs[0]), CANON)

    def test_normalize_run_state_urls_collapses_nike_variants(self) -> None:
        qj = self.qj
        merged = qj.normalize_run_state_urls([CAREERS, WORKDAY, WORKDAY_EN])
        self.assertEqual(merged, [CANON])

    def test_workday_prev_state_does_not_mark_canonical_job_new(self) -> None:
        qj = self.qj
        from datetime import datetime, timezone

        prev = datetime(2026, 8, 24, 2, 0, tzinfo=timezone.utc)
        job = qj.Job(
            company_id="nike",
            company_name="Nike",
            title="Senior Principal Software Engineer",
            url=CAREERS,
            loc="local",
            match="good",
            posted_ts=int(prev.timestamp()) - 86400,
        )
        prev_urls = qj.prev_urls_from_run_state({"urls": [WORKDAY]})
        qj.mark_job_novelty_flags(job, prev_urls=prev_urls, prev_run_at=prev)
        self.assertFalse(job.is_new)
        self.assertFalse(job.is_updated)


if __name__ == "__main__":
    unittest.main()
