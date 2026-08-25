#!/usr/bin/env python3
"""NEW / Updated / Relisted badges from prior-run novelty flags."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_novelty", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class NoveltyBadgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def _job(self, *, url: str, posted_ts: int) -> object:
        return self.qj.Job(
            company_id="acme",
            company_name="Acme",
            title="SRE",
            url=url,
            loc="remote",
            match="good",
            salary="ok",
            job_id="1",
            posted_ts=posted_ts,
        )

    def test_unseen_url_is_new(self) -> None:
        qj = self.qj
        prev = datetime(2026, 8, 1, tzinfo=timezone.utc)
        job = self._job(url="https://example.com/jobs/new", posted_ts=int(prev.timestamp()) + 100)
        qj.mark_job_novelty_flags(
            job,
            prev_urls={"https://example.com/jobs/old"},
            prev_run_at=prev,
        )
        self.assertTrue(job.is_new)
        self.assertFalse(job.is_updated)

    def test_known_url_with_newer_posted_is_updated(self) -> None:
        qj = self.qj
        prev = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        url = "https://boards.greenhouse.io/acme/jobs/1"
        job = self._job(url=url, posted_ts=int(prev.timestamp()) + 3600)
        qj.mark_job_novelty_flags(job, prev_urls={url}, prev_run_at=prev)
        self.assertFalse(job.is_new)
        self.assertTrue(job.is_updated)

    def test_known_url_unchanged_posted_has_no_badge(self) -> None:
        qj = self.qj
        prev = datetime(2026, 8, 3, tzinfo=timezone.utc)
        url = "https://boards.greenhouse.io/acme/jobs/1"
        job = self._job(url=url, posted_ts=int(prev.timestamp()) - 86400)
        qj.mark_job_novelty_flags(job, prev_urls={url}, prev_run_at=prev)
        self.assertFalse(job.is_new)
        self.assertFalse(job.is_updated)

    def test_linkedin_known_url_with_newer_posted_is_relisted(self) -> None:
        qj = self.qj
        prev = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        url = "https://www.linkedin.com/jobs/view/4422055297/"
        job = self.qj.Job(
            company_id="linkedin",
            company_name="Alteryx",
            title="Principal, Cloud Platform Architect",
            url=url,
            loc="remote",
            match="good",
            salary="ok",
            job_id="4422055297",
            posted_ts=int(prev.timestamp()) + 3600,
        )
        prev_key = qj.job_apply_key(job)
        qj.mark_job_novelty_flags(job, prev_urls={prev_key}, prev_run_at=prev)
        self.assertFalse(job.is_new)
        self.assertTrue(job.is_updated)
        self.assertEqual(qj.job_repost_badge_label(job), "Relisted")
        plain, html = qj.format_job_card_meta_parts(job)
        self.assertTrue(plain.startswith("Relisted "))
        rendered = qj.render_job(job, "local", cfg={"companies": []})
        self.assertIn("badge-relisted", rendered)
        self.assertIn(">Relisted</span>", rendered)
        self.assertIn('data-relisted="true"', rendered)
        self.assertNotIn("badge-updated", rendered)

    def test_linkedin_first_sighting_is_new_not_relisted(self) -> None:
        qj = self.qj
        prev = datetime(2026, 8, 1, tzinfo=timezone.utc)
        url = "https://www.linkedin.com/jobs/view/999/"
        job = self.qj.Job(
            company_id="linkedin",
            company_name="Acme",
            title="SRE",
            url=url,
            loc="remote",
            match="good",
            salary="ok",
            job_id="999",
            posted_ts=int(prev.timestamp()) + 100,
        )
        qj.mark_job_novelty_flags(
            job,
            prev_urls={"https://www.linkedin.com/jobs/view/other/"},
            prev_run_at=prev,
        )
        self.assertTrue(job.is_new)
        self.assertFalse(job.is_updated)
        plain, _ = qj.format_job_card_meta_parts(job)
        self.assertTrue(plain.startswith("Posted "))
        rendered = qj.render_job(job, "local", cfg={"companies": []})
        self.assertIn("badge-new", rendered)
        self.assertNotIn("badge-relisted", rendered)

    def test_render_updated_badge(self) -> None:
        qj = self.qj
        job = self._job(url="https://example.com/j/1", posted_ts=1)
        job.is_updated = True
        html = qj.render_job(job, "local", cfg={"companies": []})
        self.assertIn("badge-updated", html)
        self.assertIn(">Updated</span>", html)
        self.assertNotIn("badge-new", html)
        self.assertNotIn("badge-relisted", html)
        self.assertIn('data-updated="true"', html)

    def test_render_new_badge_not_updated(self) -> None:
        qj = self.qj
        job = self._job(url="https://example.com/j/2", posted_ts=1)
        job.is_new = True
        html = qj.render_job(job, "local", cfg={"companies": []})
        self.assertIn("badge-new", html)
        self.assertIn(">NEW</span>", html)
        self.assertNotIn("badge-updated", html)


if __name__ == "__main__":
    unittest.main()
