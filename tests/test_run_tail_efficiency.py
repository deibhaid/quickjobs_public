#!/usr/bin/env python3
"""Run tail: sampled validation, filter log write, lazy-board parse cache."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_run_tail", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class RunTailEfficiencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_sample_validation_articles_caps_and_keeps_last(self) -> None:
        bodies = [f"body-{i}" for i in range(1000)]
        sample = self.qj._sample_validation_articles(bodies, 120)
        self.assertLessEqual(len(sample), 120)
        self.assertEqual(sample[-1], "body-999")

    def test_structure_validation_sample_size_env(self) -> None:
        prev = os.environ.get("QUICKJOBS_VALIDATE_STRUCTURE_SAMPLE")
        try:
            os.environ["QUICKJOBS_VALIDATE_STRUCTURE_SAMPLE"] = "0"
            self.assertEqual(self.qj.structure_validation_sample_size(), 0)
            os.environ["QUICKJOBS_VALIDATE_STRUCTURE_SAMPLE"] = "50"
            self.assertEqual(self.qj.structure_validation_sample_size(), 50)
        finally:
            if prev is None:
                os.environ.pop("QUICKJOBS_VALIDATE_STRUCTURE_SAMPLE", None)
            else:
                os.environ["QUICKJOBS_VALIDATE_STRUCTURE_SAMPLE"] = prev

    def test_write_filter_reject_log_writes_and_reports(self) -> None:
        import tempfile

        self.qj.clear_filter_rejects()
        tmp = Path(tempfile.gettempdir()) / "job-board-filtered-test.log"
        prev = self.qj.FILTERED_LOG
        self.qj.FILTERED_LOG = tmp
        try:
            self.qj.record_filter_reject("acme", "Engineer", "https://acme/j/1", "title_tier2")
            n = self.qj.write_filter_reject_log(
                datetime(2026, 8, 22, tzinfo=timezone.utc),
                quiet=True,
            )
            self.assertEqual(n, 1)
            text = tmp.read_text(encoding="utf-8")
            self.assertIn("# counts: title_tier2=1", text)
            self.assertIn("acme", text)
        finally:
            self.qj.FILTERED_LOG = prev
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
