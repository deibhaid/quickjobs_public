#!/usr/bin/env python3
"""Optional Playwright fallback when curl/http probes are blocked."""

from __future__ import annotations

import os
import re
from typing import Any

import hub_http

BROWSER_USER_AGENT = hub_http.BROWSER_USER_AGENT
DEFAULT_VIEWPORT = {"width": 1440, "height": 2200}

_BOT_BLOCK_RE = re.compile(
    r"access denied|bot detected|captcha|cloudflare|akamai|perimeterx|"
    r"please enable javascript|unusual traffic|request blocked|"
    r"verify you are human|attention required",
    re.I,
)


def playwright_enabled() -> bool:
    raw = os.environ.get("QUICKJOBS_HUB_PLAYWRIGHT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def looks_like_bot_block(code: int, body: str) -> bool:
    text = str(body or "")
    if code in (401, 403):
        return True
    if code == 200 and len(text.strip()) < 200 and _BOT_BLOCK_RE.search(text):
        return True
    if code == 200 and _BOT_BLOCK_RE.search(text[:8000]):
        return True
    return False


def should_playwright_fallback(code: int, body: str) -> bool:
    if not playwright_enabled():
        return False
    text = str(body or "")
    if code in (401, 403):
        return True
    if code == 200 and len(text.strip()) < 200:
        return bool(_BOT_BLOCK_RE.search(text))
    if not text.strip() and code in (200, 401, 403, 503):
        return True
    return False


def playwright_fetch(
    url: str,
    *,
    referer: str = "",
    timeout_ms: int = 45_000,
) -> tuple[int, str, str]:
    """Load one URL in headless Chromium; returns (status, final_url, body)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return 599, url, "playwright not installed"

    status = 599
    final_url = url
    body = ""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport=DEFAULT_VIEWPORT,
                    user_agent=BROWSER_USER_AGENT,
                    locale="en-US",
                )
                page = context.new_page()
                if referer:
                    page.set_extra_http_headers({"Referer": referer})
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2500)
                final_url = page.url or url
                body = page.content()
                status = response.status if response is not None else 200
            finally:
                browser.close()
    except Exception as exc:
        return 599, url, str(exc)[:500]
    return status, final_url, body


def probe_icims_from_html(body: str, final_url: str) -> dict[str, Any] | None:
    import discover_career_endpoints as discover

    row = discover.probe_icims("_playwright", body, final_url)
    if not row or row.status not in ("ok", "empty"):
        return None
    return {
        "method": row.method,
        "status": row.status,
        "total_jobs": row.total_jobs,
        "config_hint": row.config_hint,
        "url_tested": row.url_tested,
    }
