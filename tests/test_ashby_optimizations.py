#!/usr/bin/env python3
"""Ashby board-HTML listing and URL verification optimizations."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

QUICKJOBS_PY = Path(__file__).resolve().parents[1] / "quickjobs.py"


def load_quickjobs():
    spec = importlib.util.spec_from_file_location("quickjobs_mod_ashby_opt", QUICKJOBS_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["quickjobs_mod_ashby_opt"] = mod
    spec.loader.exec_module(mod)
    return mod


BOARD_APP_DATA = {
    "jobBoard": {
        "jobPostings": [
            {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "title": "Platform Engineer",
                "locationName": "San Francisco",
                "workplaceType": "Remote",
                "employmentType": "FullTime",
                "isListed": True,
                "publishedDate": "2026-01-15",
                "secondaryLocations": [
                    {
                        "locationName": "Seattle",
                        "address": {
                            "postalAddress": {"addressCountry": "United States"}
                        },
                    }
                ],
            }
        ]
    }
}


def board_html_body() -> str:
    payload = json.dumps(BOARD_APP_DATA, separators=(",", ":"))
    return f"<!DOCTYPE html><script>window.__appData = {payload};\n</script>"


class AshbyOptimizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_quickjobs()

    def test_skip_url_verify_standard_board_url(self) -> None:
        mod = self.mod
        company = {"id": "harvey", "ashby_board": "harvey"}
        posting = {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "title": "Platform Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/harvey/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        }
        with patch.dict(
            os.environ,
            {"QUICKJOBS_ASHBY_SKIP_URL_VERIFY": "1"},
            clear=False,
        ):
            with patch.object(mod, "ashby_page_is_live") as live:
                url = mod.ashby_pick_posting_url(company, posting)
        self.assertEqual(
            url, "https://jobs.ashbyhq.com/harvey/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        live.assert_not_called()

    def test_custom_careers_url_still_verified(self) -> None:
        mod = self.mod
        company = {
            "id": "cursor",
            "ashby_board": "cursor",
            "ashby_custom_jobs_base": "https://cursor.com/careers",
        }
        posting = {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "title": "Software Engineer",
            "jobUrl": "https://cursor.com/careers/software-engineer",
        }
        with patch.dict(
            os.environ,
            {"QUICKJOBS_ASHBY_SKIP_URL_VERIFY": "1"},
            clear=False,
        ):
            with patch.object(mod, "ashby_page_is_live", return_value=True) as live:
                url = mod.ashby_pick_posting_url(company, posting)
        self.assertEqual(url, "https://cursor.com/careers/software-engineer")
        live.assert_called()

    def test_parse_board_job_postings(self) -> None:
        mod = self.mod
        rows = mod.ashby_parse_board_job_postings(board_html_body())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Platform Engineer")

    def test_board_posting_to_listing(self) -> None:
        mod = self.mod
        row = BOARD_APP_DATA["jobBoard"]["jobPostings"][0]
        listing = mod.ashby_board_posting_to_listing(row, "harvey")
        self.assertEqual(listing["location"], "San Francisco")
        self.assertTrue(listing["isRemote"])
        self.assertEqual(
            listing["jobUrl"],
            "https://jobs.ashbyhq.com/harvey/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.assertNotIn("descriptionPlain", listing)

    def test_fetch_list_postings_prefers_board_html(self) -> None:
        mod = self.mod
        company = {"id": "harvey", "ashby_board": "harvey"}
        html = board_html_body()

        def cache_side_effect(_script_dir, key, ttl_hours=0.0):
            if key == "ashby-board-html-harvey":
                return html
            return None

        with patch.dict(os.environ, {"QUICKJOBS_ASHBY_USE_BOARD_HTML": "1"}, clear=False):
            with patch.object(mod, "cache_get", side_effect=cache_side_effect):
                with patch.object(mod, "http_get") as http_get:
                    postings, source, err = mod.ashby_fetch_list_postings(company, 12.0)
        http_get.assert_not_called()
        self.assertIsNone(err)
        self.assertEqual(source, "board-html")
        self.assertEqual(len(postings), 1)
        self.assertEqual(postings[0]["title"], "Platform Engineer")

    def test_fetch_list_postings_falls_back_to_posting_api(self) -> None:
        mod = self.mod
        company = {"id": "harvey", "ashby_board": "harvey"}
        api_body = json.dumps({"jobs": [{"id": "x", "title": "From API", "isListed": True}]})

        def cache_side_effect(_script_dir, key, ttl_hours=0.0):
            if key == "ashby-list-harvey":
                return api_body
            return None

        with patch.dict(os.environ, {"QUICKJOBS_ASHBY_USE_BOARD_HTML": "0"}, clear=False):
            with patch.object(mod, "cache_get", side_effect=cache_side_effect):
                with patch.object(mod, "http_get") as http_get:
                    postings, source, err = mod.ashby_fetch_list_postings(company, 12.0)
        http_get.assert_not_called()
        self.assertIsNone(err)
        self.assertEqual(source, "posting-api")
        self.assertEqual(postings[0]["title"], "From API")

    def test_merge_posting_page_is_remote(self) -> None:
        mod = self.mod
        posting = {"location": "Bengaluru", "isRemote": False}
        page = {
            "posting": {
                "isRemote": True,
                "descriptionPlainText": "Build platform systems.",
            }
        }
        body = f"<script>window.__appData = {json.dumps(page)};\n</script>"
        desc = mod.ashby_merge_posting_page_fields(posting, body)
        self.assertTrue(posting["isRemote"])
        self.assertIn("platform", desc)

    def test_obviously_non_us_onsite_abroad(self) -> None:
        mod = self.mod
        posting = {
            "location": "Dublin",
            "workplaceType": "OnSite",
            "isRemote": False,
        }
        self.assertTrue(mod.ashby_posting_obviously_non_us(posting))
        posting["workplaceType"] = "Hybrid"
        self.assertFalse(mod.ashby_posting_obviously_non_us(posting))

    def test_ashby_detail_window_posting_ids_rotation(self) -> None:
        mod = self.mod
        survivors = [
            ({"id": "a"}, False),
            ({"id": "b"}, False),
            ({"id": "c"}, False),
            ({"id": "w"}, True),
        ]
        with patch.object(mod, "get_ashby_detail_offset", return_value=1):
            detail_ids, offset, non_watch = mod._ashby_detail_window_posting_ids(
                survivors,
                company_id="harvey",
                detail_cap=2,
                use_board_html=True,
            )
        self.assertEqual(offset, 1)
        self.assertEqual(non_watch, 3)
        self.assertEqual(detail_ids, {"b", "c", "w"})

    def test_ashby_detail_window_includes_all_when_under_cap(self) -> None:
        """Offset must not drop early jobs when the board fits in one window."""
        mod = self.mod
        survivors = [({"id": "a"}, False), ({"id": "b"}, False), ({"id": "c"}, False)]
        with patch.object(mod, "get_ashby_detail_offset", return_value=2):
            detail_ids, offset, non_watch = mod._ashby_detail_window_posting_ids(
                survivors,
                company_id="confluent",
                detail_cap=30,
                use_board_html=False,
            )
        self.assertEqual(offset, 2)
        self.assertEqual(non_watch, 3)
        self.assertEqual(detail_ids, {"a", "b", "c"})

    def test_ashby_detail_window_wraps_when_over_cap(self) -> None:
        mod = self.mod
        survivors = [
            ({"id": "a"}, False),
            ({"id": "b"}, False),
            ({"id": "c"}, False),
        ]
        with patch.object(mod, "get_ashby_detail_offset", return_value=2):
            detail_ids, offset, non_watch = mod._ashby_detail_window_posting_ids(
                survivors,
                company_id="harvey",
                detail_cap=2,
                use_board_html=True,
            )
        self.assertEqual(offset, 2)
        self.assertEqual(non_watch, 3)
        self.assertEqual(detail_ids, {"c", "a"})

    def test_ashby_salary_from_confluent_k_summary(self) -> None:
        mod = self.mod
        body = (
            "<script>window.__appData = "
            + json.dumps(
                {
                    "posting": {
                        "compensationTierSummary": "$197.4K – $271.2K • Offers Equity",
                        "compensationTiers": [
                            {
                                "tierSummary": "$197.4K – $271.2K • Offers Equity",
                                "components": [],
                            }
                        ],
                    }
                }
            )
            + ";\n</script>"
        )
        cfg = {"profile": {"salary_floor": 180000}}
        salary, label = mod.ashby_salary_from_posting_html(
            body, cfg, title="Distributed Systems Software Engineer - WarpStream"
        )
        self.assertEqual(salary, "ok")
        self.assertIn("197.4K", label or "")
        self.assertIn("271.2K", label or "")

    def test_fetch_ashby_detail_window_caps_parallel_html(self) -> None:
        mod = self.mod
        postings = [
            {
                "id": f"aaaaaaaa-bbbb-cccc-dddd-00000000000{i}",
                "title": f"Platform Engineer {i}",
                "location": "Remote",
                "workplaceType": "Remote",
                "employmentType": "FullTime",
                "isListed": True,
                "publishedAt": "2026-01-15",
                "isRemote": True,
            }
            for i in range(5)
        ]
        company = {"id": "harvey", "ashby_board": "harvey"}
        cfg = mod.load_config()
        parallel_urls: list[str] = []

        def capture_parallel(urls, fetch_one, *, company_id):
            parallel_urls.extend(urls)
            return {
                url: (
                    f"<script>window.__appData = {json.dumps({'posting': {'descriptionPlainText': 'kubernetes terraform ci/cd', 'isRemote': True}})};\n</script>"
                )
                for url in urls
            }

        with patch.dict(
            os.environ,
            {
                "QUICKJOBS_ASHBY_USE_BOARD_HTML": "1",
                "QUICKJOBS_ASHBY_MAX_DETAILS": "2",
                "QUICKJOBS_ASHBY_FETCH_SALARY_HTML": "0",
            },
            clear=False,
        ):
            with patch.object(mod, "get_ashby_detail_offset", return_value=0):
                with patch.object(
                    mod,
                    "ashby_fetch_list_postings",
                    return_value=(postings, "board-html", None),
                ):
                    with patch.object(
                        mod, "_parallel_fetch_ats_details", side_effect=capture_parallel
                    ):
                        raw, note = mod.fetch_ashby(company, cfg)
        self.assertEqual(len(parallel_urls), 2)
        self.assertEqual(len(raw), 5)
        self.assertIn("list-only", note or "")

    def test_fetch_ashby_list_only_outside_window_keeps_empty_jd(self) -> None:
        mod = self.mod
        postings = [
            {
                "id": "aaaaaaaa-bbbb-cccc-dddd-000000000001",
                "title": "Platform Engineer",
                "location": "Remote",
                "workplaceType": "Remote",
                "employmentType": "FullTime",
                "isListed": True,
                "publishedAt": "2026-01-15",
                "isRemote": True,
            },
            {
                "id": "aaaaaaaa-bbbb-cccc-dddd-000000000002",
                "title": "Senior Platform Engineer",
                "location": "Remote",
                "workplaceType": "Remote",
                "employmentType": "FullTime",
                "isListed": True,
                "publishedAt": "2026-01-15",
                "isRemote": True,
            },
        ]
        company = {"id": "harvey", "ashby_board": "harvey"}
        cfg = mod.load_config()

        def capture_parallel(urls, fetch_one, *, company_id):
            return {
                urls[0]: (
                    f"<script>window.__appData = {json.dumps({'posting': {'descriptionPlainText': 'kubernetes terraform', 'isRemote': True}})};\n</script>"
                )
            }

        with patch.dict(
            os.environ,
            {
                "QUICKJOBS_ASHBY_USE_BOARD_HTML": "1",
                "QUICKJOBS_ASHBY_MAX_DETAILS": "1",
                "QUICKJOBS_ASHBY_FETCH_SALARY_HTML": "0",
            },
            clear=False,
        ):
            with patch.object(mod, "get_ashby_detail_offset", return_value=0):
                with patch.object(
                    mod,
                    "ashby_fetch_list_postings",
                    return_value=(postings, "board-html", None),
                ):
                    with patch.object(
                        mod, "_parallel_fetch_ats_details", side_effect=capture_parallel
                    ):
                        raw, _note = mod.fetch_ashby(company, cfg)
        by_id = {row.job_id: row for row in raw}
        self.assertIn("kubernetes", by_id["aaaaaaaa-bbbb-cccc-dddd-000000000001"].description_text)
        self.assertEqual(by_id["aaaaaaaa-bbbb-cccc-dddd-000000000002"].description_text, "")

    def test_board_html_jd_fetch_still_parses_cash_compensation(self) -> None:
        """Even with salary-HTML env off, JD posting HTML should yield Cash range."""
        mod = self.mod
        posting = {
            "id": "aaaaaaaa-bbbb-cccc-dddd-000000000099",
            "title": "Senior Software Engineer, Developer Experience",
            "location": "Remote U.S.",
            "workplaceType": "Remote",
            "employmentType": "FullTime",
            "isListed": True,
            "publishedAt": "2026-01-15",
            "isRemote": True,
        }
        company = {"id": "vanta", "ashby_board": "vanta"}
        cfg = mod.load_config()
        app_data = {
            "posting": {
                "descriptionPlainText": "Build CI/CD and developer tools on AWS.",
                "isRemote": True,
                "scrapeableCompensationSalarySummary": "$224K - $263K",
                "compensationTierSummary": (
                    "$224K – $263K • Offers Equity • medical benefits"
                ),
            }
        }
        html = (
            f"<script>window.__appData = {json.dumps(app_data)};\n</script>"
        )

        def capture_parallel(urls, fetch_one, *, company_id):
            return {url: html for url in urls}

        with patch.dict(
            os.environ,
            {
                "QUICKJOBS_ASHBY_USE_BOARD_HTML": "1",
                "QUICKJOBS_ASHBY_MAX_DETAILS": "5",
                "QUICKJOBS_ASHBY_FETCH_SALARY_HTML": "0",
            },
            clear=False,
        ):
            with patch.object(mod, "get_ashby_detail_offset", return_value=0):
                with patch.object(
                    mod,
                    "ashby_fetch_list_postings",
                    return_value=([posting], "board-html", None),
                ):
                    with patch.object(
                        mod, "_parallel_fetch_ats_details", side_effect=capture_parallel
                    ):
                        raw, note = mod.fetch_ashby(company, cfg)
        self.assertEqual(len(raw), 1)
        self.assertIn("224", raw[0].salary_label or "")
        self.assertIn("263", raw[0].salary_label or "")
        self.assertIn("list-only", note or "")

    def test_published_at_from_posting_prefers_api_field(self) -> None:
        mod = self.mod
        self.assertEqual(
            mod.ashby_published_at_from_posting(
                {"publishedAt": "2026-07-30T18:29:16.827+00:00", "publishedDate": "2026-01-01"}
            ),
            "2026-07-30T18:29:16.827+00:00",
        )
        self.assertEqual(
            mod.ashby_published_at_from_posting({"publishedDate": "2026-01-15"}),
            "2026-01-15",
        )
        self.assertEqual(mod.ashby_published_at_from_posting({}), "")

    def test_published_at_from_html_json_ld(self) -> None:
        mod = self.mod
        body = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","datePosted":"2026-07-30","title":"SRE"}'
            "</script>"
        )
        self.assertEqual(mod.ashby_published_at_from_html(body), "2026-07-30")
        ts = mod.parse_iso_ts("2026-07-30")
        self.assertGreater(ts, 0)

    def test_overlay_published_at_fills_board_html_rows(self) -> None:
        mod = self.mod
        listings = [
            {"id": "job-1", "title": "SRE", "publishedAt": ""},
            {"id": "job-2", "title": "Platform", "publishedAt": "2026-01-15"},
        ]
        company = {"id": "runpod", "ashby_board": "runpod"}
        with patch.object(
            mod,
            "ashby_fetch_published_at_map",
            return_value={"job-1": "2026-07-30T18:29:16.827+00:00"},
        ) as fetch_map:
            mod.ashby_overlay_published_at(listings, company, 12.0)
        fetch_map.assert_called_once()
        self.assertEqual(listings[0]["publishedAt"], "2026-07-30T18:29:16.827+00:00")
        self.assertEqual(listings[1]["publishedAt"], "2026-01-15")

    def test_overlay_published_at_skips_when_all_dated(self) -> None:
        mod = self.mod
        listings = [{"id": "job-1", "publishedAt": "2026-01-15"}]
        with patch.object(mod, "ashby_fetch_published_at_map") as fetch_map:
            mod.ashby_overlay_published_at(listings, {"id": "runpod"}, 12.0)
        fetch_map.assert_not_called()

    def test_fetch_ashby_board_html_uses_api_dates(self) -> None:
        mod = self.mod
        posting = {
            "id": "aaaaaaaa-bbbb-cccc-dddd-000000000001",
            "title": "Platform Engineer",
            "location": "Remote",
            "workplaceType": "Remote",
            "employmentType": "FullTime",
            "isListed": True,
            "isRemote": True,
        }
        company = {"id": "runpod", "ashby_board": "runpod"}
        cfg = mod.load_config()
        html = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","datePosted":"2026-07-30"}'
            "</script>"
            f"<script>window.__appData = {json.dumps({'posting': {'descriptionPlainText': 'kubernetes terraform ci/cd', 'isRemote': True}})};\n</script>"
        )

        def capture_parallel(urls, fetch_one, *, company_id):
            return {url: html for url in urls}

        with patch.dict(
            os.environ,
            {
                "QUICKJOBS_ASHBY_USE_BOARD_HTML": "1",
                "QUICKJOBS_ASHBY_MAX_DETAILS": "5",
                "QUICKJOBS_ASHBY_FETCH_SALARY_HTML": "0",
            },
            clear=False,
        ):
            with patch.object(mod, "get_ashby_detail_offset", return_value=0):
                with patch.object(
                    mod,
                    "ashby_fetch_list_postings",
                    return_value=([posting], "board-html", None),
                ):
                    with patch.object(
                        mod,
                        "ashby_fetch_published_at_map",
                        return_value={
                            "aaaaaaaa-bbbb-cccc-dddd-000000000001": "2026-07-30T18:29:16.827+00:00"
                        },
                    ):
                        with patch.object(
                            mod,
                            "_parallel_fetch_ats_details",
                            side_effect=capture_parallel,
                        ):
                            raw, _note = mod.fetch_ashby(company, cfg)
        self.assertEqual(len(raw), 1)
        self.assertGreater(raw[0].posted_ts, 0)
        self.assertEqual(
            raw[0].posted_ts, mod.parse_iso_ts("2026-07-30T18:29:16.827+00:00")
        )

    def test_fetch_ashby_html_json_ld_date_when_api_map_empty(self) -> None:
        mod = self.mod
        posting = {
            "id": "aaaaaaaa-bbbb-cccc-dddd-000000000001",
            "title": "Platform Engineer",
            "location": "Remote",
            "workplaceType": "Remote",
            "employmentType": "FullTime",
            "isListed": True,
            "isRemote": True,
        }
        company = {"id": "runpod", "ashby_board": "runpod"}
        cfg = mod.load_config()
        html = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","datePosted":"2026-07-30"}'
            "</script>"
            f"<script>window.__appData = {json.dumps({'posting': {'descriptionPlainText': 'kubernetes terraform ci/cd', 'isRemote': True}})};\n</script>"
        )

        def capture_parallel(urls, fetch_one, *, company_id):
            return {url: html for url in urls}

        with patch.dict(
            os.environ,
            {
                "QUICKJOBS_ASHBY_USE_BOARD_HTML": "1",
                "QUICKJOBS_ASHBY_MAX_DETAILS": "5",
                "QUICKJOBS_ASHBY_FETCH_SALARY_HTML": "0",
            },
            clear=False,
        ):
            with patch.object(mod, "get_ashby_detail_offset", return_value=0):
                with patch.object(
                    mod,
                    "ashby_fetch_list_postings",
                    return_value=([posting], "board-html", None),
                ):
                    with patch.object(mod, "ashby_fetch_published_at_map", return_value={}):
                        with patch.object(
                            mod,
                            "_parallel_fetch_ats_details",
                            side_effect=capture_parallel,
                        ):
                            raw, _note = mod.fetch_ashby(company, cfg)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0].posted_ts, mod.parse_iso_ts("2026-07-30"))


if __name__ == "__main__":
    unittest.main()
