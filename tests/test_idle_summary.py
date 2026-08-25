#!/usr/bin/env python3
"""Idle status: published HTML should supersede stale incomplete cron blocks."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RUN = Path.home() / "local/bin/quickjobs-server/run"


class IdleSummaryTests(unittest.TestCase):
    def test_stale_cron_hidden_when_html_newer(self) -> None:
        if not RUN.is_file():
            self.skipTest(f"missing {RUN}")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            html = tmp_path / "job-search-quickjobs.html"
            html.write_text(
                "<html>Updated 07/01/26 15:25:00 PDT</html>\n", encoding="utf-8"
            )
            runtime = tmp_path / "job-board-runtime.json"
            runtime.write_text(
                json.dumps({"state": {"run_at": "2026-07-01T22:26:10+00:00"}}),
                encoding="utf-8",
            )
            digest = tmp_path / "job-board-digest.txt"
            digest.write_text("Live roles: 5094\n", encoding="utf-8")
            cron_block = (
                "===== 2026-07-01 12:00:01 UTC | start =====\n"
                "  … scraping HTTP 270/473 · 45m · 12w\n"
            )
            env = os.environ.copy()
            env["BLOCK"] = cron_block
            env["REPORTS_DIR"] = str(tmp_path)
            script = RUN.read_text(encoding="utf-8")
            start = script.index("resolve_idle_summary() {")
            end = script.index("\n}\n\nshow_cron_idle_summary()", start)
            fn_src = script[start:end]
            py_start = fn_src.index("<<'PY'\n") + len("<<'PY'\n")
            py_body = fn_src[py_start : fn_src.rindex("\nPY")]
            wrapper = (
                "import json, sys\n"
                + py_body
                + "\n"
                + "runtime_path = sys.argv[1]\n"
                + "html_path = sys.argv[2]\n"
                + "digest_path = sys.argv[3]\n"
            )
            proc = subprocess.run(
                [str(Path.home() / ".v/bin/python"), "-c", wrapper, str(runtime), str(html), str(digest)],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(proc.stdout.strip())
            self.assertEqual(data["scrape_state"], "completed")
            self.assertFalse(data["show_cron_log"])
            self.assertIn("superseded", data["cron_note"])

    def test_manual_run_log_when_cron_also_completed(self) -> None:
        if not RUN.is_file():
            self.skipTest(f"missing {RUN}")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            html = tmp_path / "job-search-quickjobs.html"
            html.write_text(
                "<html>Updated 07/02/26 08:17:21 PDT</html>\n", encoding="utf-8"
            )
            runtime = tmp_path / "job-board-runtime.json"
            runtime.write_text(
                json.dumps({"state": {"run_at": "2026-07-02T15:17:23+00:00"}}),
                encoding="utf-8",
            )
            digest = tmp_path / "job-board-digest.txt"
            digest.write_text("Live roles: 7689\n", encoding="utf-8")
            run_log = tmp_path / "quickjobs-run-2026-07-02T145416Z.log"
            run_log.write_text(
                "===== 2026-07-02 14:54:16 UTC | start =====\n"
                "455 zero-yield\n"
                "Wrote /mnt/Uploads/html/job-search-quickjobs.html\n"
                "===== 2026-07-02 15:17:23 UTC | exit 0 =====\n",
                encoding="utf-8",
            )
            cron_block = (
                "===== 2026-07-02 00:00:01 UTC | start =====\n"
                "quickjobs.py\n"
                "466 zero-yield\n"
                "===== 2026-07-02 00:11:29 UTC | exit 0 =====\n"
            )
            env = os.environ.copy()
            env["BLOCK"] = cron_block
            env["REPORTS_DIR"] = str(tmp_path)
            script = RUN.read_text(encoding="utf-8")
            start = script.index("resolve_idle_summary() {")
            end = script.index("\n}\n\nshow_cron_idle_summary()", start)
            fn_src = script[start:end]
            py_start = fn_src.index("<<'PY'\n") + len("<<'PY'\n")
            py_body = fn_src[py_start : fn_src.rindex("\nPY")]
            wrapper = (
                "import json, sys\n"
                + py_body
                + "\n"
                + "runtime_path = sys.argv[1]\n"
                + "html_path = sys.argv[2]\n"
                + "digest_path = sys.argv[3]\n"
            )
            proc = subprocess.run(
                [str(Path.home() / ".v/bin/python"), "-c", wrapper, str(runtime), str(html), str(digest)],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(proc.stdout.strip())
            self.assertEqual(data["source"], "quickjobs-run")
            self.assertEqual(data["scrape_state"], "completed")
            self.assertTrue(data["show_run_log"])
            self.assertFalse(data["show_cron_log"])
            self.assertIn("quickjobs-run-2026-07-02T145416Z.log", data["run_log"])


if __name__ == "__main__":
    unittest.main()
