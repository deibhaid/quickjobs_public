#!/usr/bin/env python3
"""LinkedIn guest Jobs scraper (job_sites aggregator)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]

SAMPLE_CARD_HTML = """
<ul>
<li>
<div class="base-search-card" data-entity-urn="urn:li:jobPosting:4422055297">
  <a href="https://www.linkedin.com/jobs/view/4422055297/">
    <h3 class="base-search-card__title">Principal Platform Engineer</h3>
  </a>
  <h4 class="base-search-card__subtitle">Acme Cloud</h4>
  <span class="job-search-card__location">Portland, Oregon, United States</span>
  <time datetime="2026-08-11">1 week ago</time>
</div>
</li>
<li>
<div class="base-search-card" data-entity-urn="urn:li:jobPosting:999">
  <a href="https://www.linkedin.com/jobs/view/999/">
    <h3 class="base-search-card__title">Staff SRE</h3>
  </a>
  <h4 class="base-search-card__subtitle">Remote Co</h4>
  <span class="job-search-card__location">Remote - United States</span>
  <time datetime="2026-08-18">2 days ago</time>
</div>
</li>
</ul>
"""


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_linkedin", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class LinkedInJobsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_sb2_maps_salary_floor(self) -> None:
        qj = self.qj
        code, floor = qj.linkedin_min_salary_to_sb2(192_000)
        self.assertEqual(code, "8")
        self.assertEqual(floor, 180_000)
        code2, floor2 = qj.linkedin_min_salary_to_sb2(200_000)
        self.assertEqual(code2, "9")
        self.assertEqual(floor2, 200_000)
        self.assertEqual(qj.linkedin_min_salary_to_sb2(0), (None, None))

    def test_parse_listings(self) -> None:
        qj = self.qj
        listings = qj.linkedin_parse_listings(SAMPLE_CARD_HTML)
        self.assertEqual(len(listings), 2)
        self.assertEqual(listings[0]["job_id"], "4422055297")
        self.assertEqual(listings[0]["title"], "Principal Platform Engineer")
        self.assertEqual(listings[0]["company"], "Acme Cloud")
        self.assertIn("Portland", listings[0]["location"])
        self.assertEqual(listings[1]["title"], "Staff SRE")

    def test_parse_salary_from_text(self) -> None:
        qj = self.qj
        parsed = qj.linkedin_parse_salary_from_text(
            "Base salary range: $180,000 to $240,000 per year."
        )
        assert parsed is not None
        self.assertEqual(parsed["annual_min"], 180_000)
        self.assertEqual(parsed["annual_max"], 240_000)

    def test_parse_salary_shared_k_suffix(self) -> None:
        qj = self.qj
        parsed = qj.linkedin_parse_salary_from_text(
            "Benefits Salary range: $120-140k, based upon experience Equity options"
        )
        assert parsed is not None
        self.assertEqual(parsed["annual_min"], 120_000)
        self.assertEqual(parsed["annual_max"], 140_000)

    def test_parse_salary_scribd_geo_bands_prefer_non_ca(self) -> None:
        qj = self.qj
        text = (
            "San Francisco is our highest geographic market in the United States. "
            "In the state of California, the reasonably expected salary range is between "
            "$176,500 [minimum salary in our lowest geographic market within California] "
            "to $275,000 [maximum salary in our highest geographic market within California]. "
            "In the United States, outside of California, the reasonably expected salary range "
            "is between $145,000 [minimum salary in our lowest US geographic market outside of "
            "California] to $261,500 [maximum salary in our highest US geographic market "
            "outside of California]. "
            "In Canada, the reasonably expected salary range is between $184,500 CAD to $244,500 CAD."
        )
        parsed = qj.linkedin_parse_salary_from_text(text, location_name="Portland, OR")
        assert parsed is not None
        self.assertEqual(parsed["annual_min"], 145_000)
        self.assertEqual(parsed["annual_max"], 261_500)
        ca = qj.linkedin_parse_salary_from_text(text, location_name="San Francisco, CA")
        assert ca is not None
        self.assertEqual(ca["annual_min"], 176_500)
        self.assertEqual(ca["annual_max"], 275_000)

    def test_listing_to_raw_uses_salary_floor(self) -> None:
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000}}
        raw = qj.linkedin_listing_to_raw(
            {
                "job_id": "1",
                "title": "Platform Engineer",
                "company": "Acme",
                "location": "Remote, United States",
                "posted": "2026-08-11",
                "url": "https://www.linkedin.com/jobs/view/1/",
            },
            cfg,
            salary_parsed={"annual_min": 210_000, "annual_max": 250_000, "raw": "$210k"},
        )
        assert raw is not None
        self.assertEqual(raw.salary, "ok")
        self.assertEqual(raw.company_name, "Acme")
        self.assertTrue(raw.skip_verify)

    def test_guest_url_includes_sb2_and_workplace(self) -> None:
        qj = self.qj
        url = qj.linkedin_build_guest_url(
            "devops",
            "United States",
            tpr="week",
            workplace=["remote"],
            start=0,
            geo_id=qj.LINKEDIN_US_GEO_ID,
            salary_sb2="9",
        )
        self.assertIn("keywords=devops", url)
        self.assertIn("f_SB2=9", url)
        self.assertIn("f_WT=2", url)
        self.assertIn("geoId=103644278", url)

    def test_fetch_linkedin_uses_profile_queries_and_salary(self) -> None:
        qj = self.qj
        cfg = {
            "profile": {"salary_floor": 200_000},
            "keywords_include_tier1": ["devops", "platform engineer"],
            "search_keywords_extra": ["site reliability engineer"],
        }
        company = {
            "id": "linkedin",
            "name": "LinkedIn",
            "type": "linkedin",
            "linkedin_max_queries": 2,
            "linkedin_pages_per_query": 1,
            "linkedin_fetch_details": False,
            "linkedin_search_sleep": 0,
            "linkedin_min_interval_hours": 0,
            "cache_ttl_hours": 0,
        }
        with mock.patch.object(
            qj, "linkedin_fetch_html", return_value=(200, SAMPLE_CARD_HTML)
        ) as fetch_html:
            raw, note = qj.fetch_linkedin(company, cfg)
        self.assertTrue(raw)
        self.assertEqual(len(raw), 2)
        self.assertIn("linkedin", qj.SEARCH_HANDLERS)
        self.assertIn("f_SB2=9", note)
        self.assertIn("salary_floor=200000", note)
        # 2 queries × 2 passes × 1 page
        self.assertEqual(fetch_html.call_count, 4)
        first_url = fetch_html.call_args_list[0][0][0]
        self.assertIn("f_SB2=9", first_url)

    def test_linkedin_fetch_html_uses_cache(self) -> None:
        qj = self.qj
        url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords=cache-test-{id(self)}"
        )
        # Ensure no leftover cache entry for this URL.
        key = qj.linkedin_html_cache_key(url)
        cache_path = qj.cache_dir(qj.SCRIPT_DIR) / f"{key}.txt"
        if cache_path.is_file():
            cache_path.unlink()
        state = qj.LinkedInFetchState()
        with mock.patch.object(qj, "http_get", return_value=(200, url, SAMPLE_CARD_HTML)) as http_get:
            code1, body1 = qj.linkedin_fetch_html(
                url, cache_ttl_hours=6, state=state, pace_sleep=0
            )
            code2, body2 = qj.linkedin_fetch_html(
                url, cache_ttl_hours=6, state=state, pace_sleep=0
            )
        self.assertEqual(code1, 200)
        self.assertEqual(code2, 200)
        self.assertEqual(body1, body2)
        self.assertEqual(http_get.call_count, 1)
        self.assertEqual(state.live_gets, 1)
        self.assertEqual(state.cache_hits, 1)

    def test_linkedin_fetch_html_429_aborts(self) -> None:
        qj = self.qj
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=rate-limit"
        state = qj.LinkedInFetchState()
        with mock.patch.object(qj, "http_get", return_value=(429, url, "")):
            with mock.patch.object(qj.time, "sleep"):
                code, body = qj.linkedin_fetch_html(
                    url,
                    cache_ttl_hours=0,
                    state=state,
                    pace_sleep=0,
                    retries_429=1,
                    backoff_429_sec=0.01,
                )
        self.assertEqual(code, 429)
        self.assertTrue(state.rate_limited)
        self.assertGreaterEqual(state.live_gets, 2)

    def test_linkedin_cooldown_serves_bundle(self) -> None:
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000}}
        company = {
            "id": "linkedin-cooldown-test",
            "name": "LinkedIn",
            "type": "linkedin",
            "linkedin_min_interval_hours": 6,
            "cache_ttl_hours": 6,
        }
        qj.linkedin_save_bundle(
            "linkedin-cooldown-test",
            [
                {
                    "job_id": "1",
                    "title": "Platform Engineer",
                    "company": "Acme",
                    "location": "Remote",
                    "posted": "2026-08-20",
                    "url": "https://www.linkedin.com/jobs/view/1/",
                    "linkedin_remote_us": "1",
                    "description_text": "DevOps platform work",
                }
            ],
            fingerprint=qj.linkedin_scrape_fingerprint(company, cfg),
        )
        with mock.patch.object(qj, "linkedin_fetch_html") as fetch_html:
            raw, note = qj.fetch_linkedin(company, cfg)
        fetch_html.assert_not_called()
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0].title, "Platform Engineer")
        self.assertIn("cooldown", note)

    def test_handler_registered(self) -> None:
        self.assertIn("linkedin", self.qj.SEARCH_HANDLERS)

    def test_favicon_uses_employer_heuristic(self) -> None:
        qj = self.qj
        company_cfg = {
            "id": "linkedin",
            "name": "LinkedIn",
            "type": "linkedin",
            "source_group": "job_sites",
            "browse_url": "https://www.linkedin.com/jobs/search/",
        }
        domain = qj.company_favicon_domain(
            company_cfg=company_cfg,
            posting_url="https://www.linkedin.com/jobs/view/4422055297/",
            employer_name="Alteryx",
        )
        self.assertEqual(domain, "alteryx.com")
        self.assertTrue(qj._company_skips_favicon_domain_audit(company_cfg))
        self.assertEqual(qj._FETCH_TYPE_ORDER.get("linkedin"), 11)

    def test_brand_labels_prefer_employer(self) -> None:
        qj = self.qj
        job = qj.Job(
            title="Principal, Cloud Platform Architect",
            company_id="linkedin",
            url="https://www.linkedin.com/jobs/view/4422055297/",
            loc="remote",
            match="strong",
            salary="maybe",
            why="",
            meta="",
            description_text="",
            company_name="Alteryx",
        )
        co = qj.CompanyResult(
            id="linkedin",
            name="LinkedIn",
            label="LinkedIn (aggregated)",
            section="aggregated",
            source_group="job_sites",
        )
        display, hint = qj._job_card_brand_labels(
            job, co, {"id": "linkedin", "type": "linkedin", "source_group": "job_sites"}
        )
        self.assertEqual(display, "Alteryx")
        self.assertEqual(hint, "Alteryx")

    def test_apply_company_fields_preserves_aggregator_employer(self) -> None:
        qj = self.qj
        job = qj.Job(
            title="Sr. Principal Front-End Design Automation Engineer",
            company_id="linkedin",
            url="https://www.linkedin.com/jobs/view/1/",
            loc="local",
            match="good",
            salary="maybe",
            why="",
            meta="",
            description_text="",
            company_name="Ampere",
        )
        co = qj.CompanyResult(
            id="linkedin",
            name="LinkedIn",
            label="LinkedIn (aggregated)",
            section="aggregated",
            source_group="job_sites",
        )
        qj.apply_company_result_job_fields(co, job)
        self.assertEqual(job.company_name, "Ampere")
        domain = qj.company_favicon_domain(
            company_cfg={
                "id": "linkedin",
                "type": "linkedin",
                "source_group": "job_sites",
                "browse_url": "https://www.linkedin.com/jobs/search/",
            },
            posting_url=job.url,
            employer_name=job.company_name,
        )
        self.assertEqual(domain, "amperecomputing.com")

    def test_employer_favicon_aliases_for_common_linkedin_brands(self) -> None:
        qj = self.qj
        cases = {
            "Snorkel AI": "snorkel.ai",
            "TikTok USDS Joint Venture": "tiktok.com",
            "Convene, Inc.": "getconvene.com",
            "Intrepid Solutions and Services LLC": "intrepid-solutions.com",
            "Longbridge Singapore": "longbridge.global",
            "Millennium": "mlp.com",
            "Stifel Financial Corp.": "stifel.com",
            "Ampere": "amperecomputing.com",
            "Analog Devices": "analog.com",
            "Cambia Health Solutions": "cambiahealth.com",
            "Elevate Digital": "elevate.digital",
            "Federal Reserve Bank of Cleveland": "clevelandfed.org",
            "Johnson & Johnson MedTech": "jnj.com",
            "Koniag Government Services": "koniag.com",
            "LG Ad Solutions": "lg.com",
            "Lakeview Loan Servicing, LLC.": "mylakeviewloan.com",
            "Metropolitan Transportation Authority": "mta.info",
            "Orange County's Credit Union": "occu.org",
            "Schrödinger": "schrodinger.com",
            "Tata Consultancy Services": "tcs.com",
            "Booz Allen Hamilton": "boozallen.com",
            "Chipotle Mexican Grill": "chipotle.com",
            "Block": "block.xyz",
            "Aurora": "aurora.tech",
            "Handshake": "joinhandshake.com",
            "HDR": "hdrinc.com",
        }
        for name, domain in cases.items():
            self.assertEqual(qj._employer_domain_heuristic(name), domain, name)
        url = qj.company_favicon_url("amperecomputing.com")
        self.assertIn("google.com/s2/favicons", url)
        self.assertIn("amperecomputing.com", url)

    def test_aws_employer_favicon_alias(self) -> None:
        qj = self.qj
        self.assertEqual(
            qj._employer_domain_heuristic("Amazon Web Services (AWS)"),
            "amazon.com",
        )
        domain = qj.company_favicon_domain(
            company_cfg={
                "id": "linkedin",
                "type": "linkedin",
                "source_group": "job_sites",
                "browse_url": "https://www.linkedin.com/jobs/search/",
            },
            posting_url="https://www.linkedin.com/jobs/view/1/",
            employer_name="Amazon Web Services (AWS)",
        )
        self.assertEqual(domain, "amazon.com")

    def test_job_sites_prefer_core_keywords_before_extras(self) -> None:
        qj = self.qj
        cfg = {
            "search_keywords_extra": [
                "distinguished engineer",
                "lead software engineer",
            ],
        }
        company = {
            "id": "linkedin",
            "type": "linkedin",
            "source_group": "job_sites",
            "search_keywords": ["devops", "platform engineer"],
            "linkedin_max_queries": 4,
        }
        qs = qj.cap_company_search_queries(
            company, cfg, max_queries_key="linkedin_max_queries", default=4
        )
        self.assertEqual(qs[:2], ["devops", "platform engineer"])
        self.assertEqual(
            qs,
            [
                "devops",
                "platform engineer",
                "distinguished engineer",
                "lead software engineer",
            ],
        )

    def test_detail_priority_prefers_remote_and_principal(self) -> None:
        qj = self.qj
        rows = [
            {"title": "Software Engineer", "linkedin_remote_us": "0"},
            {"title": "Principal Platform Engineer", "linkedin_remote_us": "0"},
            {"title": "Staff SRE", "linkedin_remote_us": "1"},
        ]
        ordered = sorted(rows, key=qj.linkedin_detail_priority)
        self.assertEqual(ordered[0]["title"], "Staff SRE")
        self.assertEqual(ordered[1]["title"], "Principal Platform Engineer")

    def test_remote_us_pass_forces_remote_loc(self) -> None:
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "local_radius_miles": 50}}
        raw = qj.linkedin_listing_to_raw(
            {
                "job_id": "2",
                "title": "Staff SRE",
                "company": "Acme",
                "location": "Remote - United States",
                "posted": "2026-08-20",
                "url": "https://www.linkedin.com/jobs/view/2/",
                "linkedin_remote_us": "1",
            },
            cfg,
        )
        assert raw is not None
        self.assertEqual(raw.force_loc, "remote")
        self.assertIn("Remote", str(raw.force_loc_label or ""))
        self.assertEqual(raw.company_name, "Acme")

    def test_remote_us_city_hq_with_li_remote_still_forces(self) -> None:
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "local_radius_miles": 50}}
        raw = qj.linkedin_listing_to_raw(
            {
                "job_id": "2b",
                "title": "Staff SRE",
                "company": "Acme",
                "location": "Austin, TX",
                "posted": "2026-08-20",
                "url": "https://www.linkedin.com/jobs/view/2b/",
                "linkedin_remote_us": "1",
            },
            cfg,
            description_text="Fully remote role in the United States. #LI-REMOTE",
        )
        assert raw is not None
        self.assertEqual(raw.force_loc, "remote")

    def test_remote_us_dallas_hybrid_dropped(self) -> None:
        """Hybrid / bare city from remote pass must not become Remote US (guest f_WT is ignored)."""
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "local_radius_miles": 50}}
        raw = qj.linkedin_listing_to_raw(
            {
                "job_id": "4456187750",
                "title": "Site Reliability Engineer",
                "company": "Longbridge Singapore",
                "location": "Dallas, TX",
                "posted": "2026-08-19",
                "url": "https://www.linkedin.com/jobs/view/site-reliability-engineer-at-longbridge-singapore-4456187750/",
                "linkedin_remote_us": "1",
            },
            cfg,
            description_text=(
                "Partner globally across remote/global teams. "
                "Headquartered in Singapore. #LI-HYBRID"
            ),
        )
        self.assertIsNone(raw)
        # Bare city with no remote cue is dropped (not forced Remote US).
        raw2 = qj.linkedin_listing_to_raw(
            {
                "job_id": "4456187750",
                "title": "Site Reliability Engineer",
                "company": "Longbridge Singapore",
                "location": "Dallas, TX",
                "posted": "2026-08-19",
                "url": "https://www.linkedin.com/jobs/view/4456187750/",
                "linkedin_remote_us": "1",
            },
            cfg,
            description_text="Build systems with global teams.",
        )
        self.assertIsNone(raw2)

    def test_remote_us_city_onsite_noise_dropped(self) -> None:
        """City HQ / onsite titles from remote pass are dropped."""
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "local_radius_miles": 50}}
        for listing in (
            {
                "job_id": "4455799302",
                "title": "Principal Engineer, AWS Agentic AI",
                "company": "Amazon Web Services (AWS)",
                "location": "Seattle, WA",
                "url": "https://www.linkedin.com/jobs/view/4455799302/",
                "linkedin_remote_us": "1",
            },
            {
                "job_id": "4443266547",
                "title": "Staff Software Engineer, App Hub",
                "company": "Google",
                "location": "Sunnyvale, CA",
                "url": "https://www.linkedin.com/jobs/view/4443266547/",
                "linkedin_remote_us": "1",
            },
            {
                "job_id": "4457015234",
                "title": "Senior Principal Software Engineer (Onsite)",
                "company": "Collins Aerospace",
                "location": "Fulton, MD",
                "url": "https://www.linkedin.com/jobs/view/4457015234/",
                "linkedin_remote_us": "1",
            },
            {
                "job_id": "4446125177",
                "title": "Staff Software Engineer - Compute Infrastructure",
                "company": "LinkedIn",
                "location": "Mountain View, CA",
                "url": "https://www.linkedin.com/jobs/view/4446125177/",
                "linkedin_remote_us": "1",
            },
        ):
            self.assertIsNone(qj.linkedin_listing_to_raw(listing, cfg), listing["title"])

    def test_linkedin_employer_favicon_allowed(self) -> None:
        qj = self.qj
        self.assertEqual(qj._employer_domain_heuristic("LinkedIn"), "linkedin.com")
        domain = qj.company_favicon_domain(
            company_cfg={
                "id": "linkedin",
                "type": "linkedin",
                "source_group": "job_sites",
                "browse_url": "https://www.linkedin.com/jobs/search/",
            },
            posting_url="https://www.linkedin.com/jobs/view/4446125177/",
            employer_name="LinkedIn",
        )
        self.assertEqual(domain, "linkedin.com")
        url = qj.company_favicon_url(domain)
        self.assertIn("linkedin.com", url)
        self.assertIn("google.com/s2/favicons", url)

    def test_remote_us_pass_keeps_portland_local(self) -> None:
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "local_radius_miles": 50}}
        raw = qj.linkedin_listing_to_raw(
            {
                "job_id": "3",
                "title": "Platform Engineer",
                "company": "Ampere",
                "location": "Portland, OR",
                "posted": "2026-08-17",
                "url": "https://www.linkedin.com/jobs/view/3/",
                "linkedin_remote_us": "1",
            },
            cfg,
        )
        assert raw is not None
        self.assertIsNone(raw.force_loc)
        self.assertEqual(raw.location_name, "Portland, OR")

    def test_remote_us_hillsborough_nh_not_treated_as_local(self) -> None:
        """Hillsborough, NH must not match Hillsboro metro; bare city remote-pass is dropped."""
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "local_radius_miles": 50}}
        raw = qj.linkedin_listing_to_raw(
            {
                "job_id": "4406977268",
                "title": "Senior Principal Engineer - AI/ML",
                "company": "Celestica",
                "location": "Hillsborough County, NH",
                "posted": "2026-08-20",
                "url": "https://www.linkedin.com/jobs/view/4406977268/",
                "linkedin_remote_us": "1",
            },
            cfg,
        )
        self.assertIsNone(raw)

    def test_dedupe_same_employer_title_keeps_newer_job_id(self) -> None:
        qj = self.qj
        listings = [
            {
                "job_id": "4437561880",
                "title": "Senior / Staff Platform Engineer",
                "company": "Radar",
                "location": "United States",
                "posted": "2026-08-18",
                "url": "https://www.linkedin.com/jobs/view/senior-staff-platform-engineer-at-radar-4437561880",
                "linkedin_remote_us": "0",
            },
            {
                "job_id": "4437576255",
                "title": "Senior / Staff Platform Engineer",
                "company": "Radar",
                "location": "United States",
                "posted": "2026-08-21",
                "url": "https://www.linkedin.com/jobs/view/senior-staff-platform-engineer-at-radar-4437576255",
                "linkedin_remote_us": "1",
            },
        ]
        deduped, removed = qj.linkedin_dedupe_listings_by_employer_title(listings)
        self.assertEqual(removed, 1)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["job_id"], "4437576255")
        self.assertEqual(deduped[0]["linkedin_remote_us"], "1")

    def test_dedupe_keeps_distinct_employers_with_same_title(self) -> None:
        qj = self.qj
        listings = [
            {
                "job_id": "1",
                "title": "Infrastructure Engineer",
                "company": "Bishop Fox",
                "url": "https://www.linkedin.com/jobs/view/1",
            },
            {
                "job_id": "2",
                "title": "Infrastructure Engineer",
                "company": "Insight Global",
                "url": "https://www.linkedin.com/jobs/view/2",
            },
        ]
        deduped, removed = qj.linkedin_dedupe_listings_by_employer_title(listings)
        self.assertEqual(removed, 0)
        self.assertEqual(len(deduped), 2)

    def test_dedupe_marks_non_local_remote_pass(self) -> None:
        qj = self.qj
        cfg = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "local_radius_miles": 50}}
        company = {
            "id": "linkedin-dedupe-test",
            "name": "LinkedIn",
            "type": "linkedin",
            "linkedin_max_queries": 1,
            "linkedin_pages_per_query": 1,
            "linkedin_fetch_details": False,
            "linkedin_search_sleep": 0,
            "linkedin_min_interval_hours": 0,
            "cache_ttl_hours": 0,
            "search_keywords": ["devops"],
            "skip_search_keywords_extra": True,
        }
        remote_card = """
        <ul><li>
        <div class="base-search-card" data-entity-urn="urn:li:jobPosting:777">
          <a href="https://www.linkedin.com/jobs/view/777/">
            <h3 class="base-search-card__title">Staff SRE</h3>
          </a>
          <h4 class="base-search-card__subtitle">Remote Co</h4>
          <span class="job-search-card__location">Austin, TX</span>
          <time datetime="2026-08-18">2 days ago</time>
        </div>
        </li></ul>
        """
        calls = {"n": 0}

        def fake_fetch(url, **kwargs):
            calls["n"] += 1
            # First passes are portland metro (empty), then remote_us gets the card.
            if "Portland" in url or "portland" in url.lower():
                return (200, "<ul></ul>")
            return (200, remote_card)

        with mock.patch.object(qj, "linkedin_fetch_html", side_effect=fake_fetch):
            raw, note = qj.fetch_linkedin(company, cfg)
        self.assertEqual(len(raw), 0)
        # Austin city HQ from remote pass with no remote cue is dropped.


if __name__ == "__main__":
    unittest.main()
