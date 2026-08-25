#!/usr/bin/env python3
"""Run log success detection matches legacy and publish-complete lines."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

RUN = Path.home() / "local/bin/quickjobs-server/run"


def _load_success_re() -> re.Pattern[str]:
    text = RUN.read_text(encoding="utf-8")
    m = re.search(r"SUCCESS_RE = re\.compile\(\s*r\"([^\"]+)\"\s*\)", text)
    assert m, "SUCCESS_RE not found in quickjobs-server/run"
    return re.compile(m.group(1))


class RunLogSuccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not RUN.is_file():
            raise unittest.SkipTest(f"missing {RUN}")
        cls.success_re = _load_success_re()

    def _has_success(self, log_text: str) -> bool:
        return bool(self.success_re.search(log_text))

    def test_legacy_wrote_line(self) -> None:
        self.assertTrue(
            self._has_success("Wrote /mnt/Uploads/html/job-search-david.html\n")
        )

    def test_board_publish_complete_line(self) -> None:
        self.assertTrue(
            self._has_success(
                "Board publish complete: /mnt/Uploads/html/job-search-david.html (1378 KB)\n"
            )
        )

    def test_missing_success_line(self) -> None:
        self.assertFalse(self._has_success("Validated badge structure (10253 job cards)\n"))

    def test_run_log_has_success_from_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            fh.write(
                "===== start =====\n"
                "Board publish complete: /mnt/Uploads/html/job-search-david.html (1378 KB)\n"
            )
            path = Path(fh.name)
        try:
            tail = path.read_text(encoding="utf-8")
            self.assertTrue(self._has_success(tail))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
