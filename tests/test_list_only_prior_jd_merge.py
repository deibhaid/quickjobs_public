#!/usr/bin/env python3
"""List-only scrape restores prior JD text and recomputes match tiers."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("quickjobs_mod_list_only", ROOT / "quickjobs.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["quickjobs_mod_list_only"] = mod
spec.loader.exec_module(mod)


def test_merge_prior_job_descriptions_restores_text_and_key() -> None:
    prior = {
        "companies": [
            {
                "id": "affirm",
                "name": "Affirm",
                "label": "Affirm",
                "section": "company",
                "jobs": [
                    {
                        "title": "Staff Backend Engineer",
                        "company_id": "affirm",
                        "url": "https://boards.greenhouse.io/affirm/jobs/123",
                        "job_id": "123",
                        "match": "good",
                        "loc": "remote",
                        "salary": "ok",
                        "description_text": "kubernetes terraform python ci/cd",
                    }
                ],
            }
        ]
    }
    job = mod.Job(
        title="Staff Backend Engineer",
        company_id="affirm",
        url="https://boards.greenhouse.io/affirm/jobs/123",
        job_id="123",
        match="stretch",
        loc="remote",
        salary="ok",
        description_text="",
    )
    co = mod.CompanyResult(
        id="affirm",
        name="Affirm",
        label="Affirm",
        section="company",
        jobs=[job],
    )
    merged = mod.merge_prior_job_descriptions([co], prior)
    assert merged == 1
    assert "kubernetes" in co.jobs[0].description_text


def test_greenhouse_list_only_scrape_env() -> None:
    import os

    os.environ.pop("QUICKJOBS_GREENHOUSE_FETCH_CONTENT", None)
    os.environ.pop("QUICKJOBS_GREENHOUSE_LIST_ONLY", None)
    assert mod.greenhouse_list_only_scrape() is False
    os.environ["QUICKJOBS_GREENHOUSE_LIST_ONLY"] = "1"
    assert mod.greenhouse_list_only_scrape() is True
    os.environ["QUICKJOBS_GREENHOUSE_FETCH_CONTENT"] = "1"
    assert mod.greenhouse_list_only_scrape() is False


def test_greenhouse_fetch_job_content_enabled_default_on() -> None:
    import os

    os.environ.pop("QUICKJOBS_GREENHOUSE_FETCH_CONTENT", None)
    os.environ.pop("QUICKJOBS_GREENHOUSE_LIST_ONLY", None)
    assert mod._greenhouse_fetch_job_content_enabled(in_watch=False) is True
    os.environ["QUICKJOBS_GREENHOUSE_LIST_ONLY"] = "1"
    assert mod._greenhouse_fetch_job_content_enabled(in_watch=False) is False
    assert mod._greenhouse_fetch_job_content_enabled(in_watch=True) is True
