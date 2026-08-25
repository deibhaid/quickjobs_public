#!/usr/bin/env python3
"""Shared HTTP client for quickjobs hub discovery probes."""

from __future__ import annotations

import http.cookiejar
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import hub_network

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 35
MAX_BODY_BYTES = 400_000
MAX_429_RETRIES = 4
MAX_TRANSIENT_RETRIES = 4

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_HOST_LOCK = threading.Lock()
_HOST_LAST_REQUEST: dict[str, float] = {}
_HOST_LOCKS: dict[str, threading.Lock] = {}
_COOKIE_JARS: dict[str, http.cookiejar.CookieJar] = {}
_cookie_env = os.environ.get("QUICKJOBS_HUB_COOKIE_DIR", "").strip()
_COOKIE_DIR = (
    Path(_cookie_env).expanduser()
    if _cookie_env
    else Path.home() / ".cache" / "quickjobs" / "hub-cookies"
)


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 120) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def hub_delay_ms() -> int:
    return _env_int("QUICKJOBS_HUB_DELAY_MS", 750, minimum=0, maximum=30_000)


def hub_max_workers(default: int = 8) -> int:
    return _env_int("QUICKJOBS_HUB_MAX_WORKERS", default, minimum=1, maximum=64)


def transient_retry_count() -> int:
    return _env_int("QUICKJOBS_HUB_TRANSIENT_RETRIES", MAX_TRANSIENT_RETRIES, minimum=1, maximum=8)


def _transient_backoff_seconds(attempt: int) -> float:
    return min(2.0 ** attempt, 15.0)


def _finalize_fetch_result(code: int, body: str, *, url: str) -> None:
    """Per-curl retries are done; update global monitor and maybe pause."""
    hub_network.note_fetch_result(code, body, url=url)


def _host_key(url: str) -> str:
    return (urllib.parse.urlsplit(str(url or "")).hostname or "default").lower()


def careers_referer(seed_url: str, probe_url: str = "") -> str:
    """Corporate careers home URL for Referer when probing ATS sub-paths."""
    seed = str(seed_url or "").strip()
    if not seed:
        return ""
    parsed = urllib.parse.urlsplit(seed)
    if not parsed.scheme or not parsed.netloc:
        return seed
    probe = str(probe_url or "").strip()
    if not probe:
        return seed
    probe_host = (urllib.parse.urlsplit(probe).hostname or "").lower()
    seed_host = parsed.netloc.lower()
    if probe_host and probe_host != seed_host:
        return seed
    return seed


def _host_lock(host: str) -> threading.Lock:
    with _HOST_LOCK:
        lock = _HOST_LOCKS.get(host)
        if lock is None:
            lock = threading.Lock()
            _HOST_LOCKS[host] = lock
        return lock


def _throttle_host(host: str) -> None:
    delay_sec = hub_delay_ms() / 1000.0
    if delay_sec <= 0:
        return
    lock = _host_lock(host)
    with lock:
        now = time.monotonic()
        last = _HOST_LAST_REQUEST.get(host, 0.0)
        wait = delay_sec - (now - last)
        if wait > 0:
            time.sleep(wait)
        _HOST_LAST_REQUEST[host] = time.monotonic()


def _cookie_jar_for_host(host: str) -> http.cookiejar.CookieJar:
    with _HOST_LOCK:
        jar = _COOKIE_JARS.get(host)
        if jar is None:
            jar = http.cookiejar.CookieJar()
            _COOKIE_JARS[host] = jar
        return jar


def _cookie_file_for_host(host: str) -> Path:
    safe = re.sub(r"[^a-z0-9.-]+", "_", host.lower()).strip("_") or "default"
    _COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    return _COOKIE_DIR / f"{safe}.txt"


def _opener_for_host(host: str) -> urllib.request.OpenerDirector:
    jar = _cookie_jar_for_host(host)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _retry_after_seconds(headers: Any, attempt: int) -> float:
    retry_after = ""
    if headers is not None:
        retry_after = str(headers.get("Retry-After") or headers.get("retry-after") or "").strip()
    if retry_after.isdigit():
        return max(float(retry_after), 1.0)
    if retry_after:
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(retry_after)
            delta = dt.timestamp() - time.time()
            if delta > 0:
                return min(delta, 120.0)
        except (TypeError, ValueError, OverflowError):
            pass
    return min(2.0 ** attempt, 60.0)


def _build_headers(
    url: str,
    *,
    headers: dict[str, str] | None,
    referer: str,
) -> dict[str, str]:
    hdrs = dict(DEFAULT_HEADERS)
    if referer:
        hdrs["Referer"] = referer
        parsed_probe = urllib.parse.urlsplit(url)
        parsed_ref = urllib.parse.urlsplit(referer)
        if parsed_probe.netloc and parsed_ref.netloc:
            if parsed_probe.netloc.lower() == parsed_ref.netloc.lower():
                hdrs["Sec-Fetch-Site"] = "same-origin"
            else:
                hdrs["Sec-Fetch-Site"] = "cross-site"
    if headers:
        hdrs.update(headers)
    return hdrs


def http_get(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    referer: str = "",
    max_body: int = MAX_BODY_BYTES,
) -> tuple[int, str, str]:
    """GET with browser-like headers, per-host delay, cookies, and 429 backoff."""
    host = _host_key(url)
    hdrs = _build_headers(url, headers=headers, referer=referer)
    opener = _opener_for_host(host)
    last_code = 599
    last_url = url
    last_body = ""
    transient_limit = transient_retry_count()
    for transient in range(transient_limit):
        hub_network.wait_before_fetch()
        for attempt in range(MAX_429_RETRIES + 1):
            _throttle_host(host)
            req = urllib.request.Request(url, headers=hdrs)
            try:
                with opener.open(req, timeout=timeout) as resp:
                    body = resp.read(max_body).decode("utf-8", "replace")
                    code = resp.status
                    if code == 429 and attempt < MAX_429_RETRIES:
                        time.sleep(_retry_after_seconds(resp.headers, attempt))
                        continue
                    hub_network.record_fetch_result(code, body)
                    return code, resp.geturl(), body
            except urllib.error.HTTPError as exc:
                body = (exc.read(max_body) if exc.fp else b"").decode("utf-8", "replace")
                final = getattr(exc, "url", url) or url
                last_code, last_url, last_body = exc.code, final, body
                if exc.code == 429 and attempt < MAX_429_RETRIES:
                    time.sleep(_retry_after_seconds(exc.headers, attempt))
                    continue
                if hub_network.is_waf_block(exc.code, body):
                    hub_network.record_fetch_result(exc.code, body)
                    return exc.code, final, body
                if not hub_network.is_network_error(exc.code, body):
                    hub_network.record_fetch_result(exc.code, body)
                    return exc.code, final, body
                break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_code, last_url, last_body = 599, url, str(exc)
                break
        else:
            hub_network.record_fetch_result(last_code, last_body)
            return last_code, last_url, last_body
        if transient + 1 < transient_limit:
            time.sleep(_transient_backoff_seconds(transient))
            continue
        _finalize_fetch_result(last_code, last_body, url=url)
        return last_code, last_url, last_body
    return last_code, last_url, last_body


def http_post_json(
    url: str,
    payload: dict,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    referer: str = "",
) -> tuple[int, str]:
    import json

    host = _host_key(url)
    hdrs = _build_headers(url, headers=headers, referer=referer)
    hdrs["Content-Type"] = "application/json"
    hdrs["Accept"] = "application/json, text/javascript, */*; q=0.01"
    hdrs["Sec-Fetch-Dest"] = "empty"
    hdrs["Sec-Fetch-Mode"] = "cors"
    data = json.dumps(payload).encode()
    opener = _opener_for_host(host)
    last_code = 599
    last_body = ""
    transient_limit = transient_retry_count()
    for transient in range(transient_limit):
        hub_network.wait_before_fetch()
        for attempt in range(MAX_429_RETRIES + 1):
            _throttle_host(host)
            req = urllib.request.Request(url, data=data, method="POST", headers=hdrs)
            try:
                with opener.open(req, timeout=timeout) as resp:
                    body = resp.read(200_000).decode("utf-8", "replace")
                    code = resp.status
                    if code == 429 and attempt < MAX_429_RETRIES:
                        time.sleep(_retry_after_seconds(resp.headers, attempt))
                        continue
                    hub_network.record_fetch_result(code, body)
                    return code, body
            except urllib.error.HTTPError as exc:
                last_code = exc.code
                last_body = (exc.read(4000) if exc.fp else b"").decode("utf-8", "replace")
                if exc.code == 429 and attempt < MAX_429_RETRIES:
                    time.sleep(_retry_after_seconds(exc.headers, attempt))
                    continue
                if hub_network.is_waf_block(exc.code, last_body):
                    hub_network.record_fetch_result(exc.code, last_body)
                    return exc.code, last_body
                if not hub_network.is_network_error(exc.code, last_body):
                    hub_network.record_fetch_result(exc.code, last_body)
                    return exc.code, last_body
                break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_code, last_body = 599, str(exc)
                break
        else:
            hub_network.record_fetch_result(last_code, last_body)
            return last_code, last_body
        if transient + 1 < transient_limit:
            time.sleep(_transient_backoff_seconds(transient))
            continue
        _finalize_fetch_result(last_code, last_body, url=url)
        return last_code, last_body
    return last_code, last_body


def curl_base_args(*, timeout: int = DEFAULT_TIMEOUT, referer: str = "") -> list[str]:
    args = [
        "curl",
        "-sL",
        "--compressed",
        "--max-time",
        str(timeout),
        "-A",
        BROWSER_USER_AGENT,
        "-H",
        f"Accept: {DEFAULT_HEADERS['Accept']}",
        "-H",
        f"Accept-Language: {DEFAULT_HEADERS['Accept-Language']}",
        "-H",
        "Sec-Fetch-Dest: document",
        "-H",
        "Sec-Fetch-Mode: navigate",
        "-H",
        "Sec-Fetch-User: ?1",
        "-H",
        "Upgrade-Insecure-Requests: 1",
    ]
    if referer:
        args.extend(["-H", f"Referer: {referer}"])
    return args


def curl_fetch(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    referer: str = "",
    max_body: int = MAX_BODY_BYTES,
) -> tuple[int, str, str]:
    """curl fetch mirroring http_get semantics for discover/batch scripts."""
    host = _host_key(url)
    cookie_file = _cookie_file_for_host(host)
    last_code = 599
    last_url = url
    last_body = ""
    transient_limit = transient_retry_count()
    for transient in range(transient_limit):
        hub_network.wait_before_fetch()
        for attempt in range(MAX_429_RETRIES + 1):
            _throttle_host(host)
            proc = subprocess.run(
                [
                    *curl_base_args(timeout=timeout, referer=referer),
                    "-c",
                    str(cookie_file),
                    "-b",
                    str(cookie_file),
                    "-w",
                    "\n%{http_code}\n%{url_effective}",
                    url,
                ],
                capture_output=True,
                timeout=timeout + 10,
            )
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", errors="replace")
                last_code, last_url, last_body = 599, url, err
                break
            raw = proc.stdout or b""
            parts = raw.rsplit(b"\n", 2)
            if len(parts) == 3 and parts[1].strip().isdigit():
                code = int(parts[1].strip())
                final_url = parts[2].decode("utf-8", errors="replace").strip() or url
                body_raw = parts[0]
            elif len(parts) == 2 and parts[1].strip().isdigit():
                code = int(parts[1].strip())
                final_url = url
                body_raw = parts[0]
            else:
                code = 200
                final_url = url
                body_raw = raw
            if body_raw[:2] == b"\x1f\x8b":
                body = ""
            else:
                body = body_raw[:max_body].decode("utf-8", errors="replace")
            last_code, last_url, last_body = code, final_url, body
            if code == 429 and attempt < MAX_429_RETRIES:
                time.sleep(_retry_after_seconds(None, attempt))
                continue
            if hub_network.is_waf_block(code, body):
                hub_network.record_fetch_result(code, body)
                return code, final_url, body
            if not hub_network.is_network_error(code, body):
                hub_network.record_fetch_result(code, body)
                return code, final_url, body
            break
        else:
            hub_network.record_fetch_result(last_code, last_body)
            return last_code, last_url, last_body
        if transient + 1 < transient_limit:
            time.sleep(_transient_backoff_seconds(transient))
            continue
        _finalize_fetch_result(last_code, last_body, url=url)
        return last_code, last_url, last_body
    return last_code, last_url, last_body
