#!/usr/bin/env python3
"""Oracle HCM vanity domains and /job/{id} URL handling."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("quickjobs_david", ROOT / "quickjobs.david.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["quickjobs_david"] = mod
spec.loader.exec_module(mod)


def test_oracle_hcm_ce_base_from_vanity_browse_url() -> None:
    company = {
        "browse_url": "https://jobs.akamai.com/en/sites/CX_1",
        "oracle_api_base": (
            "https://fa-extu-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest"
        ),
        "oracle_site_number": "CX_1",
    }
    assert mod.oracle_hcm_ce_base(company) == "https://jobs.akamai.com/en/sites/CX_1"
    assert (
        mod.oracle_hcm_job_url(company, "3234")
        == "https://jobs.akamai.com/en/sites/CX_1/job/3234"
    )


def test_oracle_hcm_job_url_not_treated_as_landing() -> None:
    company = {
        "id": "akamai",
        "type": "oracle_hcm",
        "browse_url": "https://jobs.akamai.com/en/sites/CX_1",
    }
    url = "https://jobs.akamai.com/en/sites/CX_1/job/3234"
    cloud = (
        "https://fa-extu-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/"
        "CandidateExperience/en/sites/CX_1/job/3234"
    )
    assert mod.is_careers_landing_url(url, company) is False
    assert mod.is_careers_landing_url(cloud, company) is False
    resolved = mod.resolve_job_posting_url(url, company, job_id="3234", title="Senior Software Engineer")
    assert resolved == url
    assert mod.job_url_shape_valid(resolved, company, job_id="3234")


def test_oracle_hcm_browse_hub_still_landing() -> None:
    company = {
        "id": "akamai",
        "type": "oracle_hcm",
        "browse_url": "https://jobs.akamai.com/en/sites/CX_1",
    }
    assert mod.is_careers_landing_url("https://jobs.akamai.com/en/sites/CX_1", company) is True
