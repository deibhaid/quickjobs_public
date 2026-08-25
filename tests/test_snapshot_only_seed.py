#!/usr/bin/env python3
"""First-clone --only must be allowed to seed an empty prior snapshot."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_snapshot_seed", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSnapshotOnlySeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_validate_allows_only_run_when_prior_empty(self) -> None:
        issues = self.qj.validate_run_snapshot_replace(
            {"companies": []},
            [{"id": "remotive", "jobs": []}, {"id": "remoteok", "jobs": []}],
            company_order_count=800,
            only_run=True,
        )
        self.assertEqual(issues, [])

    def test_validate_allows_empty_board_when_no_jobs_expected(self) -> None:
        styles = "\n".join(self.qj._STYLE_NEEDLES)
        html = (
            "<!DOCTYPE html><html><head><style>"
            f"{styles}"
            "</style></head><body>"
            '<div id="pipeline-data"></div>'
            "<script>\n"
            "const pipelineEl = document.getElementById('pipeline-data');\n"
            "</script>\n</body></html>"
        )
        issues = self.qj.validate_html_structure(html, expect_jobs=False)
        job_needles = (
            'Missing required markup/CSS fragment: class="job-main"',
            'Missing required markup/CSS fragment: class="badges"',
            'Missing required markup/CSS fragment: class="job-title"',
            "No job articles found in DOM or lazy-board payloads",
        )
        for needle in job_needles:
            self.assertNotIn(needle, issues)

    def test_validate_requires_jobs_when_expected(self) -> None:
        styles = "\n".join(self.qj._STYLE_NEEDLES)
        html = f"<html><head><style>{styles}</style></head><body></body></html>"
        issues = self.qj.validate_html_structure(html, expect_jobs=True)
        self.assertTrue(
            any("No job articles found" in i or 'class="job-main"' in i for i in issues)
        )

    def test_save_seeds_snapshot_from_only_companies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "job-search-quickjobs.html"
            out.write_text("<html></html>\n", encoding="utf-8")
            self.qj.save_run_snapshot(
                out,
                [{"id": "remotive", "jobs": []}],
                datetime.now(timezone.utc),
                prior={"companies": []},
                company_order_count=800,
                only_run=True,
            )
            loaded = self.qj.load_run_snapshot(out)
            assert loaded is not None
            self.assertEqual(
                [row["id"] for row in loaded["companies"]],
                ["remotive"],
            )


if __name__ == "__main__":
    unittest.main()
