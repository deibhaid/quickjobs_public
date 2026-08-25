#!/usr/bin/env python3
"""Employers known not to sponsor work visas — excluded for resident_status=h1b."""

from __future__ import annotations

import json
from pathlib import Path

# Resolved from quickjobs base JSON (company id / Greenhouse board).
CANONICAL_NO_VISA_SPONSOR_COMPANY_IDS = (
    "airship",
    "cayuse-holdings-llc",
    "chainguard",
    "defense-unicorns",
    "tria-federal",
)


def load_no_visa_sponsor_company_ids(root: Path) -> list[str]:
    """Load canonical non-sponsoring employer excludes from config snippet."""
    snippet = root / "config" / "no-visa-sponsor-company-ids.json"
    if snippet.is_file():
        payload = json.loads(snippet.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            raw = payload.get("company_ids") or []
        else:
            raw = payload
        return sorted(str(cid) for cid in raw if str(cid).strip())
    return sorted(CANONICAL_NO_VISA_SPONSOR_COMPANY_IDS)
