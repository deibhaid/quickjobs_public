#!/usr/bin/env python3
"""Run quickjobs with all paths confined to this directory (except resume input)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from portable_runtime import ROOT, apply_portable_env, ensure_venv_python
from worker_tuning import apply_worker_env

QUICKJOBS_PY = ROOT / "quickjobs.py"


def main() -> int:
    ensure_venv_python()
    apply_portable_env()
    apply_worker_env()
    os.environ["QUICKJOBS_STRICT"] = "1"
    os.environ["QUICKJOBS_PYTHON"] = sys.executable
    if not QUICKJOBS_PY.is_file():
        print(f"Missing {QUICKJOBS_PY}", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, str(QUICKJOBS_PY), *sys.argv[1:]], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
