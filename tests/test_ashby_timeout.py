#!/usr/bin/env python3
"""Ashby list read timeout and cache helpers."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

QUICKJOBS_PY = Path(__file__).resolve().parents[1] / "quickjobs.py"


def load_quickjobs():
    spec = importlib.util.spec_from_file_location("quickjobs_mod_ashby", QUICKJOBS_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["quickjobs_mod_ashby"] = mod
    spec.loader.exec_module(mod)
    return mod


class AshbyTimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_quickjobs()

    def test_ashby_read_timeout_default(self) -> None:
        mod = self.mod
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QUICKJOBS_ASHBY_READ_TIMEOUT_SEC", None)
            self.assertEqual(mod._ashby_read_timeout_sec(), 180)

    def test_ashby_read_timeout_env_override(self) -> None:
        mod = self.mod
        with patch.dict(os.environ, {"QUICKJOBS_ASHBY_READ_TIMEOUT_SEC": "240"}):
            self.assertEqual(mod._ashby_read_timeout_sec(), 240)

    def test_fetch_ashby_uses_list_cache(self) -> None:
        mod = self.mod
        company = {"id": "harvey", "type": "ashby", "ashby_board": "harvey"}
        cfg: dict = {}
        cached_body = '{"jobs": []}'
        with patch.dict(os.environ, {"QUICKJOBS_ASHBY_USE_BOARD_HTML": "0"}, clear=False):
            with patch.object(mod, "cache_get", return_value=cached_body) as cache_get:
                with patch.object(mod, "http_get") as http_get:
                    raw, note = mod.fetch_ashby(company, cfg)
        cache_get.assert_called_once()
        http_get.assert_not_called()
        self.assertEqual(raw, [])
        self.assertIn("Ashby board harvey", note or "")


if __name__ == "__main__":
    unittest.main()
