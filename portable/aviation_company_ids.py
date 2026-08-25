#!/usr/bin/env python3
"""Aviation employer IDs for portable profile excludes (sector=aviation in base JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def aviation_company_ids_from_base(data: dict[str, Any]) -> list[str]:
    """Return sorted company ids with sector=aviation from a quickjobs base config."""
    return sorted(
        str(c["id"])
        for c in data.get("companies", [])
        if c.get("id") and str(c.get("sector") or "").lower() == "aviation"
    )


def load_aviation_company_ids(root: Path) -> list[str]:
    """Load canonical aviation excludes from config snippet or quickjobs.base.json."""
    snippet = root / "config" / "aviation-company-ids.json"
    if snippet.is_file():
        payload = json.loads(snippet.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            raw = payload.get("company_ids") or []
        else:
            raw = payload
        return sorted(str(cid) for cid in raw if str(cid).strip())

    companies_path = root / "quickjobs.companies.json"
    if companies_path.is_file():
        data = json.loads(companies_path.read_text(encoding="utf-8"))
        return aviation_company_ids_from_base(data)

    base_path = root / "quickjobs.base.json"
    if not base_path.is_file():
        return []
    data = json.loads(base_path.read_text(encoding="utf-8"))
    return aviation_company_ids_from_base(data)
