#!/usr/bin/env python3
"""Show listing frames the job URL except hosts that refuse framing."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_listing_frame", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class JobListingFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_greenhouse_and_ashby_frame(self) -> None:
        gh = "https://job-boards.greenhouse.io/cloudflare/jobs/7053411"
        ash = "https://jobs.ashbyhq.com/docker/5119e349-09a6-43fd-91de-db7decfa5ff9"
        self.assertEqual(
            self.qj.job_listing_frame_url(gh),
            "https://job-boards.greenhouse.io/embed/job_app?for=cloudflare&token=7053411",
        )
        self.assertEqual(self.qj.job_listing_frame_url(ash), ash)

    def test_upstart_frame_stays_on_greenhouse(self) -> None:
        src = "https://job-boards.greenhouse.io/upstart/jobs/8047138"
        self.assertEqual(
            self.qj.job_listing_frame_url(src),
            "https://job-boards.greenhouse.io/embed/job_app?for=upstart&token=8047138",
        )

    def test_workday_and_linkedin_fall_back(self) -> None:
        self.assertEqual(
            self.qj.job_listing_frame_url(
                "https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/Principal-Engineer"
            ),
            "",
        )
        self.assertEqual(
            self.qj.job_listing_frame_url("https://wd1.myworkdaysite.com/recruiting/acme/jobs"),
            "",
        )
        self.assertEqual(
            self.qj.job_listing_frame_url("https://www.linkedin.com/jobs/view/123"),
            "",
        )

    def test_company_landing_pages_fall_back(self) -> None:
        self.assertEqual(
            self.qj.job_listing_frame_url(
                "https://www.bill.com/job?6107864004&gh_jid=6107864004"
            ),
            "",
        )
        self.assertEqual(
            self.qj.job_listing_frame_url(
                "https://www.amazon.jobs/en/jobs/10558083/senior-solutions-architect"
            ),
            "",
        )
        self.assertEqual(
            self.qj.job_listing_frame_url(
                "https://weworkremotely.com/remote-jobs/zoominfo-technologies-llc-principal"
            ),
            "",
        )

    def test_show_listing_markup(self) -> None:
        html = self.qj.render_show_listing_block(
            "https://job-boards.greenhouse.io/acme/jobs/1",
            description_html="<p>Platform work.</p>",
        )
        self.assertIn("Show listing", html)
        self.assertIn("data-listing-url=", html)
        self.assertIn("data-listing-sandbox", html)
        self.assertIn("job-listing-frame", html)
        self.assertNotIn("Saved description", html)
        self.assertNotIn("Expand description", html)
        ash = self.qj.render_show_listing_block(
            "https://jobs.ashbyhq.com/docker/5119e349-09a6-43fd-91de-db7decfa5ff9"
        )
        self.assertNotIn("data-listing-sandbox", ash)

    def test_ashby_frame_ancestors_star_allows_framing(self) -> None:
        allowed = {
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors *",
        }
        blocked = {
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'",
        }
        self.assertTrue(self.qj.ashby_headers_allow_frame(allowed))
        self.assertFalse(self.qj.ashby_headers_allow_frame(blocked))

    def test_ashby_refuse_without_snapshot_uses_saved_description(self) -> None:
        url = "https://jobs.ashbyhq.com/clickhouse/6b2709a0-ee6b-481a-b72c-87a669acd055"
        original_doc = self.qj.ashby_listing_document
        original_capture = self.qj._capture_listing_snapshot
        self.qj.ashby_listing_document = lambda _url: ""
        self.qj._capture_listing_snapshot = lambda _url: ""
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            self.assertEqual(self.qj.listing_frame_url_for_card(url), "")
            html = self.qj.render_job_description_block("On call for the platform.", url)
        finally:
            self.qj.ashby_listing_document = original_doc
            self.qj._capture_listing_snapshot = original_capture
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("On call for the platform.", html)
        self.assertNotIn("Expand description", html)

    def test_ashby_snapshot_shows_local_listing(self) -> None:
        url = "https://jobs.ashbyhq.com/clickhouse/6b2709a0-ee6b-481a-b72c-87a669acd055"
        original_doc = self.qj.ashby_listing_document
        self.qj.ashby_listing_document = lambda _url: "<main>Senior Site Reliability</main>"
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block("On call for the platform.", url)
        finally:
            self.qj.ashby_listing_document = original_doc
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("data-listing-snapshot", html)
        self.assertIn("job-listing-snapshot", html)
        self.assertIn("Senior Site Reliability", html)
        self.assertNotIn("data-listing-url", html)

    def test_smartrecruiters_uses_local_posting(self) -> None:
        url = "https://jobs.smartrecruiters.com/mirantis/744000151683079"
        self.assertEqual(self.qj.listing_frame_url_for_card(url), "")
        company, pid = self.qj.smartrecruiters_company_and_posting_id(url)
        self.assertEqual(company, "mirantis")
        self.assertEqual(pid, "744000151683079")
        html_doc = self.qj.smartrecruiters_listing_html_from_posting(
            {
                "name": "Senior Principal Engineer",
                "postingUrl": url,
                "jobAd": {
                    "sections": {
                        "jobDescription": {
                            "title": "Job Description",
                            "text": "<p>Set the technical direction across the k0rdent engineering department.</p>"
                            "<script>alert(1)</script>",
                        },
                        "qualifications": {
                            "title": "Qualifications",
                            "text": "<ul><li>Expert-level proficiency across Kubernetes.</li></ul>",
                        },
                    }
                },
            },
            url,
        )
        self.assertIn("Senior Principal Engineer", html_doc)
        self.assertIn("Job Description", html_doc)
        self.assertIn("k0rdent engineering department", html_doc)
        self.assertNotIn("<script>", html_doc)
        self.assertNotIn("alert(1)", html_doc)
        original = self.qj.smartrecruiters_listing_document
        self.qj.smartrecruiters_listing_document = lambda _url: html_doc
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            block = self.qj.render_job_description_block("Stored summary.", url)
        finally:
            self.qj.smartrecruiters_listing_document = original
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("data-listing-snapshot", block)
        self.assertNotIn("data-listing-url", block)
        self.assertIn("Senior Principal Engineer", block)

    def test_unframed_listing_uses_local_snapshot(self) -> None:
        url = "https://www.linkedin.com/jobs/view/123"
        original_capture = self.qj._capture_listing_snapshot
        original_guest = self.qj.linkedin_guest_listing_document
        self.qj._capture_listing_snapshot = lambda _url: (_ for _ in ()).throw(
            AssertionError("LinkedIn must use the guest posting")
        )
        self.qj.linkedin_guest_listing_document = (
            lambda _url: "<main><h1>Kubernetes platform</h1></main>"
        )
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block(
                "Build the platform.\n\nRequirements: Kubernetes.",
                url,
            )
        finally:
            self.qj._capture_listing_snapshot = original_capture
            self.qj.linkedin_guest_listing_document = original_guest
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("data-listing-snapshot", html)
        self.assertIn("Kubernetes platform", html)
        self.assertNotIn("Expand description", html)

    def test_linkedin_guest_miss_uses_saved_description(self) -> None:
        url = "https://www.linkedin.com/jobs/view/123"
        original_capture = self.qj._capture_listing_snapshot
        original_guest = self.qj.linkedin_guest_listing_document
        self.qj._capture_listing_snapshot = lambda _url: (_ for _ in ()).throw(
            AssertionError("LinkedIn must not capture the site shell")
        )
        self.qj.linkedin_guest_listing_document = lambda _url: ""
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block(
                "Build the platform.\n\nRequirements: Kubernetes.",
                url,
            )
        finally:
            self.qj._capture_listing_snapshot = original_capture
            self.qj.linkedin_guest_listing_document = original_guest
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("Kubernetes", html)
        self.assertNotIn("Expand description", html)

    def test_linkedin_fragment_keeps_the_title_and_posting(self) -> None:
        fragment = (
            '<h2 class="top-card-layout__title">Senior Site Reliability Engineer</h2>'
            '<div class="show-more-less-html__markup">'
            "We are committed to providing reliable services for customers across the platform."
            '<ul><li>On call</li></ul><a href="https://example.com/apply">Apply</a>'
            "</div></section>"
        )
        html = self.qj.linkedin_listing_document_from_fragment(
            fragment,
            "https://www.linkedin.com/jobs/view/1",
        )
        self.assertIn("<h1>Senior Site Reliability Engineer</h1>", html)
        self.assertIn("On call", html)
        self.assertIn('target="_top"', html)

    def test_loading_shell_is_not_a_listing(self) -> None:
        self.assertTrue(
            self.qj.listing_snapshot_is_loading_shell('<body class="app-loading font">')
        )
        self.assertFalse(self.qj.listing_snapshot_is_loading_shell("<body class=\"ready\">"))

    def test_bot_wall_snapshot_uses_saved_description(self) -> None:
        url = "https://weworkremotely.com/remote-jobs/zoominfo-technologies-llc-principal"
        wall = (
            "<html><body><h1>Performing security verification</h1>"
            "<p>This website uses a security service to protect against malicious bots. "
            "This page is displayed while the website verifies you are not a bot.</p>"
            "</body></html>"
        )
        original = self.qj._capture_listing_snapshot
        self.qj._capture_listing_snapshot = lambda _url: wall
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block(
                "Own the data platform across AWS accounts.",
                url,
            )
        finally:
            self.qj._capture_listing_snapshot = original
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertNotIn("Expand description", html)
        self.assertNotIn("Performing security verification", html)
        self.assertIn("Own the data platform", html)

    def test_replace_bot_wall_keeps_real_snapshot(self) -> None:
        wall = self.qj.render_show_listing_block(
            "",
            apply_key="zoominfo-1",
            snapshot_html=(
                "<h1>Performing security verification</h1>"
                "<p>verifies you are not a bot</p>"
            ),
        )
        real = self.qj.render_show_listing_block(
            "",
            apply_key="clickhouse-1",
            snapshot_html="<main>Senior Site Reliability</main>",
        )
        html, count = self.qj.replace_bot_wall_listing_blocks(wall + real)
        self.assertEqual(count, 1)
        self.assertIn("Expand description", html)
        self.assertIn('data-desc-key="zoominfo-1"', html)
        self.assertNotIn("Performing security verification", html)
        self.assertIn("Senior Site Reliability", html)
        self.assertIn('data-desc-key="clickhouse-1"', html)
        self.assertIn("Show listing", html)

    def test_missing_greenhouse_job_uses_saved_description(self) -> None:
        url = "https://job-boards.greenhouse.io/pinterest/jobs/7494956"
        original = self.qj.greenhouse_listing_document
        original_capture = self.qj._capture_listing_snapshot
        self.qj.greenhouse_listing_document = lambda _url, _company=None: ""
        self.qj._capture_listing_snapshot = lambda _url: (_ for _ in ()).throw(
            AssertionError("removed Greenhouse job must not be snapshotted")
        )
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block(
                "Sr. Staff Software Engineer, Big Data Platform.",
                url,
            )
        finally:
            self.qj.greenhouse_listing_document = original
            self.qj._capture_listing_snapshot = original_capture
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("Big Data Platform", html)
        self.assertNotIn("Expand description", html)
        self.assertNotIn("job_board", html)
        self.assertNotIn("embed/job_app", html)

    def test_live_greenhouse_uses_posting_not_application(self) -> None:
        url = "https://job-boards.greenhouse.io/pinterest/jobs/7990090"
        original = self.qj.greenhouse_listing_document
        self.qj.greenhouse_listing_document = (
            lambda _url, _company=None: "<main><h1>Staff engineer</h1><p>Platform work.</p></main>"
        )
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block("Staff engineer.", url)
        finally:
            self.qj.greenhouse_listing_document = original
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("data-listing-snapshot", html)
        self.assertIn("Platform work.", html)
        self.assertNotIn("embed/job_app", html)
        self.assertNotIn("Expand description", html)

    def test_replace_job_board_frame_keeps_real_embed(self) -> None:
        missing = self.qj.render_show_listing_block(
            "https://job-boards.greenhouse.io/embed/job_app?for=pinterest&token=7494956",
            apply_key="https://job-boards.greenhouse.io/pinterest/jobs/7494956",
        )
        live = self.qj.render_show_listing_block(
            "https://job-boards.greenhouse.io/embed/job_app?for=pinterest&token=7990090",
            apply_key="https://job-boards.greenhouse.io/pinterest/jobs/7990090",
        )
        html, count = self.qj.replace_refused_listing_frames(
            missing + live,
            lambda url: url.endswith("token=7494956"),
        )
        self.assertEqual(count, 1)
        self.assertIn("Expand description", html)
        self.assertIn("token=7990090", html)
        self.assertIn("Show listing", html)
        self.assertNotIn("token=7494956", html)

    def test_redventures_gh_jid_uses_posting_not_board(self) -> None:
        url = "https://www.redventures.com/careers/positions/open?gh_jid=8214077"
        company = {"type": "greenhouse", "board": "redventures"}
        original = self.qj.greenhouse_listing_document
        self.qj.greenhouse_listing_document = (
            lambda _url, _company=None: "<main><p>Assess the product.</p></main>"
        )
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            frame = self.qj.listing_frame_url_for_job(url, company)
            html = self.qj.render_job_description_block_lazy(
                url,
                url,
                has_description=True,
                frame_url=frame,
                company=company,
            )
        finally:
            self.qj.greenhouse_listing_document = original
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertEqual(frame, "")
        self.assertIn("Show listing", html)
        self.assertIn("data-listing-snapshot", html)
        self.assertIn("Assess the product.", html)
        self.assertNotIn("embed/job_app", html)
        self.assertNotIn("Open Positions", html)

    def test_replace_redventures_snapshot_with_embed(self) -> None:
        index = self.qj.render_show_listing_block(
            "",
            apply_key="https://www.redventures.com/careers/positions/open?gh_jid=8214077",
            snapshot_html="<h1>Open Positions — Red Ventures</h1>",
        )
        real = self.qj.render_show_listing_block(
            "",
            apply_key="https://jobs.ashbyhq.com/clickhouse/6b2709a0-ee6b-481a-b72c-87a669acd055",
            snapshot_html="<main>Senior Site Reliability</main>",
        )
        html, count = self.qj.replace_gh_jid_snapshot_frames(index + real, "redventures")
        self.assertEqual(count, 1)
        self.assertIn("embed/job_app?for=redventures&amp;token=8214077", html)
        self.assertNotIn("Open Positions", html)
        self.assertIn("Senior Site Reliability", html)
        self.assertIn("data-listing-snapshot", html)

    def test_workday_listing_uses_the_posting(self) -> None:
        url = (
            "https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers/job/"
            "USA---Remote/Sr-Infrastructure-Engineer---Kubernetes--Remote-_R29056"
        )
        self.assertEqual(
            self.qj.workday_cxs_url(url),
            "https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/"
            "crowdstrikecareers/job/USA---Remote/"
            "Sr-Infrastructure-Engineer---Kubernetes--Remote-_R29056",
        )
        document = self.qj.workday_listing_document_from_posting(
            {
                "title": "Sr. Platform Engineer - Kubernetes (Remote)",
                "jobDescription": "<p>" + ("Protect the platform. " * 8) + "</p>",
            },
            url,
        )
        self.assertIn("<h1>Sr. Platform Engineer - Kubernetes (Remote)</h1>", document)
        self.assertIn("Protect the platform.", document)
        original_capture = self.qj._capture_listing_snapshot
        original_guest = self.qj.workday_guest_listing_document
        self.qj._capture_listing_snapshot = lambda _url: (_ for _ in ()).throw(
            AssertionError("Workday must use the posting JSON")
        )
        self.qj.workday_guest_listing_document = lambda _url: document
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block("Saved Kubernetes posting.", url)
        finally:
            self.qj._capture_listing_snapshot = original_capture
            self.qj.workday_guest_listing_document = original_guest
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("Sr. Platform Engineer - Kubernetes (Remote)", html)
        self.assertNotIn("Expand description", html)

    def test_workday_posting_miss_uses_saved_description(self) -> None:
        url = (
            "https://autodesk.wd1.myworkdayjobs.com/Ext/job/Portland-OR-USA/"
            "Software-Engineer_26WD101204-1"
        )
        original_capture = self.qj._capture_listing_snapshot
        original_guest = self.qj.workday_guest_listing_document
        self.qj._capture_listing_snapshot = lambda _url: (_ for _ in ()).throw(
            AssertionError("Workday must not capture the jobs shell")
        )
        self.qj.workday_guest_listing_document = lambda _url: ""
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block("Senior Software Engineer at Autodesk.", url)
        finally:
            self.qj._capture_listing_snapshot = original_capture
            self.qj.workday_guest_listing_document = original_guest
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("Senior Software Engineer at Autodesk.", html)
        self.assertNotIn("Expand description", html)

    def test_oracle_posting_keeps_headings_and_separate_lines(self) -> None:
        detail = {
            "Title": "Senior Platform Software Engineer",
            "ExternalDescriptionStr": "<p>Join the team that builds platform services.</p>",
            "ExternalResponsibilitiesStr": (
                "<p><strong>What You'll Do</strong></p>"
                "<p>Design, develop, test, and maintain software components.</p>"
                "<p><strong>&nbsp;</strong></p>"
                "<p><strong>What You'll Bring</strong></p>"
                "<p>3+ years of professional software-development experience.</p>"
                "<p><strong>Responsibilities</strong></p>"
                "<p><strong>Software Development</strong></p>"
                "<p>Implement features and services from defined technical requirements.</p>"
            ),
            "ExternalQualificationsStr": "",
        }
        url = "https://careers.oracle.com/en/sites/jobsearch/job/343530"
        document = self.qj.oracle_listing_document_from_detail(detail, url)
        self.assertIn("<h1>Senior Platform Software Engineer</h1>", document)
        self.assertIn("<h2>What You&#x27;ll Do</h2>", document)
        self.assertIn("<h2>What You&#x27;ll Bring</h2>", document)
        self.assertIn("<h2>Responsibilities</h2>", document)
        self.assertIn("<h2>Software Development</h2>", document)
        self.assertIn("<p>Design, develop, test, and maintain software components.</p>", document)
        self.assertIn("<p>3+ years of professional software-development experience.</p>", document)
        self.assertLess(document.find("What You'll Do"), document.find("Design, develop, test"))
        self.assertNotIn("&nbsp;", document)
        original_capture = self.qj._capture_listing_snapshot
        original_guest = self.qj.oracle_guest_listing_document
        self.qj._capture_listing_snapshot = lambda _url: (_ for _ in ()).throw(
            AssertionError("Oracle must use the requisition HTML")
        )
        self.qj.oracle_guest_listing_document = lambda _url: document
        self.qj._LISTING_SNAPSHOTS.pop(url, None)
        try:
            html = self.qj.render_job_description_block("flattened run-on text", url)
        finally:
            self.qj._capture_listing_snapshot = original_capture
            self.qj.oracle_guest_listing_document = original_guest
            self.qj._LISTING_SNAPSHOTS.pop(url, None)
        self.assertIn("Show listing", html)
        self.assertIn("<h2>What You&#x27;ll Do</h2>", html)
        self.assertNotIn("flattened run-on text", html)
        self.assertNotIn("Expand description", html)

    def test_greenhouse_application_page_gets_the_listing_text(self) -> None:
        page = (
            "<html><body><main><p>Apply for this job</p>"
            "<form></form><script>redirect()</script></main></body></html>"
        )
        html = self.qj.greenhouse_listing_html_from_parts(
            page,
            "<p>You call. You wait. You call again.</p>",
            "Principal Infrastructure Architect: Data Platform",
        )
        self.assertIn("job__description", html)
        self.assertIn("You call. You wait.", html)
        self.assertIn("<h1", html)
        self.assertIn("Principal Infrastructure Architect: Data Platform", html)
        self.assertLess(html.find("<h1"), html.find("job__description"))
        self.assertLess(html.find("job__description"), html.find("Apply for this job"))
        self.assertNotIn("<script", html.lower())

    def test_reflow_splits_glued_sections_and_requirement_items(self) -> None:
        text = (
            "About Upstart At Upstart, we are united by a mission that matters. "
            "How you'll make an impact: Embody and share SRE principles at Upstart "
            "Exercise state-of-the-art SRE practices throughout the company "
            "What we're looking for: Minimum requirements: Minimum of 6 years combined experience "
            "Proficiency coding Python https://www.upstart.com/candidate_privacy_policy"
        )
        html = self.qj.reflow_flattened_posting_text(text)
        self.assertIn("<h2>About Upstart</h2>", html)
        self.assertIn("How you", html)
        self.assertIn("make an impact</h2>", html)
        self.assertIn("<li>Embody and share SRE principles at Upstart</li>", html)
        self.assertIn(
            "<li>Exercise state-of-the-art SRE practices throughout the company</li>",
            html,
        )
        self.assertIn("<li>Proficiency coding Python", html)
        self.assertIn('href="https://www.upstart.com/candidate_privacy_policy"', html)

    def test_greenhouse_closed_id_uses_the_live_same_title(self) -> None:
        company = {"type": "greenhouse", "board": "databricks"}
        original = self.qj.greenhouse_board_jobs
        self.qj.greenhouse_board_jobs = lambda _board: [
            {
                "id": 8407875002,
                "title": "Senior Production Engineer - Realtime Products",
                "absolute_url": "https://www.databricks.com/company/careers/open-positions/job?gh_jid=8407875002",
            }
        ]
        try:
            live = self.qj.greenhouse_live_listing_url(
                "https://databricks.com/company/careers/open-positions/job?gh_jid=8337401002",
                company,
                "Senior Production Engineer - Realtime Products",
            )
        finally:
            self.qj.greenhouse_board_jobs = original
        self.assertEqual(
            live,
            "https://www.databricks.com/company/careers/open-positions/job?gh_jid=8407875002",
        )
        self.qj.greenhouse_board_jobs = lambda _board: [
            {
                "id": 8015547,
                "title": "Staff Software Engineer",
                "absolute_url": "https://www.pinterestcareers.com/jobs/?gh_jid=8015547",
            }
        ]
        try:
            index = self.qj.greenhouse_live_listing_url(
                "https://job-boards.greenhouse.io/pinterest/jobs/8015490",
                {"type": "greenhouse", "board": "pinterest"},
                "Staff Software Engineer",
            )
        finally:
            self.qj.greenhouse_board_jobs = original
        self.assertEqual(
            index,
            "https://job-boards.greenhouse.io/pinterest/jobs/8015547",
        )

    def test_greenhouse_listing_keeps_description_already_on_the_page(self) -> None:
        page = (
            '<html><body><div class="job__description body"><p>We Breathe Life Into Data</p></div>'
            "<script>boot()</script></body></html>"
        )
        html = self.qj.greenhouse_listing_html_from_parts(page, "<p>duplicate</p>")
        self.assertEqual(html.count("job__description"), 1)
        self.assertIn("We Breathe Life Into Data", html)
        self.assertNotIn("duplicate", html)
        self.assertNotIn("<script", html.lower())


if __name__ == "__main__":
    unittest.main()
