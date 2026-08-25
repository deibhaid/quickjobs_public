#!/usr/bin/env python3
"""Tests for board pipeline config and visa/green-card filter wiring."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_quickjobs_module():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_board_filters", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class BoardProfileFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_quickjobs_module()

    def test_filter_reject_log_uses_visa_tag_for_h1b_reason(self) -> None:
        qj = self.qj
        qj.clear_filter_rejects()
        qj.record_jd_filter_reject("acme", "Engineer", "posting explicitly denies visa sponsorship")
        lines = qj.filter_reject_summary_lines()
        joined = "\n".join(lines)
        self.assertIn("[visa]", joined)
        self.assertNotIn("[h1b]", joined)
        self.assertIn("Visa sponsorship filter", joined)

    def test_search_params_panel_shows_work_visa_resident_status(self) -> None:
        qj = self.qj
        cfg = {"profile": {"resident_status": "h1b", "name": "Test", "home_zip": "97035"}}
        panel = qj.render_search_parameters_panel(cfg)
        self.assertIn("work visa", panel)
        self.assertNotIn("H-1B", panel)

    def test_board_pipeline_config_includes_h1b_defaults(self) -> None:
        qj = self.qj
        cfg = {"profile": {"resident_status": "h1b"}}
        out = qj._board_pipeline_config(
            cfg,
            pipeline_server=False,
            default_runtime_path=Path("/tmp/job-board-runtime.json"),
        )
        self.assertEqual(out["residentStatus"], "h1b")
        self.assertIn("defaultTextFilters", out)
        filters = out["defaultTextFilters"]
        self.assertGreaterEqual(len(filters), 10)
        self.assertTrue(all(chip["mode"] == "not" for chip in filters))
        texts = {chip["text"] for chip in filters}
        self.assertIn("does not offer visa sponsorship", texts)
        self.assertTrue(out["defaultFilterScope"]["description"])
        self.assertTrue(out["defaultFilterScope"]["title"])

    def test_board_pipeline_config_includes_green_card_excludes(self) -> None:
        qj = self.qj
        cfg = {"profile": {"resident_status": "green_card"}}
        out = qj._board_pipeline_config(
            cfg,
            pipeline_server=False,
            default_runtime_path=Path("/tmp/job-board-runtime.json"),
        )
        self.assertEqual(out["residentStatus"], "green_card")
        filters = out["defaultTextFilters"]
        self.assertTrue(filters)
        self.assertTrue(all(chip["mode"] == "not" for chip in filters))

    def test_no_visa_sponsor_legend_in_html_template(self) -> None:
        src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")
        self.assertNotIn('data-legend-filter="visa-sponsor"', src)
        self.assertNotIn("visa_legend_filter_button", src)

    def test_lazy_board_split_scripts_present(self) -> None:
        src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")
        self.assertIn('id="lazy-board-index"', src)
        self.assertIn('id="lazy-board-payload"', src)
        self.assertIn('id="lazy-board-descriptions"', src)
        self.assertIn('id="lazy-board-deferred"', src)
        self.assertIn("readLazyBoardIndex", src)
        self.assertIn("readLazyBoardPayload", src)

    def test_hinge_health_favicon_uses_corporate_domain(self) -> None:
        qj = self.qj
        co = {
            "id": "hinge-health",
            "name": "Hinge Health",
            "ashby_board": "hinge-health",
            "browse_url": "https://jobs.ashbyhq.com/hinge-health",
        }
        domain = qj.company_favicon_domain(company_cfg=co)
        self.assertEqual(domain, "hingehealth.com")
        url = qj.company_favicon_url(domain)
        self.assertIn("google.com/s2/favicons", url)
        self.assertIn("hingehealth.com", url)

    def test_flex_favicon_uses_flex_com_not_getflex(self) -> None:
        qj = self.qj
        co = {
            "id": "flex",
            "name": "Flex",
            "board": "flex",
            "browse_url": "https://flex.com/careers",
        }
        domain = qj.company_favicon_domain(company_cfg=co)
        self.assertEqual(domain, "flex.com")
        self.assertNotEqual(domain, "getflex.com")


if __name__ == "__main__":
    unittest.main()
