#!/usr/bin/env python3
"""Load/save quickjobs base settings + companies catalog as split JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def companies_path_for_base(base_path: Path) -> Path:
    """Derive companies JSON path from a base config path."""
    name = base_path.name
    if name.endswith(".base.json"):
        return base_path.with_name(name[: -len(".base.json")] + ".companies.json")
    if name == "quickjobs.base.json":
        return base_path.with_name("quickjobs.companies.json")
    raise ValueError(f"Unrecognized base config filename: {base_path}")


def load_base_json(base_path: Path) -> dict[str, Any]:
    """Load base settings file only (may still contain legacy inline companies)."""
    data = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Base config root must be an object: {base_path}")
    return data


def load_companies_json(companies_path: Path) -> list[dict[str, Any]]:
    """Load companies list from the companies sidecar."""
    if not companies_path.is_file():
        return []
    data = json.loads(companies_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Companies config root must be an object: {companies_path}")
    companies = data.get("companies")
    if companies is None:
        return []
    if not isinstance(companies, list):
        raise RuntimeError(f"{companies_path}: companies must be a list")
    return [row for row in companies if isinstance(row, dict)]


def load_base_bundle(base_path: Path) -> dict[str, Any]:
    """Merge base settings with companies (sidecar preferred; inline legacy fallback)."""
    if not base_path.is_file():
        raise RuntimeError(f"Base config not found: {base_path}")
    data = load_base_json(base_path)
    legacy = data.pop("companies", None)
    companies_path = companies_path_for_base(base_path)
    sidecar = load_companies_json(companies_path) if companies_path.is_file() else []
    if sidecar:
        data["companies"] = sidecar
    elif isinstance(legacy, list) and legacy:
        data["companies"] = legacy
    else:
        raise RuntimeError(
            f"Config missing companies: neither {companies_path} nor inline companies in {base_path}"
        )
    return data


def save_base_bundle(base_path: Path, merged: dict[str, Any]) -> None:
    """Write base settings and companies to their respective files."""
    payload = dict(merged)
    companies = payload.pop("companies", [])
    if not isinstance(companies, list):
        raise RuntimeError("save_base_bundle: companies must be a list")
    companies_path = companies_path_for_base(base_path)
    base_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    companies_path.write_text(
        json.dumps({"companies": companies}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def validate_companies_list(
    companies: Any,
    *,
    path_label: str,
) -> list[str]:
    """Return validation issues for a companies array."""
    issues: list[str] = []
    if not isinstance(companies, list) or not companies:
        issues.append(f"{path_label}: companies must be a non-empty list")
        return issues
    seen: set[str] = set()
    for idx, row in enumerate(companies):
        if not isinstance(row, dict):
            issues.append(f"{path_label}: companies[{idx}] must be an object")
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            issues.append(f"{path_label}: companies[{idx}] missing id")
            continue
        if cid in seen:
            issues.append(f"{path_label}: duplicate company id: {cid}")
        seen.add(cid)
    return issues
