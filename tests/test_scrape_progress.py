#!/usr/bin/env python3
"""Scrape progress counter: unique company ids, not retry rows."""

from __future__ import annotations

import importlib.util
import io
import re
import sys
import threading
import unittest
from pathlib import Path

DAVID = Path(__file__).resolve().parents[1] / "quickjobs.david.py"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run_log import TimestampPrefixedStdout  # noqa: E402

_MASHED_STAMP_RE = re.compile(
    r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\d{2}-\d{2}-\d{4}"
)


def load_david():
    spec = importlib.util.spec_from_file_location("quickjobs_david", DAVID)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["quickjobs_david"] = mod
    spec.loader.exec_module(mod)
    return mod


class ScrapeProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_david()

    def test_done_count_dedupes_retries(self) -> None:
        mod = self.mod
        mod.reset_company_progress(3, scrape_ids={"a", "b", "c"})
        mod.log_company_progress("a", 10, "ok")
        mod.log_company_progress("b", 5, "ok")
        mod.log_company_progress("a", 12, "retry", retry=True)
        with mod._PROGRESS_PRINT_LOCK:
            done = mod._progress_done_count_unlocked()
            live = sum(n for n, _ in mod._PROGRESS_BY_ID.values())
        self.assertEqual(done, 2)
        self.assertEqual(live, 17)

    def test_progress_status_text_caps_done_at_total(self) -> None:
        mod = self.mod
        mod.reset_company_progress(2, scrape_ids={"a", "b"})
        with mod._PROGRESS_PRINT_LOCK:
            mod._PROGRESS_BY_ID["a"] = (1, "")
            mod._PROGRESS_BY_ID["b"] = (2, "")
            mod._PROGRESS_BY_ID["extra"] = (3, "")
        text = mod._progress_status_text(
            min(mod._progress_done_count(), 2),
            2,
            sum(n for n, _ in mod._PROGRESS_BY_ID.values()),
            when=mod.datetime(2026, 7, 5, 14, 35, 55, tzinfo=mod.timezone.utc),
        )
        self.assertEqual(
            text, "  2/2 sources - (6 jobs live) - 07/05/2026 14:35:55"
        )

    def test_tty_incremental_line_not_mashed_with_progress_stamp(self) -> None:
        mod = self.mod
        buf = io.StringIO()
        buf.isatty = lambda: True  # type: ignore[method-assign]
        real_stdout = mod.sys.stdout
        mod.sys.stdout = TimestampPrefixedStdout(buf)
        try:
            mod.reset_company_progress(3, scrape_ids={"capitalone", "b", "c"})
            mod.log_company_progress("capitalone", 12, "ok")
        finally:
            mod.sys.stdout = real_stdout
        output = buf.getvalue()
        self.assertNotRegex(output, _MASHED_STAMP_RE, msg=output)
        self.assertIn("capitalone", output)
        self.assertRegex(
            output,
            r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}",
        )
        lines = [ln for ln in output.splitlines() if "scrape" in ln and "capitalone" in ln]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}\s{6,}… scrape")

    def test_tty_incremental_lines_no_blank_gaps(self) -> None:
        mod = self.mod
        buf = io.StringIO()
        buf.isatty = lambda: True  # type: ignore[method-assign]
        real_stdout = mod.sys.stdout
        mod.sys.stdout = TimestampPrefixedStdout(buf)
        try:
            mod.reset_company_progress(3, scrape_ids={"a", "b", "c"})
            mod.log_company_progress("a", 1, "ok")
            mod.log_company_progress("b", 2, "ok")
            mod.log_company_progress("c", 3, "ok")
        finally:
            mod.sys.stdout = real_stdout
        output = buf.getvalue()
        self.assertNotIn("\n\n", output, msg=output)
        scrape_lines = [
            ln for ln in output.splitlines() if "… scrape" in ln and "jobs" in ln
        ]
        self.assertEqual(len(scrape_lines), 3)

    def test_concurrent_incremental_lines_not_mashed(self) -> None:
        mod = self.mod
        buf = io.StringIO()
        buf.isatty = lambda: True  # type: ignore[method-assign]
        real_stdout = mod.sys.stdout
        mod.sys.stdout = TimestampPrefixedStdout(buf)
        try:
            mod.reset_company_progress(4, scrape_ids={"a", "b", "c", "d"})
            barrier = threading.Barrier(2)

            def worker(cid: str, jobs: int) -> None:
                barrier.wait(timeout=5)
                mod.log_company_progress(cid, jobs, "ok")

            t1 = threading.Thread(target=worker, args=("a", 1))
            t2 = threading.Thread(target=worker, args=("b", 2))
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)
        finally:
            mod.sys.stdout = real_stdout
        output = buf.getvalue()
        self.assertNotRegex(output, _MASHED_STAMP_RE, msg=output)
        self.assertNotIn("\n\n", output, msg=output)

    def test_duplicate_progress_line_suppressed(self) -> None:
        mod = self.mod
        mod.reset_company_progress(3, scrape_ids={"crowdstrike-excluded", "b", "c"})
        mod.log_company_progress("crowdstrike-excluded", 0, "excluded")
        with mod._PROGRESS_PRINT_LOCK:
            first_count = len(mod._PROGRESS_INCREMENTAL_LOGGED)
        mod.log_company_progress("crowdstrike-excluded", 0, "excluded")
        with mod._PROGRESS_PRINT_LOCK:
            self.assertEqual(len(mod._PROGRESS_INCREMENTAL_LOGGED), first_count)
            self.assertGreater(first_count, 0)

    def test_commit_scrape_result_logs_once(self) -> None:
        mod = self.mod
        mod.reset_company_progress(1, scrape_ids={"cummins"})
        company = {
            "id": "cummins",
            "name": "Cummins",
            "label": "Cummins",
            "section": "matching",
        }
        co = mod.CompanyResult(
            id="cummins",
            name="Cummins",
            label="Cummins",
            section="matching",
            jobs=[],
            search_note="ok",
        )
        mod._commit_scrape_result(co)
        mod._commit_scrape_result(co)
        with mod._PROGRESS_PRINT_LOCK:
            self.assertEqual(
                sum(1 for key in mod._PROGRESS_INCREMENTAL_PRINTED if key == "cummins"),
                1,
            )

    def test_stall_abort_heartbeat_and_worker_commit_one_line(self) -> None:
        mod = self.mod
        mod.reset_company_progress(1, scrape_ids={"alpha-silicon"})
        company = {
            "id": "alpha-silicon",
            "name": "Alpha",
            "label": "Alpha",
            "section": "matching",
        }
        co = mod.company_result_stall_abort(company, 90, 90)
        mod._mark_company_started("alpha-silicon")
        mod._track_worker_company("quickjobs-pool-0", company)
        with mod._STALL_ABORT_LOCK:
            mod._STALL_ABORT_REQUESTED.add("alpha-silicon")
        lines: list[str] = []
        orig_write = mod.sys.stdout.write

        def capture(text: str) -> int:
            if "· alpha-silicon" in text:
                lines.append(text.strip())
            return orig_write(text)

        mod.sys.stdout.write = capture  # type: ignore[method-assign]
        try:
            mod._heartbeat_commit_stall_aborts(["alpha-silicon"], stall_msg="idle stall")
            mod._commit_scrape_result(co)
        finally:
            mod.sys.stdout.write = orig_write  # type: ignore[method-assign]
        self.assertEqual(len(lines), 1)

    def test_hub_batch_does_not_log_when_excluded_from_scrape_scope(self) -> None:
        """Hubs are link-only; main scrape no longer commits them into progress."""
        mod = self.mod
        mod.reset_company_progress(2, scrape_ids={"acme", "beta"})
        lines: list[str] = []
        orig_write = mod.sys.stdout.write

        def _capture(s: str) -> int:
            if "scrape " in s and "jobs" in s:
                lines.append(s)
            return orig_write(s)

        mod.sys.stdout.write = _capture  # type: ignore[method-assign]
        try:
            for cid in ("cooper-companies", "copart"):
                company = {
                    "id": cid,
                    "name": cid,
                    "label": cid,
                    "section": "matching",
                    "type": "hub",
                    "hub_url": f"https://example.com/{cid}",
                }
                co = mod.search_hub(company)
                # Mimic main(): hubs go into results without _commit_scrape_result.
                self.assertEqual(len(co.jobs), 0)
                self.assertEqual(co.search_note, "Career hub link")
        finally:
            mod.sys.stdout.write = orig_write  # type: ignore[method-assign]
        self.assertEqual(lines, [])
        with mod._PROGRESS_PRINT_LOCK:
            self.assertEqual(mod._progress_done_count_unlocked(), 0)
            self.assertEqual(mod._PROGRESS_TOTAL, 2)

    def test_seed_progress_marks_incremental_logged(self) -> None:
        mod = self.mod
        mod.reset_company_progress(2, scrape_ids={"a", "b"})
        co = mod.CompanyResult(
            id="a",
            name="A",
            label="A",
            section="matching",
            jobs=[],
            search_note="cached",
        )
        mod.seed_progress_from_checkpoint({"a": co}, scrape_ids={"a", "b"})
        mod._commit_scrape_result(co)
        with mod._PROGRESS_PRINT_LOCK:
            self.assertIn("a", mod._PROGRESS_INCREMENTAL_LOGGED)

    def test_hub_ids_do_not_count_toward_scrape_progress(self) -> None:
        mod = self.mod
        # Scrape total is real scrapers only; hub ids are out of scope.
        mod.reset_company_progress(2, scrape_ids={"a", "b"})
        mod.log_company_progress("a", 1, "ok")
        mod.log_company_progress("b", 2, "ok")
        mod.log_company_progress("hub-co", 0, "Career hub link")
        with mod._PROGRESS_PRINT_LOCK:
            self.assertEqual(mod._progress_done_count_unlocked(), 2)
            self.assertEqual(mod._PROGRESS_TOTAL, 2)
            self.assertNotIn("hub-co", mod._PROGRESS_BY_ID)

    def test_out_of_scope_company_does_not_inflate_done(self) -> None:
        mod = self.mod
        mod.reset_company_progress(2, scrape_ids={"a", "b"})
        mod.log_company_progress("a", 1, "ok")
        mod.log_company_progress("b", 2, "ok")
        with mod._PROGRESS_PRINT_LOCK:
            mod._PROGRESS_BY_ID["stray"] = (0, "outside scope")
        with mod._PROGRESS_PRINT_LOCK:
            self.assertEqual(mod._progress_done_count_unlocked(), 2)

    def test_company_scrape_recorded_after_commit(self) -> None:
        mod = self.mod
        mod.reset_company_progress(1, scrape_ids={"carrier-global"})
        company = {
            "id": "carrier-global",
            "name": "Carrier",
            "label": "Carrier",
            "section": "matching",
        }
        co = mod.company_result_stall_abort(company, 90, 90)
        mod._commit_scrape_result(co)
        self.assertTrue(mod._company_scrape_recorded("carrier-global", {}))
        timeout_co = mod.company_result_timeout(company, 600)
        self.assertTrue(mod._company_scrape_recorded("carrier-global", {"other": timeout_co}))


if __name__ == "__main__":
    unittest.main()
