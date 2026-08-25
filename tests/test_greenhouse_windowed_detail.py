#!/usr/bin/env python3
"""Greenhouse rotating detail window and prior JD merge."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "quickjobs_david_greenhouse_window", ROOT / "quickjobs.david.py"
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["quickjobs_david_greenhouse_window"] = mod
spec.loader.exec_module(mod)


def _cfg() -> dict:
    return mod.load_config()


def _board_job(job_id: int, title: str = "Platform Engineer") -> dict:
    return {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
        "location": {"name": "Remote"},
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _company(**extra: object) -> dict:
    base = {
        "id": "acme",
        "board": "acme",
        "discover": True,
        "watch_ids": [],
    }
    base.update(extra)
    return base


def _reset_offset_store(offsets: dict[str, int] | None = None) -> None:
    mod._DETAIL_ROTATION_OUT_PATH = None
    with mod._DETAIL_ROTATION_STORE_LOCK:
        mod._DETAIL_ROTATION_STORES.clear()
        if offsets:
            mod._DETAIL_ROTATION_STORES[mod.GREENHOUSE_DETAIL_OFFSETS_UI_KEY] = dict(
                offsets
            )


def test_advance_greenhouse_detail_offset_wraps() -> None:
    _reset_offset_store({"acme": 0})
    assert mod.advance_greenhouse_detail_offset("acme", 10, 3) == 3
    assert mod.get_greenhouse_detail_offset("acme") == 3
    assert mod.advance_greenhouse_detail_offset("acme", 10, 8) == 1
    assert mod.get_greenhouse_detail_offset("acme") == 1


def test_out_of_window_jobs_are_list_only_and_merge_restores_prior_jd() -> None:
    _reset_offset_store({"acme": 0})
    os.environ["QUICKJOBS_GREENHOUSE_MAX_DETAILS"] = "2"
    os.environ.pop("QUICKJOBS_GREENHOUSE_LIST_ONLY", None)
    os.environ.pop("QUICKJOBS_GREENHOUSE_FETCH_CONTENT", None)
    board_jobs = [_board_job(100), _board_job(200), _board_job(300)]
    detail_calls: list[int] = []

    def fake_list_api(url: str, timeout: int | None = None):
        return 200, url, json.dumps({"jobs": board_jobs})

    def fake_detail(board: str, job_id: int, force_refresh: bool = False) -> str:
        detail_calls.append(job_id)
        return f"<p>kubernetes terraform job {job_id}</p>"

    company = _company()
    cfg = _cfg()
    with patch.object(mod, "greenhouse_api_get", side_effect=fake_list_api):
        with patch.object(mod, "greenhouse_fetch_job_content", side_effect=fake_detail):
            raw, note = mod.fetch_greenhouse(company, cfg)
    try:
        assert len(raw) == 3
        assert detail_calls == [100, 200]
        by_id = {row.job_id: row for row in raw}
        assert "kubernetes" in by_id["100"].description_text
        assert "kubernetes" in by_id["200"].description_text
        assert by_id["300"].description_text == ""
        assert by_id["300"].salary == "maybe"
        assert "detail window 0:2 of 3" in (note or "")
        assert mod.get_greenhouse_detail_offset("acme") == 2

        prior = {
            "companies": [
                {
                    "id": "acme",
                    "name": "Acme",
                    "label": "Acme",
                    "section": "company",
                    "jobs": [
                        {
                            "title": "Platform Engineer",
                            "company_id": "acme",
                            "url": by_id["300"].url,
                            "job_id": "300",
                            "match": "good",
                            "loc": "remote",
                            "salary": "ok",
                            "description_text": "prior kubernetes terraform python",
                        }
                    ],
                }
            ]
        }
        co = mod.CompanyResult(
            id="acme",
            name="Acme",
            label="Acme",
            section="company",
            jobs=[
                mod.Job(
                    title=row.title,
                    company_id="acme",
                    url=row.url,
                    job_id=row.job_id,
                    match="stretch",
                    loc="remote",
                    salary=row.salary,
                    description_text=row.description_text,
                )
                for row in raw
            ],
        )
        merged = mod.merge_prior_job_descriptions([co], prior)
        assert merged == 1
        assert "prior kubernetes" in co.jobs[2].description_text
    finally:
        os.environ.pop("QUICKJOBS_GREENHOUSE_MAX_DETAILS", None)


def test_watch_ids_bypass_detail_window() -> None:
    _reset_offset_store({"acme": 0})
    os.environ["QUICKJOBS_GREENHOUSE_MAX_DETAILS"] = "1"
    os.environ.pop("QUICKJOBS_GREENHOUSE_LIST_ONLY", None)
    os.environ.pop("QUICKJOBS_GREENHOUSE_FETCH_CONTENT", None)
    board_jobs = [_board_job(100), _board_job(999, title="Sales Representative")]
    detail_calls: list[int] = []

    def fake_list_api(url: str, timeout: int | None = None):
        return 200, url, json.dumps({"jobs": board_jobs})

    def fake_detail(board: str, job_id: int, force_refresh: bool = False) -> str:
        detail_calls.append(job_id)
        return f"<p>detail {job_id}</p>"

    company = _company(watch_ids=[999])
    cfg = _cfg()
    with patch.object(mod, "greenhouse_api_get", side_effect=fake_list_api):
        with patch.object(mod, "greenhouse_fetch_job_content", side_effect=fake_detail):
            raw, _note = mod.fetch_greenhouse(company, cfg)
    try:
        assert len(raw) == 2
        assert 999 in detail_calls
        assert detail_calls.count(100) == 1
        by_id = {row.job_id: row for row in raw}
        assert by_id["999"].description_text.strip() != ""
        assert by_id["100"].description_text.strip() != ""
    finally:
        os.environ.pop("QUICKJOBS_GREENHOUSE_MAX_DETAILS", None)


def test_persist_greenhouse_detail_offsets_in_runtime_ui(tmp_path: Path) -> None:
    out_path = tmp_path / "job-search-test.html"
    out_path.write_text("<html></html>", encoding="utf-8")
    mod.save_greenhouse_detail_offsets(out_path, {"acme": 4, "beta": 12})
    doc = mod.load_runtime_document(out_path)
    offsets = (doc.get("ui") or {}).get(mod.GREENHOUSE_DETAIL_OFFSETS_UI_KEY) or {}
    assert offsets == {"acme": 4, "beta": 12}
    mod.init_greenhouse_detail_offset_store(out_path)
    assert mod.get_greenhouse_detail_offset("acme") == 4
    mod.advance_greenhouse_detail_offset("acme", 20, 5)
    mod.persist_greenhouse_detail_offset_store()
    reloaded = mod.load_greenhouse_detail_offsets(out_path)
    assert reloaded["acme"] == 9
