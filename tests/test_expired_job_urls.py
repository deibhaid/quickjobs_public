#!/usr/bin/env python3
"""Expired posting URL denylist + soft-404 detection."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_expired", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve cls.__module__.
    import sys

    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestExpiredJobUrls(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_soft404_att_jobs_phrase(self) -> None:
        mod = self.qj
        body = "<html><h1>This job is no longer available.</h1></html>"
        self.assertTrue(
            mod.url_page_indicates_dead_job(
                200,
                "https://www.att.jobs/job/remote/sr-network-engineer/117/96869927648",
                body,
            )
        )

    def test_http_404_is_dead(self) -> None:
        mod = self.qj
        self.assertTrue(mod.url_page_indicates_dead_job(404, "https://www.att.jobs/x", ""))

    def test_denylist_blocks_without_http(self) -> None:
        mod = self.qj
        url = "https://www.att.jobs/job/remote/sr-network-engineer/117/96869927648"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "job-search-quickjobs.html"
            out.write_text("<html></html>", encoding="utf-8")
            side = mod.job_search_data_dir(out)
            side.mkdir(parents=True, exist_ok=True)
            mod.remember_expired_job_urls([url], out)
            removed: list[str] = []
            jobs = [
                mod.Job(
                    title="Sr Network Engineer",
                    company_id="at-t",
                    url=url,
                    skip_verify=True,
                )
            ]
            live = mod.verify_jobs(jobs, removed, out_path=out)
            self.assertEqual(live, [])
            self.assertEqual(len(removed), 1)
            self.assertIn(url, removed[0])

    def test_verify_persists_newly_dead(self) -> None:
        mod = self.qj
        url = "https://example.com/expired-role-xyz"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "job-search-quickjobs.html"
            out.write_text("<html></html>", encoding="utf-8")

            def fake_live(u: str) -> bool:
                return False

            orig = mod.url_is_live
            mod.url_is_live = fake_live  # type: ignore[method-assign]
            try:
                removed: list[str] = []
                jobs = [
                    mod.Job(
                        title="Expired Role",
                        company_id="acme",
                        url=url,
                        skip_verify=False,
                    )
                ]
                live = mod.verify_jobs(jobs, removed, out_path=out)
                self.assertEqual(live, [])
                stored = mod.load_expired_job_urls(out)
                self.assertIn(mod.normalize_expired_job_url(url), stored)
            finally:
                mod.url_is_live = orig  # type: ignore[method-assign]

    def test_linkedin_urls_never_denylisted(self) -> None:
        mod = self.qj
        url = (
            "https://www.linkedin.com/jobs/view/"
            "sr-principal-front-end-design-automation-engineer-at-ampere-4455769253"
        )
        self.assertTrue(mod.posting_url_skip_verify(url))
        self.assertTrue(mod.url_is_linkedin_job_posting(url))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "job-search-quickjobs.html"
            out.write_text("<html></html>", encoding="utf-8")
            before = mod.load_expired_job_urls(out)
            added = mod.remember_expired_job_urls([url], out)
            self.assertEqual(added, 0)
            self.assertNotIn(mod.normalize_expired_job_url(url), mod.load_expired_job_urls(out))
            # Plant a LinkedIn URL in the denylist; verify_jobs must keep the job
            # and purge LinkedIn entries.
            denylist = mod.expired_job_urls_path(out)
            denylist.parent.mkdir(parents=True, exist_ok=True)
            planted = sorted(before | {mod.normalize_expired_job_url(url)})
            denylist.write_text(
                json.dumps({"urls": planted}, indent=2) + "\n",
                encoding="utf-8",
            )
            removed: list[str] = []
            jobs = [
                mod.Job(
                    title="Sr. Principal Front-End Design Automation Engineer",
                    company_id="linkedin",
                    url=url,
                    skip_verify=False,
                )
            ]
            live = mod.verify_jobs(jobs, removed, out_path=out)
            self.assertEqual(len(live), 1)
            self.assertEqual(removed, [])
            after = mod.load_expired_job_urls(out)
            self.assertNotIn(mod.normalize_expired_job_url(url), after)
            # Restore prior denylist entries (shared ~/.job_search sidecar in tests).
            denylist.write_text(
                json.dumps(
                    {
                        "updated_at": "test-restore",
                        "urls": sorted(before),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    def test_talentbrew_companies_no_longer_skip_verify(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "_shared"))
        import config_bundle  # noqa: E402

        data = config_bundle.load_base_bundle(REPO_ROOT / "quickjobs.base.json")
        tb = [c for c in data["companies"] if c.get("type") == "talentbrew"]
        self.assertGreaterEqual(len(tb), 30)
        still_skip = [c["id"] for c in tb if c.get("skip_verify")]
        self.assertEqual(still_skip, [], f"talentbrew still skip_verify: {still_skip}")
        att = next(c for c in tb if c["id"] == "at-t")
        self.assertNotIn("skip_verify", att)

    def test_rebuild_snapshot_documents_verify_urls(self) -> None:
        src = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")
        self.assertIn("--verify-urls", src)
        self.assertIn("ignore_skip=True", src)
        self.assertIn("expired-job-urls.json", src)


if __name__ == "__main__":
    unittest.main()
