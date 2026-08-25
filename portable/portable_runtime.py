#!/usr/bin/env python3
"""Portable quickjobs paths and venv re-exec (post-configure)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / "python_venv" / "bin" / "python"


def get_quickjobs_root() -> Path:
    """Portable package root; honors QUICKJOBS_ROOT when already set."""
    return Path(os.environ.get("QUICKJOBS_ROOT", str(ROOT))).resolve()


def run_cmd() -> str:
    """Command shown after configure (copy-paste friendly)."""
    return "python_venv/bin/python run.py"


def apply_portable_env() -> None:
    root = get_quickjobs_root()
    os.environ.setdefault("QUICKJOBS_ROOT", str(root))
    os.environ.setdefault("JOB_SEARCH_DIR", str(root / "cache" / "data"))
    os.environ.setdefault("QUICKJOBS_JOBS_DIR", str(root / "output"))
    os.environ.setdefault("QUICKJOBS_NO_REMOTE_SYNC", "1")


def ensure_venv_python() -> None:
    """Re-run this script under python_venv when it exists."""
    if not VENV_PY.is_file():
        print("Run configure.py first to create python_venv", file=sys.stderr)
        raise SystemExit(1)
    script = Path(sys.argv[0]).resolve()
    if Path(sys.executable).resolve() == VENV_PY.resolve():
        apply_portable_env()
        os.chdir(get_quickjobs_root())
        return
    env = os.environ.copy()
    apply_portable_env()
    env["QUICKJOBS_ROOT"] = str(get_quickjobs_root())
    os.chdir(get_quickjobs_root())
    os.execve(str(VENV_PY), [str(VENV_PY), str(script), *sys.argv[1:]], env)
