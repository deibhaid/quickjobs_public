#!/usr/bin/env python3
"""Rolling timestamped backups for quickjobs config JSON files."""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

BACKUP_ROOT = Path.home() / ".numbered_backups"
DEFAULT_RETENTION_DAYS = 7
_BACKUP_STAMP_RE = re.compile(r"^(.+)_(\d{1,2}\.\d{1,2}\.\d{4}_\d{2}:\d{2}:\d{2})$")


def _backup_stamp(now: datetime | None = None) -> str:
    ts = now or datetime.now()
    return f"{ts.month}.{ts.day}.{ts.year}_{ts.hour:02d}:{ts.minute:02d}:{ts.second:02d}"


def backup_dest_for(source: Path, *, now: datetime | None = None) -> Path:
    """Return the numbered-backup destination path for a source file."""
    path = source.resolve()
    rel = path.as_posix().lstrip("/")
    return BACKUP_ROOT / f"{rel}_{_backup_stamp(now)}"


def parse_backup_timestamp(filename: str) -> datetime | None:
    match = _BACKUP_STAMP_RE.match(filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(2), "%m.%d.%Y_%H:%M:%S")
    except ValueError:
        return None


def iter_backups(source: Path) -> list[Path]:
    """List existing backup snapshots for a source file (newest first)."""
    path = source.resolve()
    parent = BACKUP_ROOT / path.parent.as_posix().lstrip("/")
    if not parent.is_dir():
        return []
    matches = [p for p in parent.glob(f"{path.name}_*") if p.is_file()]
    matches.sort(
        key=lambda p: parse_backup_timestamp(p.name) or datetime.min,
        reverse=True,
    )
    return matches


def prune_old_backups(source: Path, *, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete backups older than retention_days. Returns count removed."""
    if retention_days < 1:
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for backup in iter_backups(source):
        stamped = parse_backup_timestamp(backup.name)
        if stamped is None or stamped >= cutoff:
            continue
        backup.unlink(missing_ok=True)
        removed += 1
    return removed


def rolling_backup(source: Path, *, retention_days: int = DEFAULT_RETENTION_DAYS) -> Path:
    """Copy source to ~/.numbered_backups and prune snapshots older than retention_days."""
    path = source.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    dest = backup_dest_for(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    prune_old_backups(path, retention_days=retention_days)
    return dest


def rolling_backup_bundle(
    base_path: Path,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> list[Path]:
    """Backup base settings and companies sidecar before a bundle write."""
    from config_bundle import companies_path_for_base

    saved = [rolling_backup(base_path, retention_days=retention_days)]
    companies_path = companies_path_for_base(base_path)
    if companies_path.is_file():
        saved.append(rolling_backup(companies_path, retention_days=retention_days))
    return saved
