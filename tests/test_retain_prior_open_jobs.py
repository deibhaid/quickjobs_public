#!/usr/bin/env python3
"""Prior jobs stay on the board until posting URLs are verified closed."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_retain", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve cls.__module__.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class RetainPriorOpenJobsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def _job(self, *, title: str, url: str, job_id: str = "", match: str = "good"):
        return self.qj.Job(
            title=title,
            company_id="acme",
            url=url,
            job_id=job_id,
            match=match,
            skip_verify=True,
        )

    def _co(self, jobs, *, note: str = ""):
        return self.qj.CompanyResult(
            id="acme",
            name="Acme",
            label="Acme",
            section="matching",
            jobs=list(jobs),
            search_note=note,
        )

    def test_partial_scrape_carries_missing_prior_with_force_verify(self) -> None:
        prior = self._co(
            [
                self._job(
                    title="Platform Engineer",
                    url="https://boards.greenhouse.io/acme/jobs/111",
                    job_id="111",
                ),
                self._job(
                    title="SRE",
                    url="https://boards.greenhouse.io/acme/jobs/222",
                    job_id="222",
                ),
            ]
        )
        fresh = self._co(
            [
                self._job(
                    title="Platform Engineer",
                    url="https://boards.greenhouse.io/acme/jobs/111",
                    job_id="111",
                ),
            ],
            note="Greenhouse API ok",
        )
        merged = self.qj.retain_prior_open_jobs(fresh, prior)
        self.assertEqual(len(merged.jobs), 2)
        by_id = {j.job_id: j for j in merged.jobs}
        self.assertIn("222", by_id)
        self.assertTrue(by_id["222"].force_url_verify)
        self.assertFalse(by_id["222"].skip_verify)
        self.assertFalse(by_id["111"].force_url_verify)
        self.assertIn("retained 1 prior job", merged.search_note)

    def test_dead_board_empty_does_not_resurrect_priors(self) -> None:
        prior = self._co(
            [
                self._job(
                    title="Engineer",
                    url="https://boards.greenhouse.io/acme/jobs/1",
                    job_id="1",
                )
            ]
        )
        fresh = self._co([], note="Greenhouse API returned HTTP 404")
        merged = self.qj.retain_prior_open_jobs(fresh, prior)
        self.assertEqual(merged.jobs, [])

    def test_suspicious_zero_still_preserves_all_priors(self) -> None:
        prior = self._co(
            [
                self._job(
                    title="Engineer",
                    url="https://boards.greenhouse.io/acme/jobs/1",
                    job_id="1",
                )
            ]
        )
        fresh = self._co([], note="Greenhouse API returned HTTP 429")
        merged = self.qj.retain_prior_open_jobs(fresh, prior)
        self.assertEqual(len(merged.jobs), 1)
        self.assertIn("kept 1 prior job", merged.search_note)

    def test_verify_drops_only_closed_carried_jobs(self) -> None:
        mod = self.qj
        open_url = "https://boards.greenhouse.io/acme/jobs/open1"
        closed_url = "https://boards.greenhouse.io/acme/jobs/closed1"
        prior = self._co(
            [
                self._job(title="Open Role", url=open_url, job_id="open1"),
                self._job(title="Closed Role", url=closed_url, job_id="closed1"),
            ]
        )
        fresh = self._co(
            [
                self._job(
                    title="New Role",
                    url="https://boards.greenhouse.io/acme/jobs/new1",
                    job_id="new1",
                )
            ]
        )
        merged = mod.retain_prior_open_jobs(fresh, prior)
        self.assertEqual(len(merged.jobs), 3)

        with tempfile.TemporaryDirectory() as tmp:
            # Unique board stem so we do not touch ~/.job_search/quickjobs/quickjobs/.
            out = Path(tmp) / "job-search-retain-test.html"
            out.write_text("<html></html>", encoding="utf-8")
            side = mod.job_search_data_dir(out)
            removed: list[str] = []
            orig = mod.http_verify_get

            def fake_get(u: str, timeout=None, max_bytes=None):
                if u == closed_url:
                    return (
                        404,
                        closed_url,
                        "<html>Page not found. This job is no longer available.</html>",
                    )
                if u in (open_url, "https://boards.greenhouse.io/acme/jobs/new1"):
                    return (200, u, "<html>Apply now</html>")
                return orig(u, timeout=timeout, max_bytes=max_bytes)

            mod.http_verify_get = fake_get  # type: ignore[method-assign]
            try:
                mod.verify_retained_prior_jobs([merged], removed, out_path=out)
            finally:
                mod.http_verify_get = orig  # type: ignore[method-assign]

            urls = {j.url for j in merged.jobs}
            self.assertIn(open_url, urls)
            self.assertIn("https://boards.greenhouse.io/acme/jobs/new1", urls)
            self.assertNotIn(closed_url, urls)
            self.assertEqual(len(removed), 1)
            self.assertIn(closed_url, removed[0])
            expired = mod.load_expired_job_urls(out)
            self.assertIn(mod.normalize_expired_job_url(closed_url), expired)
            # Cleanup isolated sidecar so repeated local runs stay tidy.
            denylist = mod.expired_job_urls_path(out)
            denylist.unlink(missing_ok=True)
            try:
                side.rmdir()
            except OSError:
                pass

    def test_merge_company_results_uses_retain(self) -> None:
        prior_snap = {
            "companies": [
                {
                    "id": "acme",
                    "name": "Acme",
                    "label": "Acme",
                    "section": "matching",
                    "jobs": [
                        {
                            "title": "Kept Open",
                            "company_id": "acme",
                            "url": "https://boards.greenhouse.io/acme/jobs/9",
                            "job_id": "9",
                            "match": "good",
                        }
                    ],
                }
            ]
        }
        fresh = [
            self._co(
                [
                    self._job(
                        title="Fresh",
                        url="https://boards.greenhouse.io/acme/jobs/1",
                        job_id="1",
                    )
                ]
            )
        ]
        merged = self.qj.merge_company_results(prior_snap, fresh, ["acme"])
        self.assertEqual(len(merged), 1)
        ids = {j.job_id for j in merged[0].jobs}
        self.assertEqual(ids, {"1", "9"})


if __name__ == "__main__":
    unittest.main()
