#!/usr/bin/env python3
"""Network connectivity monitor for hub discovery pause/resume."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone

class HubNetworkPauseError(Exception):
    """Raised when global network pause triggers mid-fetch; retry hub from start."""


_NETWORK_ERROR_MARKERS = (
    "connection refused",
    "timed out",
    "timeout was reached",
    "could not resolve",
    "name or service not known",
    "network is unreachable",
    "no route to host",
    "failed to connect",
    "unable to connect",
    "nodename nor servname",
    "curl: (6)",
    "curl: (7)",
    "curl: (28)",
    "curl: (52)",
    "curl: (56)",
)

_DEFAULT_PROBE_URL = "https://www.google.com/generate_204"
_DEFAULT_PROBE_HOST = "1.1.1.1"


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 120) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_waf_block(code: int, body: str = "") -> bool:
    """HTTP 403 (or similar) with a response body is WAF/bot block, not transport loss."""
    if code not in (401, 403, 503):
        return False
    return bool(str(body or "").strip())


def is_network_error(code: int, body: str = "") -> bool:
    """True for transport failures (599), not HTTP responses like 403 WAF."""
    if is_waf_block(code, body):
        return False
    if code != 599:
        return False
    err = str(body or "").lower()
    if not err.strip():
        return True
    return any(marker in err for marker in _NETWORK_ERROR_MARKERS)


def probe_connectivity(
    *,
    timeout: int = 8,
    probe_url: str = "",
) -> bool:
    """Lightweight connectivity check (URL first, then ICMP to 1.1.1.1)."""
    url = (probe_url or os.environ.get("QUICKJOBS_HUB_PROBE_URL") or _DEFAULT_PROBE_URL).strip()
    if url:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "--max-time",
                str(timeout),
                url,
            ],
            capture_output=True,
            timeout=timeout + 5,
        )
        if proc.returncode == 0:
            code = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
            if code.isdigit() and int(code) < 500:
                return True
    host = os.environ.get("QUICKJOBS_HUB_PROBE_HOST", _DEFAULT_PROBE_HOST).strip() or _DEFAULT_PROBE_HOST
    ping = subprocess.run(
        ["ping", "-c", "1", "-W", str(max(1, timeout // 2)), host],
        capture_output=True,
        timeout=timeout + 5,
    )
    return ping.returncode == 0


class NetworkMonitor:
    """Pause hub HTTP work after consecutive transport failures until connectivity returns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consecutive = 0
        self._paused = False
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._pause_thread: threading.Thread | None = None

    def failure_threshold(self) -> int:
        return _env_int("QUICKJOBS_HUB_NET_FAIL_THRESHOLD", 3, minimum=2, maximum=20)

    def poll_seconds(self) -> float:
        return float(_env_int("QUICKJOBS_HUB_NET_POLL_SEC", 10, minimum=3, maximum=120))

    def wait_before_fetch(self) -> None:
        self._resume_event.wait()

    def record_fetch_result(self, code: int, body: str = "") -> None:
        with self._lock:
            if is_network_error(code, body):
                self._consecutive += 1
                if self._consecutive >= self.failure_threshold():
                    if probe_connectivity():
                        # Transport errors are site-specific; general connectivity is OK.
                        self._consecutive = 0
                    elif not self._paused:
                        self._enter_pause_locked()
            elif code != 599:
                self._consecutive = 0

    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def _enter_pause_locked(self) -> None:
        self._paused = True
        self._resume_event.clear()
        print(
            f"[{_ts()}] Network connectivity lost "
            f"({self._consecutive} consecutive transport failures); pausing discovery…",
            flush=True,
        )
        if self._pause_thread is None or not self._pause_thread.is_alive():
            self._pause_thread = threading.Thread(
                target=self._pause_loop,
                name="hub-network-pause",
                daemon=True,
            )
            self._pause_thread.start()

    def _pause_loop(self) -> None:
        poll = self.poll_seconds()
        while True:
            if probe_connectivity():
                with self._lock:
                    self._consecutive = 0
                    self._paused = False
                    self._resume_event.set()
                print(
                    f"[{_ts()}] Network connectivity restored; resuming discovery…",
                    flush=True,
                )
                return
            print(
                f"[{_ts()}] Still offline; retrying connectivity probe in {int(poll)}s…",
                flush=True,
            )
            time.sleep(poll)


_MONITOR = NetworkMonitor()


def wait_before_fetch() -> None:
    _MONITOR.wait_before_fetch()


def record_fetch_result(code: int, body: str = "") -> None:
    _MONITOR.record_fetch_result(code, body)


def network_paused() -> bool:
    return _MONITOR.paused()


def wait_until_resumed() -> None:
    """Block until connectivity monitor clears a global pause."""
    _MONITOR.wait_before_fetch()


def note_fetch_result(code: int, body: str = "", *, url: str = "") -> None:
    """Record fetch outcome; raise HubNetworkPauseError if global pause just triggered."""
    record_fetch_result(code, body)
    if network_paused():
        raise HubNetworkPauseError(url or "network pause")
