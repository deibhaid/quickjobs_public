#!/usr/bin/env python3
"""Auto-tune HTTP and Playwright worker counts from host RAM and CPU."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable

HTTP_CAP = 32
PW_CAP = 8


def detect_cpu_cores() -> int:
    return max(1, os.cpu_count() or 1)


def _read_linux_mem_kb(key: str) -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(f"{key}:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def detect_total_ram_bytes() -> int | None:
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return int(proc.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    if sys.platform.startswith("linux"):
        kb = _read_linux_mem_kb("MemTotal")
        return kb * 1024 if kb is not None else None
    return None


def detect_available_ram_bytes() -> int | None:
    if sys.platform.startswith("linux"):
        kb = _read_linux_mem_kb("MemAvailable")
        if kb is None:
            kb = _read_linux_mem_kb("MemFree")
        return kb * 1024 if kb is not None else None
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["vm_stat"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        page_size = 4096
        for line in proc.stdout.splitlines():
            if "page size of" in line:
                parts = line.split()
                for idx, part in enumerate(parts):
                    if part == "of" and idx + 1 < len(parts):
                        try:
                            page_size = int(parts[idx + 1])
                        except ValueError:
                            pass
                        break
        pages = 0
        for label in ("Pages free", "Pages inactive"):
            for line in proc.stdout.splitlines():
                if line.strip().startswith(label):
                    try:
                        pages += int(line.split(":")[1].strip().rstrip("."))
                    except (IndexError, ValueError):
                        pass
                    break
        return pages * page_size if pages else None
    return None


def _gib_from_bytes(value: int | None, *, fallback_gib: float = 8.0) -> float:
    if value is None or value <= 0:
        return fallback_gib
    return value / (1024**3)


def compute_workers(*, cores: int, ram_gib: float) -> tuple[int, int]:
    """Return (http_workers, playwright_workers) from host capacity."""
    cores = max(1, cores)
    ram_gib = max(0.5, ram_gib)

    if ram_gib < 8:
        playwright = 1 if ram_gib < 5 else 2
        http = 4
    elif ram_gib < 16:
        playwright = min(4, 2 + int((ram_gib - 8) / 4))
        http = min(8, max(6, cores))
    elif ram_gib < 32:
        playwright = 4
        http = min(12, max(8, cores))
    elif cores >= 8:
        playwright = min(6, max(4, cores // 2))
        http = min(16, max(12, cores))
    else:
        playwright = 4
        http = min(12, max(8, cores))

    return max(1, min(HTTP_CAP, http)), max(1, min(PW_CAP, playwright))


def _adjust_for_memory_pressure(
    http: int,
    playwright: int,
    *,
    available_gib: float,
    total_gib: float,
) -> tuple[int, int]:
    if total_gib <= 0:
        return http, playwright
    ratio = available_gib / total_gib
    if ratio < 0.25:
        http = max(2, http // 2)
        playwright = max(1, playwright // 2)
    elif ratio < 0.4:
        http = max(4, http - 2)
        playwright = max(1, playwright - 1)
    return http, playwright


def _env_unset(name: str) -> bool:
    return not os.environ.get(name, "").strip()


def _format_gib(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 0.05:
        return str(int(rounded))
    return f"{value:.1f}"


def apply_worker_env(
    *,
    detect_total: Callable[[], int | None] = detect_total_ram_bytes,
    detect_available: Callable[[], int | None] = detect_available_ram_bytes,
    detect_cores: Callable[[], int] = detect_cpu_cores,
    log: Callable[[str], None] = print,
) -> tuple[int, int]:
    """Set QUICKJOBS_* worker env vars when unset; log the effective values."""
    cores = detect_cores()
    total_bytes = detect_total()
    total_gib = _gib_from_bytes(total_bytes)

    http, playwright = compute_workers(cores=cores, ram_gib=total_gib)
    avail_bytes = detect_available()
    if avail_bytes is not None and total_bytes:
        http, playwright = _adjust_for_memory_pressure(
            http,
            playwright,
            available_gib=_gib_from_bytes(avail_bytes, fallback_gib=total_gib),
            total_gib=total_gib,
        )

    if _env_unset("QUICKJOBS_HTTP_WORKERS"):
        os.environ["QUICKJOBS_HTTP_WORKERS"] = str(http)
    else:
        http = int(os.environ["QUICKJOBS_HTTP_WORKERS"].strip())

    if _env_unset("QUICKJOBS_PLAYWRIGHT_WORKERS"):
        os.environ["QUICKJOBS_PLAYWRIGHT_WORKERS"] = str(playwright)
    else:
        playwright = int(os.environ["QUICKJOBS_PLAYWRIGHT_WORKERS"].strip())

    log(
        f"Workers: http×{http}, playwright×{playwright} "
        f"({cores} cores, {_format_gib(total_gib)} GiB RAM)"
    )
    return http, playwright
