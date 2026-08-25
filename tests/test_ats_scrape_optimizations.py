#!/usr/bin/env python3
"""ATS scrape optimizations: sitemal, CXS pagination, Apple window, Oracle/iCIMS/Talentbrew."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("quickjobs_mod_ats_opt", ROOT / "quickjobs.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["quickjobs_mod_ats_opt"] = mod
spec.loader.exec_module(mod)


def _cfg() -> dict:
    return mod.load_config()


SITEMAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
<channel>
<item>
<title>DevOps Engineer (Portland, OR, US)</title>
<description><![CDATA[<p>Kubernetes Terraform CI/CD automation</p>]]></description>
<link>https://jobs.example.com/job/Portland-DevOps-Engineer/12345/</link>
<guid>12345</guid>
<g:location>Portland, OR, US</g:location>
</item>
</channel>
</rss>
"""


def test_successfactors_parse_sitemal() -> None:
    rows = mod.successfactors_parse_sitemal(SITEMAL_XML)
    assert len(rows) == 1
    assert rows[0]["title"].startswith("DevOps Engineer")
    assert rows[0]["job_id"] == "12345"
    assert "Kubernetes" in rows[0]["description_text"]
    assert rows[0]["loc_hint"] == "Portland, OR, US"


def test_fetch_successfactors_uses_sitemal_and_skips_detail_fetch() -> None:
    company = {
        "id": "sf-test",
        "site_origin": "https://jobs.example.com",
        "search_base": "https://jobs.example.com/search",
        "default_loc": "remote",
    }
    cfg = _cfg()
    detail_calls: list[str] = []

    def fake_sitemal(origin: str, **kwargs):
        assert origin == "https://jobs.example.com"
        return mod.successfactors_parse_sitemal(SITEMAL_XML)

    def fake_detail(url: str, **kwargs):
        detail_calls.append(url)
        return "should not be called"

    with patch.object(mod, "successfactors_fetch_sitemal", side_effect=fake_sitemal):
        with patch.object(mod, "successfactors_fetch_detail_text", side_effect=fake_detail):
            with patch.object(mod, "successfactors_fetch_search") as fake_search:
                raw, note = mod.fetch_successfactors(company, cfg)
    fake_search.assert_not_called()
    assert not detail_calls
    assert "sitemal" in note
    assert len(raw) == 1


def test_fetch_successfactors_sitemal_404_falls_back_to_search() -> None:
    company = {
        "id": "sf-fallback",
        "site_origin": "https://jobs.example.com",
        "search_base": "https://jobs.example.com/search",
        "search_keywords": ["devops"],
        "default_loc": "remote",
    }
    cfg = _cfg()
    listing = {
        "title": "Platform Engineer",
        "url": "https://jobs.example.com/job/Platform-Engineer/99/",
        "job_id": "99",
        "loc_hint": "Remote",
    }

    with patch.object(mod, "successfactors_fetch_sitemal", return_value=None):
        with patch.object(mod, "successfactors_fetch_search", return_value=[listing]):
            with patch.object(mod, "successfactors_fetch_detail_text", return_value=""):
                raw, note = mod.fetch_successfactors(company, cfg)
    assert "search" in note
    assert len(raw) == 1


def test_workday_cxs_search_passes_offset() -> None:
    seen: list[int] = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"jobPostings": [{"externalPath": "/job/1"}]}).encode()

    def fake_urlopen(req, timeout=30):
        payload = json.loads(req.data.decode())
        seen.append(int(payload["offset"]))
        return FakeResp()

    with patch.object(mod.urllib.request, "urlopen", side_effect=fake_urlopen):
        mod.workday_cxs_search("vst.wd5", "vst", "site", "devops", limit=20, offset=40)
    assert seen == [40]


def test_fetch_workday_cxs_paginates_until_empty() -> None:
    company = {
        "id": "wd-test",
        "browse_url": "https://vst.wd5.myworkdayjobs.com/en-US/vistra_careers",
        "max_details": 25,
        "search_keywords": ["devops"],
        "skip_search_keywords_extra": True,
    }
    cfg = _cfg()
    pages = {
        0: [
            {"externalPath": f"/job/{i}", "title": f"DevOps Engineer {i}"}
            for i in range(20)
        ],
        20: [
            {"externalPath": "/job/20", "title": "DevOps Engineer 20"},
            {"externalPath": "/job/21", "title": "DevOps Engineer 21"},
        ],
        40: [],
    }
    offsets_seen: list[int] = []

    def fake_search(host, tenant, site, query, *, limit=20, offset=0):
        offsets_seen.append(offset)
        return pages.get(offset, [])

    def fake_detail(host, tenant, site, path):
        return {
            "title": f"Role {path}",
            "url": f"https://example.com{path}",
            "description_text": "desc",
            "location": "Remote",
        }

    with patch.object(mod, "workday_cxs_unavailable_reason", return_value=None):
        with patch.object(mod, "cache_get", return_value=None):
            with patch.object(mod, "cache_set"):
                with patch.object(mod, "workday_cxs_search", side_effect=fake_search):
                    with patch.object(mod, "workday_cxs_fetch_detail", side_effect=fake_detail):
                        with patch.object(
                            mod,
                            "playwright_records_to_raw",
                            side_effect=lambda records, *_a, **_k: [
                                mod.RawPosting(title=r["title"], url=r["url"])
                                for r in records
                            ],
                        ):
                            raw, note = mod.fetch_workday_cxs(company, cfg)
    assert offsets_seen == [0, 20]
    assert len(raw) == 22
    assert "22 details" in note


def test_fetch_workday_cxs_skips_detail_for_nonmatching_list_title() -> None:
    company = {
        "id": "wd-skip-title",
        "browse_url": "https://vst.wd5.myworkdayjobs.com/en-US/vistra_careers",
        "max_details": 10,
        "search_keywords": ["devops"],
        "skip_search_keywords_extra": True,
    }
    cfg = _cfg()
    detail_paths: list[str] = []

    def fake_search(host, tenant, site, query, *, limit=20, offset=0):
        if offset:
            return []
        return [
            {"externalPath": "/job/noise", "title": "Marketing Coordinator"},
            {"externalPath": "/job/hit", "title": "DevOps Engineer"},
        ]

    def fake_detail(host, tenant, site, path):
        detail_paths.append(path)
        return {
            "title": "DevOps Engineer",
            "url": f"https://example.com{path}",
            "description_text": "desc",
            "location": "Remote",
        }

    with patch.object(mod, "workday_cxs_unavailable_reason", return_value=None):
        with patch.object(mod, "cache_get", return_value=None):
            with patch.object(mod, "cache_set"):
                with patch.object(mod, "workday_cxs_search", side_effect=fake_search):
                    with patch.object(mod, "workday_cxs_fetch_detail", side_effect=fake_detail):
                        with patch.object(
                            mod,
                            "playwright_records_to_raw",
                            side_effect=lambda records, *_a, **_k: [
                                mod.RawPosting(title=r["title"], url=r["url"])
                                for r in records
                            ],
                        ):
                            raw, note = mod.fetch_workday_cxs(company, cfg)
    assert detail_paths == ["/job/hit"]
    assert len(raw) == 1
    assert "1 details" in note


def test_fetch_apple_caps_detail_fetches() -> None:
    mod._DETAIL_ROTATION_OUT_PATH = None
    with mod._DETAIL_ROTATION_STORE_LOCK:
        mod._DETAIL_ROTATION_STORES.clear()
        mod._DETAIL_ROTATION_STORES[mod.APPLE_DETAIL_OFFSETS_UI_KEY] = {"apple-test": 0}
    os.environ["QUICKJOBS_APPLE_MAX_DETAILS"] = "1"
    company = {
        "id": "apple-test",
        "search_base": "https://jobs.apple.com/en-us/search",
        "search_keywords": ["devops"],
        "default_loc": "remote",
    }
    cfg = _cfg()
    listings = [
        {"url": "https://jobs.apple.com/en-us/details/1", "title": "DevOps Engineer", "location": "Remote"},
        {"url": "https://jobs.apple.com/en-us/details/2", "title": "Platform Engineer", "location": "Remote"},
    ]
    detail_calls: list[str] = []

    def fake_detail(url: str):
        detail_calls.append(url)
        return {
            "job_id": "1",
            "title": "DevOps Engineer",
            "summary": "k8s",
            "description": "",
            "responsibilities": "",
            "locations": ["Remote"],
            "home_office": "true",
            "posted": "",
            "team": "",
            "posting_footers": "",
        }

    with patch.object(mod, "apple_search_urls", return_value=["https://jobs.apple.com/search"]):
        with patch.object(mod, "http_get", return_value=(200, "", "<html></html>")):
            with patch.object(mod, "apple_parse_search", return_value=listings):
                with patch.object(mod, "apple_fetch_detail", side_effect=fake_detail):
                    raw, note = mod.fetch_apple(company, cfg)
    try:
        assert len(detail_calls) == 1
        assert len(raw) == 2
        assert raw[0].description_text or raw[1].description_text
        assert "list-only" in note
    finally:
        os.environ.pop("QUICKJOBS_APPLE_MAX_DETAILS", None)


def test_oracle_hcm_search_includes_offset() -> None:
    company = {"oracle_site_number": "CX_1"}
    captured: list[str] = []

    def fake_get(url):
        captured.append(url)
        body = json.dumps(
            {
                "items": [
                    {
                        "TotalJobsCount": 30,
                        "requisitionList": [{"Id": "1", "Title": "DevOps Engineer"}],
                    }
                ]
            }
        )
        return 200, url, body

    with patch.object(mod, "http_get", side_effect=fake_get):
        reqs, total = mod.oracle_hcm_search(company, "devops", limit=10, offset=20)
    assert total == 30
    assert len(reqs) == 1
    assert "offset=20" in captured[0]


def test_icims_search_page_url_sets_pr() -> None:
    url = "https://example.icims.com/jobs/search?searchKeyword=devops&in_iframe=1"
    assert mod._icims_search_page_url(url, 2) == (
        "https://example.icims.com/jobs/search?searchKeyword=devops&in_iframe=1&pr=2"
    )


def test_icims_fetch_search_listing_paginated_stops_on_empty_page() -> None:
    pages = {
        0: [{"url": "https://example.icims.com/jobs/1/devops/job", "title": "DevOps"}],
        1: [],
    }

    def fake_listing(search_url, cache_key, **kwargs):
        page = int(cache_key.rsplit("p", 1)[-1])
        return pages.get(page, [])

    with patch.object(mod, "icims_fetch_search_listing", side_effect=fake_listing):
        rows = mod.icims_fetch_search_listing_paginated(
            "https://example.icims.com/jobs/search?searchKeyword=devops",
            "icims-test",
            max_pages=5,
        )
    assert len(rows) == 1


def test_talentbrew_total_pages_and_page_url() -> None:
    html = '<section data-total-pages="4" data-current-page="1"></section>'
    assert mod.talentbrew_total_pages(html) == 4
    assert mod.talentbrew_search_page_url("https://careers.example.com", "devops", 3) == (
        "https://careers.example.com/search-jobs/devops?page=3"
    )


def test_fetch_talentbrew_paginates_search_pages() -> None:
    company = {
        "id": "tb-test",
        "talentbrew_host": "https://careers.example.com",
        "search_keywords": ["devops"],
        "default_loc": "remote",
        "max_details": 0,
    }
    cfg = _cfg()
    bodies = {
        1: '<section data-total-pages="2"><a href="/job/a" data-job-id="1"><h2>DevOps</h2></a></section>',
        2: '<a href="/job/b" data-job-id="2"><h2>Platform</h2></a>',
    }
    fetched_pages: list[int] = []

    def fake_get(url):
        page = 2 if "page=2" in url else 1
        fetched_pages.append(page)
        return 200, url, bodies[page]

    with patch.object(mod, "cache_get", return_value=None):
        with patch.object(mod, "cache_set"):
            with patch.object(mod, "http_get", side_effect=fake_get):
                raw, note = mod.fetch_talentbrew_search(company, cfg)
    assert fetched_pages == [1, 2]
    assert len(raw) == 2
    assert "2 listed" in note


def test_icims_title_from_job_url() -> None:
    url = (
        "https://careers-arch.icims.com/jobs/12345/"
        "principal-devops-engineer/job?in_iframe=1"
    )
    assert mod.icims_title_from_job_url(url) == "principal devops engineer"


def test_icims_parse_search_listing_anchor_title() -> None:
    body = """
    <a href="https://careers-arch.icims.com/jobs/99/senior-platform-engineer/job">
      Senior Platform Engineer
    </a>
    """
    rows = mod.icims_parse_search_listing(body, "https://careers-arch.icims.com/jobs/search")
    assert len(rows) == 1
    assert rows[0]["title"] == "Senior Platform Engineer"
    assert "/senior-platform-engineer/job" in rows[0]["url"]


def test_cap_company_search_queries_defaults_to_four() -> None:
    company = {
        "search_keywords": ["a", "b", "c", "d", "e", "f"],
    }
    cfg = {"title_tiers": {"tier1": ["devops"]}}
    capped = mod.cap_company_search_queries(company, cfg, max_queries_key="oracle_max_queries")
    assert capped == ["a", "b", "c", "d"]


def test_cap_company_search_queries_respects_override() -> None:
    company = {
        "search_keywords": ["a", "b", "c", "d", "e"],
        "phenom_max_queries": 2,
    }
    cfg = {"title_tiers": {"tier1": ["devops"]}}
    capped = mod.cap_company_search_queries(company, cfg, max_queries_key="phenom_max_queries")
    assert capped == ["a", "b"]


def test_fetch_icims_skips_detail_for_title_rejects() -> None:
    company = {
        "id": "test-icims",
        "search_url_template": "https://example.icims.com/jobs/search?searchKeyword={query}",
        "max_details": 5,
    }
    cfg = _cfg()
    listings = [
        {"url": "https://example.icims.com/jobs/1/sales-rep/job", "title": "Sales Representative"},
        {"url": "https://example.icims.com/jobs/2/devops-engineer/job", "title": "DevOps Engineer"},
    ]
    detail_calls: list[str] = []

    def fake_listing(*_args, **_kwargs):
        return listings

    def fake_detail(url: str, **_kwargs):
        detail_calls.append(url)
        return {
            "url": url,
            "title": "DevOps Engineer",
            "location": "US-Remote",
            "description_text": "Kubernetes Terraform CI/CD",
            "job_id": "2",
        }

    with patch.object(mod, "icims_fetch_search_listing", side_effect=fake_listing):
        with patch.object(mod, "icims_fetch_detail", side_effect=fake_detail):
            raw, note = mod.fetch_icims(company, cfg)
    assert len(detail_calls) == 1
    assert "devops-engineer" in detail_calls[0]
    assert "title-filtered pre-detail" in note
    assert len(raw) == 1


def test_fetch_phenom_lazy_job_detail_uses_teaser_before_post() -> None:
    company = {
        "id": "test-phenom",
        "phenom_base": "https://careers.example.com",
        "phenom_refnum": "EXAMPLE",
        "browse_url": "https://careers.example.com",
        "max_details": 5,
        "search_keywords": ["devops"],
    }
    cfg = _cfg()
    jobs = [
        {
            "jobId": "blocked",
            "title": "Staff Engineer",
            "location": "Remote, US",
            "descriptionTeaser": "Machine learning model serving and training pipelines",
        },
        {
            "jobId": "ok",
            "title": "Platform Engineer",
            "location": "Remote, US",
            "descriptionTeaser": "Kubernetes Terraform AWS platform automation",
        },
    ]
    detail_calls: list[str] = []

    def fake_search(_company, _keyword, *, limit=20, offset=0):
        return jobs, len(jobs)

    def fake_detail(_company, job_id: str, **_kwargs):
        detail_calls.append(job_id)
        return {
            "description_text": "Full platform description with salary range $140k - $180k",
            "title": "Platform Engineer",
        }

    with patch.object(mod, "phenom_refine_search", side_effect=fake_search):
        with patch.object(mod, "phenom_fetch_job_detail", side_effect=fake_detail):
            with patch.object(mod, "cache_get", return_value=None):
                with patch.object(mod, "cache_set"):
                    raw, _note = mod.fetch_phenom(company, cfg)
    assert detail_calls == ["ok"]
    assert len(raw) == 1
    assert raw[0].title == "Platform Engineer"


def test_vistra_workday_cxs_target() -> None:
    company = {
        "browse_url": "https://vst.wd5.myworkdayjobs.com/en-US/vistra_careers",
    }
    assert mod.parse_workday_cxs_target(str(company["browse_url"])) == (
        "vst.wd5",
        "vst",
        "vistra_careers",
    )


def test_workday_playwright_search_urls_use_q_param() -> None:
    company = {
        "id": "walmart",
        "type": "playwright",
        "playwright_kind": "workday",
        "browse_url": "https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal",
    }
    urls = mod.playwright_search_urls(company, ["devops", "platform engineer"])
    assert urls == [
        "https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal?q=devops",
        "https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal?q=platform+engineer",
    ]
