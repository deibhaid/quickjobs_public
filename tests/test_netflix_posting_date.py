#!/usr/bin/env python3
"""Netflix Job Posting Date from apply API custom_JD.data_fields.posting_date."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_netflix_date", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class NetflixPostingDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_parse_netflix_posting_date_mm_dd_yyyy(self) -> None:
        ts = self.qj.parse_netflix_posting_date("07-15-2026")
        expected = int(datetime(2026, 7, 15, tzinfo=timezone.utc).timestamp())
        self.assertEqual(ts, expected)

    def test_posting_date_from_apply_payload(self) -> None:
        payload = {
            "custom_JD": {
                "data_fields": {
                    "posting_date": ["07-15-2026"],
                    "job_req_id": ["JR31231"],
                }
            }
        }
        self.assertEqual(
            self.qj.netflix_posting_date_from_apply_payload(payload),
            "07-15-2026",
        )

    def test_posting_ts_prefers_posting_date_over_t_create(self) -> None:
        posting_ts = self.qj.parse_netflix_posting_date("07-15-2026")
        position = {"t_create": 1736380800, "t_update": 1767225600}
        original = self.qj.netflix_fetch_apply_detail

        def fake_fetch(_job_id: str) -> dict[str, str]:
            return {"job_description": "jd", "posting_date": "07-15-2026"}

        self.qj.netflix_fetch_apply_detail = fake_fetch  # type: ignore[method-assign]
        try:
            self.assertEqual(self.qj.netflix_posting_ts("790300762468", position), posting_ts)
        finally:
            self.qj.netflix_fetch_apply_detail = original  # type: ignore[method-assign]

    def test_posting_ts_falls_back_to_t_create(self) -> None:
        position = {"t_create": 1736380800, "t_update": 1767225600}
        original = self.qj.netflix_fetch_apply_detail

        def fake_fetch(_job_id: str) -> dict[str, str]:
            return {"job_description": "", "posting_date": ""}

        self.qj.netflix_fetch_apply_detail = fake_fetch  # type: ignore[method-assign]
        try:
            self.assertEqual(self.qj.netflix_posting_ts("790300762468", position), 1736380800)
        finally:
            self.qj.netflix_fetch_apply_detail = original  # type: ignore[method-assign]


if __name__ == "__main__":
    unittest.main()
