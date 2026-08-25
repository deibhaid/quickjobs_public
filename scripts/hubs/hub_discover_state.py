#!/usr/bin/env python3
"""Checkpoint state for resumable hub ATS discovery runs."""

from __future__ import annotations

import json
import uuid
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hub_tools

STATE_FILENAME = "quickjobs-discover-run-state.json"


def state_path() -> Path:
    return hub_tools.report_path(STATE_FILENAME)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def discovery_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "careers_url": row.careers_url,
        "method": row.method,
        "status": row.status,
        "total_jobs": row.total_jobs,
        "keyword_hits": row.keyword_hits,
        "recommended_type": row.recommended_type,
        "apply": row.apply,
        "config_hint": row.config_hint,
        "url_tested": row.url_tested,
        "error": row.error,
        "notes": row.notes,
    }


def discovery_from_dict(data: dict[str, Any]) -> Any:
    from discover_hub_ats_paths import Discovery

    return Discovery(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
        careers_url=str(data.get("careers_url") or ""),
        method=str(data.get("method") or ""),
        status=str(data.get("status") or ""),
        total_jobs=str(data.get("total_jobs") or ""),
        keyword_hits=str(data.get("keyword_hits") or ""),
        recommended_type=str(data.get("recommended_type") or ""),
        apply=str(data.get("apply") or ""),
        config_hint=str(data.get("config_hint") or ""),
        url_tested=str(data.get("url_tested") or ""),
        error=str(data.get("error") or ""),
        notes=str(data.get("notes") or ""),
        tests=None,
    )


def run_params_from_args(args: Namespace) -> dict[str, Any]:
    from_deferred = args.from_deferred
    return {
        "workers": int(args.workers),
        "limit": int(args.limit),
        "offset": int(args.offset),
        "from_deferred": str(from_deferred) if from_deferred else "",
        "ids": str(args.ids or ""),
        "apply": bool(args.apply),
        "exclude_unresolved": bool(args.exclude_unresolved),
        "sync_hidden": bool(args.sync_hidden),
    }


def params_compatible(stored: dict[str, Any], args: Namespace) -> bool:
    current = run_params_from_args(args)
    for key in ("limit", "offset", "from_deferred", "ids", "apply"):
        if str(stored.get(key, "")) != str(current.get(key, "")):
            return False
    return True


def new_state(args: Namespace, *, total_hubs: int, hub_ids: list[str]) -> dict[str, Any]:
    now = _iso_now()
    return {
        "run_id": uuid.uuid4().hex[:12],
        "started_at": now,
        "updated_at": now,
        "total_hubs": total_hubs,
        "hub_ids": hub_ids,
        **run_params_from_args(args),
        "completed_ids": [],
        "in_progress_hub_id": "",
        "rows": [],
    }


def set_in_progress(state: dict[str, Any], hub_id: str) -> None:
    cid = str(hub_id or "").strip()
    state["in_progress_hub_id"] = cid
    if cid:
        uncomplete_hub(state, cid)


def clear_in_progress(state: dict[str, Any]) -> None:
    state["in_progress_hub_id"] = ""


def uncomplete_hub(state: dict[str, Any], hub_id: str) -> None:
    cid = str(hub_id or "").strip()
    if not cid:
        return
    completed = [x for x in (state.get("completed_ids") or []) if str(x) != cid]
    state["completed_ids"] = completed
    state["rows"] = [
        r for r in (state.get("rows") or []) if str(r.get("id") or "") != cid
    ]


def complete_hub(state: dict[str, Any], row: Any) -> None:
    append_result(state, row)
    clear_in_progress(state)


def remaining_hub_ids(state: dict[str, Any]) -> list[str]:
    completed = {str(x) for x in (state.get("completed_ids") or [])}
    out: list[str] = []
    for cid in state.get("hub_ids") or []:
        sid = str(cid)
        if sid not in completed:
            out.append(sid)
    in_progress = str(state.get("in_progress_hub_id") or "").strip()
    if in_progress and in_progress not in out:
        out.insert(0, in_progress)
    elif in_progress and in_progress in out:
        out.remove(in_progress)
        out.insert(0, in_progress)
    return out


def load_state() -> dict[str, Any] | None:
    path = state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _iso_now()
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def clear_state() -> None:
    path = state_path()
    if path.is_file():
        path.unlink()


def append_result(state: dict[str, Any], row: Any) -> None:
    cid = str(row.id)
    completed = list(state.get("completed_ids") or [])
    if cid not in completed:
        completed.append(cid)
    state["completed_ids"] = completed
    rows = [r for r in (state.get("rows") or []) if str(r.get("id") or "") != cid]
    rows.append(discovery_to_dict(row))
    state["rows"] = rows
