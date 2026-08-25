#!/usr/bin/env python3
"""Footer digest panel HTML and rebuild-snapshot embedding."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "quickjobs.david.py"


def load_module():
    spec = importlib.util.spec_from_file_location("quickjobs_david_test", SOURCE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def qj():
    return load_module()


def test_build_digest_includes_panel_and_sections(qj):
    run_time = datetime(2026, 7, 2, 15, 29, tzinfo=timezone.utc)
    prev_run = datetime(2026, 7, 1, 15, 29, tzinfo=timezone.utc)

    class FakeJob:
        def __init__(self, title: str, *, is_new: bool = False, company_name: str = "Acme"):
            self.title = title
            self.is_new = is_new
            self.company_name = company_name
            self.company_id = "acme"

    jobs = [
        FakeJob("Platform Engineer", is_new=True, company_name="Nike"),
        FakeJob("SRE", is_new=False, company_name="Intel"),
    ]
    html_block, plain = qj.build_digest(
        run_time,
        {"old-url"},
        jobs,
        ["Old Role (https://example.com/old)"],
        ["Junior Analyst"],
        ["Platform Engineer"],
        prev_run_at=prev_run,
    )
    assert 'id="digest-panel"' in html_block
    assert "footer-expand-panel digest-panel is-collapsed" in html_block
    assert "Previous run" in html_block
    assert "New postings" in html_block
    assert "Removed (expired URLs)" in html_block
    assert "Live roles: 2" in plain
    assert "New since last run: 1" in plain


def test_new_postings_digest_lists_all_entries(qj):
    run_time = datetime(2026, 8, 24, 17, 22, tzinfo=timezone.utc)
    prev_run = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)

    class FakeJob:
        def __init__(self, title: str):
            self.title = title
            self.is_new = True
            self.company_name = "Nike"
            self.company_id = "nike"

    jobs = [FakeJob(f"Role {i}") for i in range(26)]
    html_block, plain = qj.build_digest(
        run_time,
        {"old-url"},
        jobs,
        [],
        [],
        [],
        prev_run_at=prev_run,
    )
    assert "New postings (26)" in html_block
    assert "Role 25" in html_block
    assert "digest-detail-more" not in html_block
    assert plain.count("  - Role ") == 26


def test_validate_html_structure_flags_missing_digest_panel(qj):
    html = """<!DOCTYPE html><html><body><footer>
      <button id="toggle-digest" aria-controls="digest-panel"></button>
      <script>
    const pipelineEl = document.getElementById('pipeline-data');
    const digestPanel = document.getElementById('digest-panel');
    const toggleDigest = document.getElementById('toggle-digest');
    wireFooterAccordion(toggleDigest, digestPanel);
      </script>
    </body></html>"""
    issues = qj.validate_embedded_board_js(html)
    assert any("digest-panel markup is missing" in issue for issue in issues)


def test_board_digest_html_marks_new_jobs(qj):
    run_time = datetime(2026, 7, 2, 15, 29, tzinfo=timezone.utc)
    job = qj.Job(
        title="DevOps Engineer",
        url="https://example.com/new",
        company_id="acme",
        match="good",
    )
    co = qj.CompanyResult(id="acme", name="Acme", label="Acme", section="company", jobs=[job])
    prev_state = {
        "urls": ["https://example.com/old"],
        "run_at": "2026-07-01T15:29:00+00:00",
    }
    html_block, _plain = qj.board_digest_html(run_time, [co], [], [], [], prev_state)
    assert "DevOps Engineer" in html_block
    assert job.is_new is True
