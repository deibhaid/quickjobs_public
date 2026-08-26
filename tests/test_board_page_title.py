#!/usr/bin/env python3
"""Board page title uses full date and time from the run stamp."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
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
        self.assertEqual(title, "Quickjobs - August 25, 2026 - 02:28:34")

    def test_format_board_page_title_no_leading_zero_day(self) -> None:
        when = datetime(2026, 8, 5, 17, 5, 9, tzinfo=timezone.utc)
        local = when.astimezone(ZoneInfo("America/Los_Angeles"))
        title = self.qj.format_board_page_title(when)
        self.assertEqual(
            title,
            f"Quickjobs - August {local.day}, 2026 - {local.strftime('%H:%M:%S')}",
        )
        self.assertNotIn("August 05", title)


if __name__ == "__main__":
    unittest.main()
