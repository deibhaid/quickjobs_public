#!/usr/bin/env python3
"""Dice MCP pagination reads metadata.totalPages (current) and meta.pageCount (legacy)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "dice" / "discover_dice_employers.py"


def _load():
    spec = importlib.util.spec_from_file_location("discover_dice_employers_meta", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestDiceMcpPaginationMeta(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load()

    def test_current_metadata_shape(self) -> None:
        page_count, total = self.mod.dice_payload_page_meta(
            {
                "data": [{"id": "1"}],
                "metadata": {"page": 1, "pageSize": 100, "total": 11617, "totalPages": 117},
            }
        )
        self.assertEqual(page_count, 117)
        self.assertEqual(total, 11617)

    def test_legacy_meta_shape(self) -> None:
        page_count, total = self.mod.dice_payload_page_meta(
            {
                "data": [{"id": "1"}],
                "meta": {"pageCount": 42, "totalResults": 4200},
            }
        )
        self.assertEqual(page_count, 42)
        self.assertEqual(total, 4200)

    def test_missing_meta_defaults_to_one_page(self) -> None:
        page_count, total = self.mod.dice_payload_page_meta({"data": [{"id": "1"}]})
        self.assertEqual(page_count, 1)
        self.assertIsNone(total)

    def test_extract_payload_prefers_structured_content_metadata(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"data":[{"id":"x"}],"metadata":{"totalPages":3,"total":250}}',
                    }
                ],
                "structuredContent": {
                    "data": [{"id": "a"}, {"id": "b"}],
                    "metadata": {"totalPages": 3, "total": 250},
                },
                "isError": False,
            },
        }
        payload = self.mod.extract_payload(data)
        self.assertEqual(len(payload.get("data") or []), 2)
        page_count, total = self.mod.dice_payload_page_meta(payload)
        self.assertEqual(page_count, 3)
        self.assertEqual(total, 250)


if __name__ == "__main__":
    unittest.main()
