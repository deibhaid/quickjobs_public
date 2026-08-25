#!/usr/bin/env python3
"""Unit tests for scripts/discover/discover_cli.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DISCOVER_DIR = REPO / "scripts" / "discover"
sys.path.insert(0, str(DISCOVER_DIR))
import discover_cli as dc  # noqa: E402


def test_passes_conservative_filters_high_confidence():
    row = {
        "name": "Example Co",
        "is_agency": False,
        "in_base_json": False,
        "ats_api_scrapable": True,
        "ats_confidence": "high",
        "ats_type": "greenhouse",
        "ats_slug": "exampleco",
    }
    assert dc.passes_conservative_filters(row) is True


def test_passes_conservative_filters_rejects_review():
    row = {
        "name": "Example Co",
        "is_agency": False,
        "in_base_json": False,
        "ats_api_scrapable": True,
        "ats_confidence": "review",
        "ats_type": "greenhouse",
        "ats_slug": "exampleco",
    }
    assert dc.passes_conservative_filters(row) is False


def test_build_company_entry_greenhouse():
    row = {
        "name": "Torc Robotics",
        "ats_type": "greenhouse",
        "ats_slug": "torcrobotics",
        "browse_url": "https://boards.greenhouse.io/torcrobotics",
    }
    entry = dc.build_company_entry(row, {"existing"})
    assert entry["id"] == "torc-robotics"
    assert entry["type"] == "greenhouse"
    assert entry["board"] == "torcrobotics"
    assert entry["discover"] is True
    assert entry["browse_url"] == "https://boards.greenhouse.io/torcrobotics"
    assert len(entry["search_keywords"]) >= 10


def test_build_company_entry_ashby():
    row = {
        "name": "Quora",
        "ats_type": "ashby",
        "ats_slug": "quora",
        "browse_url": "https://jobs.ashbyhq.com/quora",
    }
    entry = dc.build_company_entry(row, set())
    assert entry["ashby_board"] == "quora"
    assert entry["type"] == "ashby"


def test_numbered_backup_creates_file(tmp_path, monkeypatch):
    src = tmp_path / "repo" / "quickjobs.david.base.json"
    src.parent.mkdir(parents=True)
    src.write_text('{"companies": []}\n', encoding="utf-8")
    monkeypatch.setattr(dc.Path, "home", classmethod(lambda cls: tmp_path))
    dest = dc.numbered_backup(src)
    assert dest.is_file()
    assert ".numbered_backups" in str(dest)
    assert dest.read_text() == src.read_text()


def test_find_ats_duplicate_groups():
    companies = [
        {"id": "a", "type": "greenhouse", "board": "acme"},
        {"id": "b", "type": "greenhouse", "board": "acme"},
        {"id": "c", "type": "ashby", "ashby_board": "solo"},
    ]
    groups = dc.find_ats_duplicate_groups(companies)
    assert len(groups) == 1
    key, rows = groups[0]
    assert key == ("greenhouse", "acme")
    assert {r["id"] for r in rows} == {"a", "b"}


def test_company_ats_key_skips_incomplete():
    assert dc.company_ats_key({"id": "x", "type": "greenhouse"}) is None
    assert dc.company_ats_key({"id": "x", "type": "greenhouse", "board": "Acme"}) == (
        "greenhouse",
        "acme",
    )


def test_load_candidates_from_report(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    report = out / "dice-new-candidates-2026-07-04.json"
    report.write_text(
        json.dumps(
            {
                "all_api_scrapable_direct_not_in_base": [
                    {
                        "name": "Acme",
                        "postings": 3,
                        "is_agency": False,
                        "in_base_json": False,
                        "ats_api_scrapable": True,
                        "ats_confidence": "high",
                        "ats_type": "greenhouse",
                        "ats_slug": "acme",
                        "browse_url": "https://boards.greenhouse.io/acme",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dc, "OUTPUT_DIR", out)
    rows, origin = dc.load_candidates("dice")
    assert len(rows) == 1
    assert rows[0]["name"] == "Acme"
    assert "report" in origin
