#!/usr/bin/env python3
"""Board page title uses full date and time from the run stamp."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_board_title", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestBoardPageTitle(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_format_board_page_title_pacific(self) -> None:
        # 2026-08-25 09:28:34 UTC == 02:28:34 PDT
        when = datetime(2026, 8, 25, 9, 28, 34, tzinfo=timezone.utc)
        title = self.qj.format_board_page_title(when)
        self.assertEqual(title, "August 25, 2026 - 02:28:34")
        self.assertNotIn("Quickjobs", title)
        self.assertNotIn("QuickJobs", title)

    def test_format_board_page_title_no_leading_zero_day(self) -> None:
        when = datetime(2026, 8, 5, 17, 5, 9, tzinfo=timezone.utc)
        local = when.astimezone(ZoneInfo("America/Los_Angeles"))
        title = self.qj.format_board_page_title(when)
        self.assertEqual(
            title,
            f"August {local.day}, 2026 - {local.strftime('%H:%M:%S')}",
        )
        self.assertNotIn("August 05", title)

    def test_build_html_title_uses_completion_not_run_start(self) -> None:
        """Browser title and Updated stamp use HTML write time, not scrape start."""
        qj = self.qj
        run_start = datetime(2026, 8, 27, 7, 0, 2, tzinfo=timezone.utc)  # 00:00:02 PDT
        completed = datetime(2026, 8, 27, 7, 38, 40, tzinfo=timezone.utc)  # 00:38:40 PDT
        cfg = {
            "profile": {"name": "User", "home_zip": "00000"},
            "companies": [],
            "sections": {},
        }
        with mock.patch.object(qj, "utc_now", return_value=completed):
            with mock.patch.object(qj, "prefetch_glassdoor_for_all_companies"):
                html = qj.build_html(cfg, [], run_start, [], {})
        expected_title = qj.format_board_page_title(completed)
        self.assertIn(f"<title>{qj.esc(expected_title)}</title>", html)
        self.assertIn(f"<h1>{qj.esc(expected_title)}</h1>", html)
        self.assertIn("board-header-top", html)
        self.assertIn("text-align: center", html)
        # Must not use scrape-start midnight title.
        wrong = qj.format_board_page_title(run_start)
        self.assertNotEqual(expected_title, wrong)
        self.assertNotIn(f"<title>{qj.esc(wrong)}</title>", html)
        self.assertIn(f"Updated {qj.format_generated_stamp(completed)}", html)


if __name__ == "__main__":
    unittest.main()
