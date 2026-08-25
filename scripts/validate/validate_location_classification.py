#!/usr/bin/env python3
"""Validate city/state vs multi-country location classification rules."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path


def _load_module(path: Path, name: str):
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    sys.modules[name] = mod
    with path.open(encoding="utf-8") as handle:
        exec(compile(handle.read(), str(path), "exec"), mod.__dict__)
    return mod


def _load_cfg() -> dict:
    candidates = [
        Path.home() / ".job_search/quickjobs/quickjobs/quickjobs.profile.json",
        Path(__file__).resolve().parents[2] / "quickjobs.profile.json",
    ]
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {"profile": {"home_zip": "00000", "local_radius_miles": 50}}


def _run_cases(mod, cfg: dict, label: str, cases: list[tuple[str, str, str]]) -> list[str]:
    failures: list[str] = []
    print(f"=== {label} ===")
    for location, default_loc, expected in cases:
        job_loc, _ = mod.classify_location_with_fallback(
            location, "us", default_loc, cfg
        )
        ok = job_loc == expected
        status = "ok" if ok else "FAIL"
        print(f"  [{status}] {location!r} default_loc={default_loc!r} -> {job_loc!r} (expected {expected!r})")
        if not ok:
            failures.append(f"{label}: {location!r} -> {job_loc!r}, expected {expected!r}")
    return failures


def _run_nationwide_us_remote_matrix(mod, path_name: str, cfg: dict) -> list[str]:
    from dataclasses import dataclass

    @dataclass
    class _NationwideJob:
        loc: str = "remote"
        loc_label: str | None = None
        meta: str = ""
        title: str = ""
        description_text: str = ""
        company_id: str = ""
        loc_verify: bool = False
        work_model: str | None = None

    failures: list[str] = []
    include_labels = [
        "Remote - US",
        "Remote - US: All locations",
        "Remote - US: All locations (may list states in JD)",
        "Remote US",
        "Remote - United States",
        "United States - Remote Opportunity",
        "Remote - USA",
        "United States - Remote",
        "United States (remote)",
        "U.S. (Remote)",
        "US Remote",
        "Remote, USA",
        "Remote, US",
        "Remote, United States",
        "-REMOTE, USA-",
        "Remote (United States)",
        "Remote (US)",
        "Remote (USA)",
        "USA, Remote",
        "US, Remote",
        "United States, Remote",
        "US - Remote",
        "USA - Remote",
        "United States - Remote",
        "Remote Nationwide",
    ]
    exclude_labels = [
        "Remote, OR",
        "Remote, CA",
        "Remote - CA",
        "Remote - NC",
        "Remote - Oregon only",
        "Remote in California only",
        "Remote - United Kingdom",
        "Remote, WA only",
        "Cupertino, CA (Remote)",
        "Remote - Poland",
        "United States",
        "Canada - Remote",
        "United Kingdom - Remote",
        "Remote - Canada",
        "Canada, United States",
        "Canada, United States, Remote",
        "Canada; United States",
        "United States; Canada",
        "United States, Canada",
        "US, Canada",
        "San Francisco / Remote",
        "Hybrid- Any Office (Fremont, CA, Salem, OR, or Pittsburgh, PA)",
    ]
    print(f"=== {path_name} (nationwide US remote matrix) ===")
    for label in include_labels:
        job = _NationwideJob(loc_label=label)
        ok = mod.job_is_nationwide_us_remote_unrestricted(job, cfg)
        status = "ok" if ok else "FAIL"
        print(f"  [{status}] include {label!r}")
        if not ok:
            failures.append(f"{path_name}: nationwide include {label!r}")
    for label in exclude_labels:
        job = _NationwideJob(loc_label=label)
        ok = not mod.job_is_nationwide_us_remote_unrestricted(job, cfg)
        status = "ok" if ok else "FAIL"
        print(f"  [{status}] exclude {label!r}")
        if not ok:
            failures.append(f"{path_name}: nationwide exclude {label!r}")
    bare_us_job = _NationwideJob(meta="Remote · Posted 2d ago", company_id="stripe")
    bare_intl_job = _NationwideJob(
        loc="remote-intl",
        meta="Remote · Posted 2d ago",
        company_id="shopify",
    )
    if not mod.job_is_nationwide_us_remote_unrestricted(bare_us_job, cfg):
        failures.append(f"{path_name}: bare Remote with US employer should qualify")
    else:
        print("  [ok] bare Remote with US employer qualifies")
    if mod.job_is_nationwide_us_remote_unrestricted(bare_intl_job, cfg):
        failures.append(f"{path_name}: remote-intl bare Remote should not qualify")
    else:
        print("  [ok] remote-intl bare Remote excluded")
    or_remote = _NationwideJob(loc_label="Remote, OR")
    if not mod.job_is_remote_workable_from_home(or_remote, cfg):
        failures.append(f"{path_name}: Remote, OR not remote-workable from home")
    elif mod.job_is_nationwide_us_remote_unrestricted(or_remote, cfg):
        failures.append(f"{path_name}: Remote, OR wrongly nationwide US remote")
    else:
        print("  [ok] Remote, OR is remote-from-home only, not nationwide US")
    pure_storage = _NationwideJob(
        loc="excluded",
        loc_label="Raleigh, North Carolina",
        description_text=(
            "Partner with Product Management and Global Field teams. "
            "Work from the Raleigh, NC office. #LI-ONSITE"
        ),
        company_id="purestorage",
    )
    if mod.job_is_nationwide_us_remote_unrestricted(pure_storage, cfg):
        failures.append(f"{path_name}: Pure Storage onsite Raleigh must not be nationwide US")
    else:
        print("  [ok] excluded onsite Raleigh (Global Field teams) not nationwide US")
    disney_onsite = _NationwideJob(
        loc="excluded",
        loc_label="Bristol, Connecticut, United States | New York, New York, United States",
        title="Sr. Database Engineer, Site Reliability",
        company_id="disney-it",
        work_model="in-office",
    )
    if mod.job_is_nationwide_us_remote(disney_onsite, cfg):
        failures.append(f"{path_name}: Disney Bristol/NY onsite must not be nationwide US")
    elif mod.job_is_remote_workable_from_home(disney_onsite, cfg):
        failures.append(f"{path_name}: Disney Bristol/NY onsite must not be remote-from-home")
    else:
        print("  [ok] Disney Bristol/NY in-person excluded is not remote US or remote-from-home")
    anduril_title = "Multinational Digital Infrastructure - Full Stack SW Eng. (US)"
    anduril_jd = (
        "global Maritime and AUKUS missions. "
        "Location: Ideally based in Washington, D.C. Open to remote."
    )
    anduril_dc = _NationwideJob(
        loc="excluded",
        loc_label="Washington, District of Columbia, United States",
        title=anduril_title,
        description_text=anduril_jd,
        company_id="andurilindustries",
    )
    if mod.job_is_nationwide_us_remote_unrestricted(anduril_dc, cfg):
        failures.append(f"{path_name}: Anduril DC site must not be nationwide US")
    else:
        print("  [ok] Anduril Washington DC site not nationwide US")
    anduril_remote_no_label = _NationwideJob(
        loc="remote",
        loc_label="",
        title=anduril_title,
        description_text=anduril_jd,
        company_id="andurilindustries",
    )
    if mod.job_is_nationwide_us_remote_unrestricted(anduril_remote_no_label, cfg):
        failures.append(
            f"{path_name}: Anduril DC must not be nationwide US via title/JD alone"
        )
    else:
        print("  [ok] Anduril title (US) + global JD prose not nationwide US")
    for label, note in (
        ("Washington, District of Columbia, United States", "DC"),
        ("Quonset, Rhode Island, United States", "Quonset RI"),
        ("Raleigh, North Carolina", "Raleigh NC"),
    ):
        if not mod.segment_names_city_state_site(label):
            failures.append(f"{path_name}: {note} full-state label must be city/state site")
        else:
            print(f"  [ok] {label!r} is city/state site")
    samsara = _NationwideJob(loc_label="Remote - CA", company_id="samsara")
    if mod.job_is_nationwide_us_remote_unrestricted(samsara, cfg):
        failures.append(f"{path_name}: Remote - CA must not be nationwide US")
    else:
        print("  [ok] Remote - CA excluded from nationwide US")
    samsara_jd = _NationwideJob(
        loc_label="Remote - CA",
        title="Engineer",
        description_text="Join our global team. Work from anywhere in the US.",
        company_id="samsara",
    )
    if mod.job_is_nationwide_us_remote_unrestricted(samsara_jd, cfg):
        failures.append(f"{path_name}: Remote - CA must not be nationwide US via JD global prose")
    else:
        print("  [ok] Remote - CA not promoted to nationwide US by JD global prose")
    remote_us = _NationwideJob(loc_label="Remote - US", company_id="samsara")
    if not mod.job_is_nationwide_us_remote_unrestricted(remote_us, cfg):
        failures.append(f"{path_name}: Remote - US must be nationwide US")
    else:
        print("  [ok] Remote - US qualifies as nationwide US")
    docker_us_ca = _NationwideJob(
        loc="remote",
        loc_label="Canada, United States, Remote",
        title="Principal Product Manager, Growth",
        company_id="docker",
    )
    if mod.job_is_nationwide_us_remote_unrestricted(docker_us_ca, cfg):
        failures.append(
            f"{path_name}: Docker Ashby Canada+US remote must not be nationwide US"
        )
    elif not mod.job_is_remote_workable_from_home(docker_us_ca, cfg):
        failures.append(
            f"{path_name}: Docker Ashby Canada+US remote must be remote-workable from US"
        )
    else:
        print("  [ok] Docker Ashby Canada+US is remote-workable but not nationwide US")
    for label in ("Canada; United States", "Canada, United States"):
        us_ca = _NationwideJob(loc="remote", loc_label=label, company_id="docker")
        if mod.job_is_nationwide_us_remote_unrestricted(us_ca, cfg):
            failures.append(
                f"{path_name}: {label!r} must not be nationwide US remote"
            )
        elif not mod.job_is_remote_workable_from_home(us_ca, cfg):
            failures.append(
                f"{path_name}: {label!r} must remain remote-workable from US"
            )
        else:
            print(f"  [ok] {label!r} remote-workable from US, not nationwide US")
    if mod.remote_scope_is_broad_us("partner with global field teams"):
        failures.append(f"{path_name}: global marketing prose must not be broad US remote")
    else:
        print("  [ok] global marketing prose alone is not broad US remote")
    if not mod.remote_scope_is_broad_us("join our global remote team"):
        print("  [ok] global remote marketing prose is not broad US remote")
    else:
        failures.append(f"{path_name}: global remote marketing prose must not be broad US remote")
    for label in (
        "Canada - Remote",
        "United Kingdom - Remote",
        "Remote - Canada",
        "San Francisco / Remote",
    ):
        if not mod.location_text_is_non_us_country_remote(label) and label.startswith(
            ("Canada", "United Kingdom", "Remote - Canada")
        ):
            failures.append(
                f"{path_name}: location_text_is_non_us_country_remote({label!r}) should be true"
            )
        elif mod.location_text_is_non_us_country_remote(label) and label.startswith(
            ("Canada", "United Kingdom", "Remote - Canada")
        ):
            print(f"  [ok] location_text_is_non_us_country_remote({label!r})")
    if mod.location_text_is_non_us_country_remote("Remote - US"):
        failures.append(f"{path_name}: Remote - US must not be non-US country remote")
    else:
        print("  [ok] Remote - US is not non-US country remote")
    jd_promotion_cases = [
        (
            "Canada - Remote",
            "remote",
            "Engineer",
            "Work from anywhere in the United States.",
            False,
        ),
        (
            "United Kingdom - Remote",
            "remote",
            "Engineer (US)",
            "Join our global remote team.",
            False,
        ),
        (
            "San Francisco / Remote",
            "remote",
            "Staff Engineer",
            "This role can be performed remotely anywhere in the United States.",
            False,
        ),
        (
            "Hybrid- Any Office (Fremont, CA, Salem, OR, or Pittsburgh, PA)",
            "excluded",
            "Robotics Engineer",
            "Work from anywhere in the US.",
            False,
        ),
    ]
    for label, loc, title, desc, want in jd_promotion_cases:
        job = _NationwideJob(
            loc=loc,
            loc_label=label,
            title=title,
            description_text=desc,
        )
        got = mod.job_is_nationwide_us_remote_unrestricted(job, cfg)
        ok = got == want
        status = "ok" if ok else "FAIL"
        print(f"  [{status}] JD block {label!r} title={title!r} -> {got} (expected {want})")
        if not ok:
            failures.append(
                f"{path_name}: JD promoted {label!r} to nationwide US remote"
            )
    if not mod.location_text_has_geographic_place("Raleigh, North Carolina"):
        failures.append(f"{path_name}: Raleigh, North Carolina must be geographic")
    else:
        print("  [ok] full US state name Raleigh, North Carolina is geographic")
    anduril_title = "Multinational Digital Infrastructure - Full Stack SW Eng. (US)"
    for label, note in (
        ("Washington, District of Columbia, United States", "DC onsite"),
        ("Quonset, Rhode Island, United States", "Quonset RI onsite"),
    ):
        job = _NationwideJob(
            loc="excluded",
            loc_label=label,
            title=anduril_title,
            company_id="andurilindustries",
        )
        if mod.job_is_nationwide_us_remote_unrestricted(job, cfg):
            failures.append(f"{path_name}: Anduril {note} must not be nationwide US")
        else:
            print(f"  [ok] Anduril {note} (City, State, United States) not nationwide US")
    title_only_us = _NationwideJob(
        loc="excluded",
        loc_label="Quonset, Rhode Island, United States",
        title=anduril_title,
        company_id="andurilindustries",
    )
    if mod.job_is_nationwide_us_remote_unrestricted(title_only_us, cfg):
        failures.append(f"{path_name}: title (US) suffix must not promote onsite to nationwide US")
    else:
        print("  [ok] title (US) suffix alone does not promote onsite to nationwide US")
    excluded_jd_remote = _NationwideJob(
        loc="excluded",
        loc_label=None,
        description_text=(
            "Work from our Quonset office. Open to remote candidates anywhere in the United States."
        ),
        company_id="andurilindustries",
    )
    if mod.job_is_nationwide_us_remote_unrestricted(excluded_jd_remote, cfg):
        failures.append(f"{path_name}: excluded onsite must not be promoted by JD remote-US prose")
    else:
        print("  [ok] excluded onsite not promoted to nationwide US by JD remote-US prose")
    return failures


def _run_nus_implies_remote_from_home(mod, path_name: str, cfg: dict) -> list[str]:
    """Nationwide US remote must always qualify as remote-workable from home (OR)."""
    from dataclasses import dataclass

    @dataclass
    class _NationwideJob:
        loc: str = "remote"
        loc_label: str | None = None
        meta: str = ""
        title: str = ""
        description_text: str = ""
        company_id: str = ""
        loc_verify: bool = False
        work_model: str | None = None

    failures: list[str] = []
    print(f"=== {path_name} (nationwide US remote ⊆ remote-from-home) ===")
    cases = [
        _NationwideJob(loc_label="Remote - US", company_id="samsara"),
        _NationwideJob(loc="excluded", loc_label="Remote", title="IT Systems Engineer"),
        _NationwideJob(loc="remote", loc_label="Remote, United States"),
    ]
    for job in cases:
        if not mod.job_is_nationwide_us_remote(job, cfg):
            continue
        if mod.job_is_remote_workable_from_home(job, cfg):
            print(f"  [ok] nationwide US remote also remote-from-home: {job.loc_label!r}")
        else:
            failures.append(
                f"{path_name}: nationwide US remote must be remote-from-home ({job.loc_label!r})"
            )
    return failures


_MATCH_TIER_RANK = {"strong": 3, "good": 2, "stretch": 1}


def _strictest_match_tier(keys: list[str]) -> str | None:
    best: str | None = None
    best_rank = 0
    for key in keys:
        rank = _MATCH_TIER_RANK.get(key, 0)
        if rank > best_rank:
            best_rank = rank
            best = key
    return best


def _legend_entry_matches_loc_key(entry: dict, key: str, flag) -> bool:
    loc = entry.get("loc") or ""
    wm = str(entry.get("wm") or "").strip().lower()
    if key in {"remote", "remote-from-home"}:
        if wm in {"in-office", "onsite", "on-site"}:
            return False
        if loc == "excluded":
            if not (flag(entry, "nus") or flag(entry, "rfh")):
                if (entry.get("ll") or "").strip():
                    return False
    if key == "remote":
        return flag(entry, "nus")
    if key == "remote-from-home":
        return flag(entry, "rfh")
    if key == "local":
        return loc == "local"
    if key == "remote-intl":
        return loc == "remote-intl"
    return False


def _legend_entry_matches_match_keys(entry: dict, match_keys: list[str], *, mode: str) -> bool:
    if not match_keys:
        return True
    tier = entry.get("match") or "good"
    if mode == "and":
        strictest = _strictest_match_tier(match_keys)
        return tier == strictest if strictest else True
    return any(tier == key for key in match_keys)


def _legend_entry_matches_loc_keys(entry: dict, loc_keys: list[str], *, mode: str, flag) -> bool:
    if not loc_keys:
        return True
    if mode == "and":
        return all(_legend_entry_matches_loc_key(entry, key, flag) for key in loc_keys)
    return any(_legend_entry_matches_loc_key(entry, key, flag) for key in loc_keys)


def _legend_entry_matches_keys(entry: dict, keys: list[str], *, mode: str, flag) -> bool:
    match_keys = [k for k in keys if k in {"strong", "good", "stretch"}]
    loc_keys = [k for k in keys if k not in match_keys]
    return _legend_entry_matches_match_keys(entry, match_keys, mode=mode) and _legend_entry_matches_loc_keys(
        entry, loc_keys, mode=mode, flag=flag
    )


def _run_legend_and_filter_and_logic(cfg: dict) -> list[str]:
    """Board index: unified legend OR/AND — location AND/OR, match AND strictest."""
    import json
    import re

    failures: list[str] = []
    print("=== legend filter combine logic (board index) ===")

    if not _legend_entry_matches_match_keys({"match": "strong"}, ["strong", "good"], mode="and"):
        failures.append("legend match AND: strong+good must accept strong entries")
    elif _legend_entry_matches_match_keys({"match": "good"}, ["strong", "good"], mode="and"):
        failures.append("legend match AND: strong+good must reject good-only entries")
    else:
        print("  [ok] match AND strictest: strong+good → strong only")

    if not _legend_entry_matches_match_keys({"match": "good"}, ["strong", "good"], mode="or"):
        failures.append("legend match OR: strong+good must accept good entries")
    else:
        print("  [ok] match OR: strong+good accepts good entries")

    jobs_dir = Path(cfg.get("profile", {}).get("jobs_dir", "~/Downloads/jobs")).expanduser()
    board_path = jobs_dir / "job-search-quickjobs.html"
    if not board_path.is_file():
        print(f"  [skip] no board at {board_path}")
        return failures
    text = board_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'id="lazy-board-data"[^>]*>(\{.*?\})</script>', text, re.DOTALL)
    if not match:
        failures.append("legend filter: board missing lazy-board-data")
        return failures
    entries = json.loads(match.group(1)).get("index", [])
    if not entries:
        failures.append("legend filter: board index empty")
        return failures

    def flag(entry: dict, key: str) -> bool:
        val = entry.get(key)
        return val is True or val in (1, "1")

    def in_pool(entry: dict, *, show_all: bool) -> bool:
        pool = entry.get("pool") or ""
        if pool == "applied":
            return False
        if show_all:
            return pool in {"listings", "excluded", "pass"}
        if pool != "listings":
            return False
        loc = entry.get("loc") or ""
        return loc in {"remote", "remote-intl", "local"} or flag(entry, "rfh") or flag(
            entry, "nus"
        )

    def count_visible(keys: list[str], *, mode: str = "and") -> int:
        total = 0
        for entry in entries:
            if not in_pool(entry, show_all=True):
                continue
            if _legend_entry_matches_keys(entry, keys, mode=mode, flag=flag):
                total += 1
        return total

    nus_rfh = count_visible(["remote", "remote-from-home"], mode="and")
    all_three = count_visible(["local", "remote", "remote-from-home"], mode="and")
    remote_or_local = count_visible(["remote", "local"], mode="or")
    remote_and_local = count_visible(["remote", "local"], mode="and")
    strong_good_and = count_visible(["strong", "good"], mode="and")
    strong_only = count_visible(["strong"], mode="or")
    print(
        f"  [info] board entries: {len(entries)} · nus∩rfh: {nus_rfh} · "
        f"local∩nus∩rfh: {all_three} · remote|local: {remote_or_local} · remote&local: {remote_and_local}"
    )
    if nus_rfh <= 0:
        failures.append("legend AND location: nus ∩ remote-from-home must be non-zero on board index")
    else:
        print(f"  [ok] nus ∩ remote-from-home is non-zero ({nus_rfh})")
    if all_three != 0:
        failures.append(
            f"legend AND location: local ∩ nus ∩ remote-from-home must be empty, got {all_three}"
        )
    else:
        print("  [ok] local ∩ nus ∩ remote-from-home is empty (mutually exclusive)")
    if remote_or_local < remote_and_local:
        failures.append(
            f"legend OR location: remote|local ({remote_or_local}) must be >= remote&local ({remote_and_local})"
        )
    else:
        print(f"  [ok] location OR is at least as broad as AND ({remote_or_local} >= {remote_and_local})")
    if strong_good_and != strong_only:
        failures.append(
            f"legend AND match: strong+good ({strong_good_and}) must equal strong-only ({strong_only})"
        )
    else:
        print(f"  [ok] match AND strictest on board index ({strong_good_and} strong jobs)")
    return failures


def _run_eightfold_posting_url_cases(mod) -> list[str]:
    failures: list[str] = []
    cases = [
        (
            "https://careers.dexcom.com",
            "41059351",
            "https://careers.dexcom.com/careers?pid=41059351&sort_by=timestamp",
        ),
        (
            "https://careers.hasbro.com",
            "12345",
            "https://careers.hasbro.com/careers?pid=12345&sort_by=timestamp",
        ),
        (
            "https://careers.ptc.com/",
            "999",
            "https://careers.ptc.com/careers?pid=999&sort_by=timestamp",
        ),
        (
            "https://citi.eightfold.ai/careers?domain=citi.com",
            "555",
            "https://citi.eightfold.ai/careers?pid=555&sort_by=timestamp",
        ),
        (
            "https://careers.lamresearch.com/careers?start=0&sort_by=timestamp",
            "777",
            "https://careers.lamresearch.com/careers?pid=777&sort_by=timestamp",
        ),
    ]
    print("=== eightfold_posting_url ===")
    for browse_url, pid, expected in cases:
        got = mod.eightfold_posting_url(browse_url, pid)
        ok = got == expected
        status = "ok" if ok else "FAIL"
        print(f"  [{status}] {browse_url!r} pid={pid} -> {got!r}")
        if not ok:
            failures.append(
                f"eightfold_posting_url: {browse_url!r} -> {got!r}, expected {expected!r}"
            )

    print("=== job_url_shape_valid (eightfold /careers) ===")
    dexcom = {"type": "playwright", "playwright_kind": "eightfold", "eightfold_fetch": "pcsx"}
    shape_cases = [
        (
            "https://careers.dexcom.com/careers?pid=41059351&sort_by=timestamp",
            True,
        ),
        (
            "https://careers.dexcom.com?pid=41059351&sort_by=timestamp",
            False,
        ),
        (
            "https://careers.dexcom.com/careers?start=0&pid=41516419&sort_by=hot",
            True,
        ),
    ]
    for url, expected in shape_cases:
        got = mod.job_url_shape_valid(url, dexcom)
        ok = got == expected
        status = "ok" if ok else "FAIL"
        print(f"  [{status}] {url!r} -> {got!r} (expected {expected!r})")
        if not ok:
            failures.append(
                f"job_url_shape_valid eightfold: {url!r} -> {got!r}, expected {expected!r}"
            )
    return failures


def main() -> int:
    root = Path(__file__).resolve().parent
    cfg = _load_cfg()
    common_cases = [
        ("San Francisco, CA (Hybrid)", "", "excluded"),
        ("San Francisco, CA (Hybrid)", "remote", "excluded"),
        ("Austin, TX", "remote", "excluded"),
        ("United States, Canada", "", "remote"),
        ("United States, Canada", "remote", "remote"),
        ("Canada; United States", "", "remote"),
        ("Canada, United States, Remote", "", "remote"),
        ("United States, United Kingdom", "", "remote"),
        ("Portland, OR", "remote", "local"),
        ("London, UK", "remote", "excluded"),
        ("San Francisco, CA, United States", "remote", "excluded"),
        (
            "Mountain View, CA, USA ; San Francisco, CA, USA ; Remote",
            "",
            "excluded",
        ),
        (
            "MOUNTAIN VIEW, CALIFORNIA, UNITED STATES | SAN FRANCISCO, CALIFORNIA, UNITED STATES",
            "",
            "excluded",
        ),
        ("Remote - US", "", "remote"),
        ("US-Remote", "local", "remote"),
        ("Greenville, TX", "remote", "excluded"),
        ("Greenville, TX", "", "excluded"),
    ]
    nvidia_cases = [
        ("US, NC, Remote", "", "excluded"),
        ("US, CA, Santa Clara", "", "excluded"),
        ("US, OR, Hillsboro", "", "local"),
        ("US, CA, Santa Clara; US, NC, Remote", "", "excluded"),
        (
            "US, CA, Santa Clara US, TX, Austin US, NC, Remote US, TX, Remote US, NY, Remote US, NC, Durham",
            "",
            "excluded",
        ),
        ("US, CA, Santa Clara; US, TX, Austin; US, NC, Durham", "", "excluded"),
        ("US, WA, Remote; US, TX, Remote; US, Remote", "", "remote"),
        (
            "US, CA, Santa Clara; US, CA, Remote; US, WA, Remote",
            "",
            "excluded",
        ),
        ("US, NC, Remote; US, OR, Remote", "", "remote"),
        ("US, OR, Remote", "", "remote"),
    ]
    nvidia_ca_cases = [
        (
            "US, CA, Santa Clara; US, CA, Remote; US, WA, Remote",
            "",
            "remote",
        ),
    ]
    talentbrew_cases = [
        ("New York, New York, United States", "remote", "excluded"),
        ("Glendale, CA & Bristol, CT", "remote", "excluded"),
        ("Product Software Engineer II", "remote", "excluded"),
        ("", "remote", "remote"),
    ]
    datadog_loc = (
        "California, USA, Remote; Massachusetts, USA, Remote; "
        "New York, New York, USA; New York, USA, Remote; "
        "Texas, USA, Remote; Washington, USA, Remote"
    )
    datadog_cases = [
        (datadog_loc, "", "excluded"),
        (datadog_loc, "remote", "excluded"),
    ]
    sanitize_cases = [
        ("Rehovot,ISR You'll benefit from a supportive work culture", "", "Rehovot, IL"),
        ("Hybrid", "", ""),
        ("Live posting (Workday)", "", ""),
        ("PERM - N/A", "", ""),
        ("PERM - N/A", "Software Engineer", ""),
        ("Senior DevOps Engineer", "", ""),
        (
            "B-dul 21 Decembrie 1989 No. 77 Building D-E-F, The Office, 400604 Cluj-Napoca, Romania",
            "",
            "Cluj-Napoca, Romania",
        ),
        ("Mumbai,IND You will benefit from learning", "", "Mumbai, IN"),
        ("Remote, US", "", ""),
        ("REMOTE, US", "", ""),
        ("Remote US", "", ""),
        ("US Remote", "", ""),
        ("Remote, United States", "", ""),
        ("Remote · US", "", ""),
        ("United States - Remote", "", ""),
        ("United States - Remote Opportunity", "", ""),
        ("Remote Opportunity", "", ""),
        ("US", "", ""),
        ("USA", "", ""),
        ("United States", "", ""),
        ("United States (remote)", "", ""),
        ("Remote - USA", "", ""),
        ("Remote (U.S.)", "", ""),
        ("San Francisco Bay Area or Remote (U.S.)", "", "Bay Area"),
        ("Remote, OR", "", "Remote, OR"),
        ("Waymo Mountain View, CA", "", "Mountain View, CA", "Waymo"),
    ]
    sanitize_desc_cases = [
        (
            "Clackamas, Clackamas",
            "",
            "Primary Location Clackamas, Oregon Facility Name Kaiser Sunnyside Medical Center",
            "Clackamas, OR",
        ),
        (
            "Clackamas, Clackamas, OR, Flexible, Full-time, Day",
            "",
            "Primary Location Clackamas, Oregon Facility Name Kaiser Sunnyside Medical Center",
            "Clackamas, OR",
        ),
    ]
    abbrev_cases = [
        (
            "United States / San Diego, California / Washington, DC / Boston, MA",
            "US\nSan Diego, CA\nDC\nBoston, MA",
        ),
        ("Work at Home, Florida, United States", "Work at Home, FL, US"),
        ("Boston, MA", "Boston, MA"),
        ("New York, NY", "New York, NY"),
        ("New York, New York", "New York, NY"),
        ("USA - Seal Beach, CA", "Seal Beach, CA"),
        ("USA - HAZELWOOD, MO", "HAZELWOOD, MO"),
        ("USA – Berkeley, MO", "Berkeley, MO"),
        ("United States - Everett, WA", "Everett, WA"),
        (
            "USA - Hazelwood, MO / USA - Seal Beach, CA",
            "Hazelwood, MO\nSeal Beach, CA",
        ),
        ("GBR - RAF Lossiemouth, UK", "RAF Lossiemouth, UK"),
        ("DE - Berlin, Germany", "Berlin, Germany"),
        ("FR - Paris, France", "Paris, FR"),
        ("CAN - Toronto, ON", "Toronto, ON"),
        ("San Francisco, California", "San Francisco, CA"),
        ("Mountain View, California, United States", "Mountain View, CA"),
        ("Waymo Mountain View, CA", "Mountain View, CA", "Waymo"),
        ("Seattle, Washington", "Seattle, WA"),
        ("Toronto, Canada", "Toronto, Canada"),
        ("Toronto, Ontario", "Toronto, ON"),
        ("Calgary, Alberta", "Calgary, AB"),
        ("Vancouver, British Columbia", "Vancouver, BC"),
        ("United States / Canada", "US\nCA"),
        ("Canada", "CA"),
        ("United Kingdom", "UK"),
        ("London, United Kingdom", "London, UK"),
        ("Mumbai, India", "Mumbai, India"),
        ("400604 Cluj-Napoca, Romania", "Cluj-Napoca, Romania"),
        ("Germany", "DE"),
        ("Paris, France", "Paris, FR"),
        ("Singapore", "SG"),
        ("Netherlands", "NL"),
        ("Tokyo, Japan", "Tokyo, JP"),
        ("", ""),
        (
            "Clackamas, Clackamas, OR, Flexible, Full-time, Day",
            "Clackamas, OR",
        ),
    ]
    ibm_cases = [
        ("Singapore, SG", "", "excluded"),
        ("Pune, IN", "", "excluded"),
        ("Tucson, AZ", "", "excluded"),
        ("TUCSON, US", "", "excluded"),
        ("Markham, Toronto, ON, Canada", "", "excluded"),
        ("Multiple Cities", "", "excluded"),
        (
            "Poughkeepsie | Lowell | Rochester | Tucson | Research Triangle Park | Armonk | Durham | Raleigh",
            "",
            "excluded",
        ),
    ]
    ibm_sanitize_cases = [
        ("TUCSON, Arizona, United States", "", "Tucson, AZ"),
        ("Singapore, Central Singapore, Singapore", "", "Singapore, Central Singapore"),
        ("Markham, Toronto, Ontario, Canada", "", "Markham, Toronto"),
        (
            "Poughkeepsie | Lowell | Rochester | Tucson | Research Triangle Park | Armonk | Durham | Raleigh",
            "",
            "Poughkeepsie | Lowell | Rochester | Tucson | Research Triangle Park | Armonk | Durham | Raleigh",
        ),
        ("Multiple Cities", "", "Multiple Cities"),
        ("TUCSON, US", "", "Tucson, US"),
    ]
    ibm_abbrev_cases = [
        ("Tucson, AZ", "Tucson, AZ"),
        ("Markham, Toronto, ON, Canada", "Markham, Toronto, ON, Canada"),
        ("Singapore, SG", "Singapore"),
        (
            "Poughkeepsie | Lowell | Rochester | Tucson",
            "Poughkeepsie\nLowell\nRochester\nTucson",
        ),
    ]
    failures: list[str] = []
    for script_name, mod_name in (
        ("quickjobs.py", "validate_qj"),
        ("../job-board/job_board.py", "validate_jb"),
    ):
        path = (root / script_name).resolve()
        if not path.is_file():
            print(f"=== skip {script_name} (not present) ===")
            continue
        mod = _load_module(path, mod_name)
        failures.extend(_run_cases(mod, cfg, path.name, common_cases))
        if script_name == "quickjobs.py":
            failures.extend(_run_eightfold_posting_url_cases(mod))
            failures.extend(_run_cases(mod, cfg, f"{path.name} (NVIDIA/Workday)", nvidia_cases))
            ca_cfg = {
                "profile": {
                    **cfg.get("profile", {}),
                    "home_zip": "94043",
                    "home_state": "CA",
                }
            }
            failures.extend(
                _run_cases(
                    mod,
                    ca_cfg,
                    f"{path.name} (NVIDIA/Workday, CA profile)",
                    nvidia_ca_cases,
                )
            )
            failures.extend(
                _run_cases(
                    mod,
                    cfg,
                    f"{path.name} (Talentbrew/Disney location)",
                    talentbrew_cases,
                )
            )
            failures.extend(
                _run_cases(
                    mod,
                    cfg,
                    f"{path.name} (Datadog/Greenhouse multi-loc)",
                    datadog_cases,
                )
            )
            failures.extend(
                _run_cases(
                    mod,
                    cfg,
                    f"{path.name} (IBM location)",
                    ibm_cases,
                )
            )
            for raw, title, expected in ibm_sanitize_cases:
                got = mod.sanitize_loc_label_for_badge(
                    raw, title=title, company_name="IBM"
                )
                if got != expected:
                    failures.append(
                        f"{path.name}: IBM sanitize {raw!r} -> {got!r}, expected {expected!r}"
                    )
            print(f"=== {path.name} (IBM abbreviate_location_label) ===")
            for case in ibm_abbrev_cases:
                raw = case[0]
                expected = case[1]
                got = mod.abbreviate_location_label(raw, company_name="IBM")
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: IBM abbreviate {raw!r} -> {got!r}, expected {expected!r}"
                    )
            ibm_resolve_samples = [
                (
                    "TUCSON, Arizona, United States",
                    "City / Township / Village\nTUCSON\nState / Province\nArizona\nCountry\nUnited States\nWork arrangement\nOnsite",
                    "",
                    "Tucson, AZ",
                ),
                (
                    "Markham, Toronto, Ontario, Canada",
                    "City / Township / Village\nMarkham, Toronto\nState / Province\nOntario\nCountry\nCanada\nWork arrangement\nRemote",
                    "",
                    "Markham, Toronto, ON, Canada",
                ),
                (
                    "",
                    "City / Township / Village\nSingapore\nState / Province\nCentral Singapore\nCountry\nSingapore\nWork arrangement\nOnsite",
                    "Singapore, SG",
                    "Singapore, Central Singapore, SG",
                ),
            ]
            print(f"=== {path.name} (ibm_resolve_location) ===")
            for header, desc, card, expected in ibm_resolve_samples:
                got = mod.ibm_resolve_location(header, desc, card_location=card)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: ibm_resolve_location -> {got!r}, expected {expected!r}"
                    )
            if mod.ibm_workplace_mode_from_text(
                "City / Township / Village\nTUCSON\nWork arrangement\nOnsite"
            ) != "in-office":
                failures.append(f"{path.name}: ibm_workplace_mode_from_text Onsite failed")
            if mod.ibm_workplace_mode_from_text(
                "Work arrangement\nRemote"
            ) != "remote":
                failures.append(f"{path.name}: ibm_workplace_mode_from_text Remote failed")
            if mod.ibm_workplace_mode_from_text(
                "Work arrangement\nHybrid"
            ) != "hybrid":
                failures.append(f"{path.name}: ibm_workplace_mode_from_text Hybrid failed")
            # Title-as-location must never classify as local
            title_loc, _ = mod.classify_location_with_fallback(
                "Product Software Engineer II",
                "us",
                "local",
                cfg,
            )
            if title_loc == "local":
                failures.append(
                    f"{path.name}: job title misread as local location"
                )
            path_loc, _ = mod.classify_location_with_fallback(
                mod.talentbrew_loc_from_path(
                    "/job/glendale/product-software-engineer-ii/391/123456"
                ),
                "us",
                "remote",
                cfg,
            )
            if path_loc != "excluded":
                failures.append(
                    f"{path.name}: talentbrew path slug -> {path_loc!r}, expected 'excluded'"
                )
            if mod.location_text_looks_like_job_title("Product Software Engineer II") is not True:
                failures.append(f"{path.name}: title guard failed for engineer title")
            if mod.location_text_looks_like_job_title("Glendale, CA") is not False:
                failures.append(f"{path.name}: title guard false-positive on Glendale, CA")
            for case in sanitize_cases:
                raw = case[0]
                title = case[1]
                expected = case[2]
                company_name = case[3] if len(case) > 3 else ""
                got = mod.sanitize_loc_label_for_badge(
                    raw, title=title, company_name=company_name
                )
                if got != expected:
                    failures.append(
                        f"{path.name}: sanitize {raw!r} -> {got!r}, expected {expected!r}"
                    )
            for raw, title, description, expected in sanitize_desc_cases:
                got = mod.sanitize_loc_label_for_badge(
                    raw, title=title, description_text=description
                )
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(
                    f"  [{status}] sanitize+desc {raw!r} -> {got!r} (expected {expected!r})"
                )
                if not ok:
                    failures.append(
                        f"{path.name}: sanitize+desc {raw!r} -> {got!r}, expected {expected!r}"
                    )
            print(f"=== {path.name} (abbreviate_location_label) ===")
            for case in abbrev_cases:
                raw = case[0]
                expected = case[1]
                company_name = case[2] if len(case) > 2 else ""
                got = mod.abbreviate_location_label(raw, company_name=company_name)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: abbreviate {raw!r} -> {got!r}, expected {expected!r}"
                    )
            if mod.infer_work_model("Hybrid", "", "") != "hybrid":
                failures.append(f"{path.name}: infer_work_model Hybrid failed")
            if mod.infer_work_model("Austin, TX", "This is a hybrid role.", "") != "hybrid":
                failures.append(f"{path.name}: infer_work_model hybrid JD failed")
            if mod.infer_work_model("Remote - US", "", "") != "remote":
                failures.append(f"{path.name}: infer_work_model remote failed")
            if mod.infer_work_model("Austin, TX", "", "") != "in-office":
                failures.append(f"{path.name}: infer_work_model US city onsite default failed")
            if mod.infer_work_model("London, UK", "", "") != "in-office":
                failures.append(f"{path.name}: infer_work_model UK onsite default failed")
            if mod.infer_work_model("Seattle, WA (Hybrid)", "", "") != "hybrid":
                failures.append(f"{path.name}: infer_work_model hybrid paren failed")
            if (
                mod.infer_work_model("San Francisco Bay Area or Remote (U.S.)", "", "")
                != "hybrid"
            ):
                failures.append(
                    f"{path.name}: infer_work_model geo-or-remote hybrid failed"
                )
            if mod.infer_work_model("Remote (U.S.)", "", "") != "remote":
                failures.append(f"{path.name}: infer_work_model Remote (U.S.) failed")
            if (
                mod.infer_work_model(
                    "Mountain View, California, United States",
                    "This role may allow partial telecommuting and remote work across US locations.",
                    "Software Engineer",
                )
                != "in-office"
            ):
                failures.append(
                    f"{path.name}: infer_work_model city onsite beats JD remote hint failed"
                )
            if mod.infer_work_model(datadog_loc, "", "") != "hybrid":
                failures.append(
                    f"{path.name}: infer_work_model Datadog mixed remote/onsite failed"
                )
            if mod.location_text_is_remote_us_nationwide(datadog_loc):
                failures.append(
                    f"{path.name}: Datadog multi-loc misread as nationwide remote US"
                )
            datadog_abbrev = mod.abbreviate_location_label(datadog_loc)
            datadog_abbrev_want = (
                "Remote, CA\nRemote, MA\nNew York, NY\nRemote, NY\nRemote, TX\nRemote, WA"
            )
            if datadog_abbrev != datadog_abbrev_want:
                failures.append(
                    f"{path.name}: Datadog abbreviate -> {datadog_abbrev!r}, expected {datadog_abbrev_want!r}"
                )
            if mod.greenhouse_url_slug_to_us_location(
                "https://careers.withwaymo.com/jobs/software-engineer-mountain-view-california-united-states-8eb1fde0-f8e6-437e-b3f0-183ecaac01cb"
            ) != "Mountain View, California":
                failures.append(f"{path.name}: greenhouse_url_slug_to_us_location Waymo failed")
            waymo_jd = (
                "Position reports to the Waymo Mountain View, CA office & may allow for partial telecommuting."
            )
            if mod.greenhouse_onsite_hint_from_description(waymo_jd) != "Waymo Mountain View, CA":
                failures.append(f"{path.name}: greenhouse_onsite_hint_from_description raw capture failed")
            resolved = mod.greenhouse_resolve_location(
                "PERM - N/A",
                "https://careers.withwaymo.com/jobs/software-engineer-mountain-view-california-united-states-14476eac-7685-45ca-b5eb-f35640a695cd",
                "",
                company_name="Waymo",
            )
            if resolved != "Mountain View, California":
                failures.append(
                    f"{path.name}: greenhouse_resolve_location PERM Waymo -> {resolved!r}, expected 'Mountain View, California'"
                )
            resolved_jd = mod.greenhouse_resolve_location(
                "PERM - N/A",
                "",
                f"<p>{waymo_jd}</p>",
                company_name="Waymo",
            )
            if resolved_jd != "Mountain View, CA":
                failures.append(
                    f"{path.name}: greenhouse_resolve_location PERM JD Waymo -> {resolved_jd!r}, expected 'Mountain View, CA'"
                )
            print(f"=== {path.name} (badge work-model / loc split) ===")
            from dataclasses import dataclass

            @dataclass
            class _BadgeJob:
                loc: str
                loc_label: str | None = None
                work_model: str | None = None
                title: str = ""
                description_text: str = ""
                meta: str = ""
                loc_verify: bool = False
                posted_ts: int | None = None

            badge_matrix = [
                (_BadgeJob("remote", "Remote - US"), "", "Remote US"),
                (_BadgeJob("remote", "Remote - USA"), "", "Remote US"),
                (_BadgeJob("remote", "Remote, US"), "", "Remote US"),
                (_BadgeJob("remote", "Remote, United States"), "", "Remote US"),
                (_BadgeJob("remote", "Remote · US"), "", "Remote US"),
                (_BadgeJob("remote", "US", meta="US · Posted 2d ago"), "", "In Person"),
                (_BadgeJob("remote", "USA", meta="USA · Posted 2d ago"), "", "In Person"),
                (
                    _BadgeJob(
                        "remote",
                        "United States - Remote Opportunity",
                        meta="United States - Remote Opportunity · Posted 2d ago",
                    ),
                    "",
                    "Remote US",
                ),
                (_BadgeJob("remote", "United States (remote)"), "", "Remote US"),
                (_BadgeJob("remote", "Remote (U.S.)"), "", "Remote US"),
                (_BadgeJob("remote", "Remote, OR"), "Remote, OR", "Remote"),
                (
                    _BadgeJob(
                        "remote",
                        "San Francisco Bay Area or Remote (U.S.)",
                        work_model="hybrid",
                        meta="San Francisco Bay Area or Remote (U.S.) · Posted 2d ago",
                        posted_ts=1_700_000_000,
                    ),
                    "Bay Area",
                    "Hybrid",
                ),
                (_BadgeJob("excluded", "Seattle, WA (Hybrid)", work_model="hybrid"), "Seattle, WA", "Hybrid"),
                (_BadgeJob("excluded", "London, UK"), "London, UK", "In Person"),
                (_BadgeJob("excluded", "Austin, TX"), "Austin, TX", "In Person"),
                (
                    _BadgeJob(
                        "excluded",
                        "Remote-Friendly (Travel-Required) | San Francisco, CA | Seattle, WA | New York, NY",
                        work_model="hybrid",
                    ),
                    "San Francisco, CA",
                    "Hybrid",
                ),
                (
                    _BadgeJob(
                        "excluded",
                        datadog_loc,
                        work_model="hybrid",
                    ),
                    "New York, NY",
                    "Hybrid",
                ),
            ]
            for job, want_loc_substr, want_work in badge_matrix:
                loc_html = mod.badge_loc(job, "")
                work_html = mod.badge_work_model(job)
                loc_ok = (not want_loc_substr and not loc_html) or (
                    want_loc_substr and want_loc_substr in loc_html
                )
                work_ok = want_work in work_html
                status = "ok" if loc_ok and work_ok else "FAIL"
                print(
                    f"  [{status}] loc={job.loc!r} label={job.loc_label!r} "
                    f"loc_badge={loc_html!r} work={work_html!r}"
                )
                if not loc_ok:
                    failures.append(
                        f"{path.name}: badge_loc {job.loc_label!r} missing {want_loc_substr!r} in {loc_html!r}"
                    )
                if not work_ok:
                    failures.append(
                        f"{path.name}: badge_work_model {job.loc_label!r} expected {want_work!r} in {work_html!r}"
                    )
            meta_job = _BadgeJob(
                "remote",
                "United States - Remote Opportunity",
                meta="United States - Remote Opportunity · Posted 2d ago",
                posted_ts=1_700_000_000,
            )
            meta_plain = mod.format_job_card_meta(meta_job)
            if not meta_plain.startswith("Posted"):
                failures.append(
                    f"{path.name}: format_job_card_meta {meta_job.loc_label!r} -> {meta_plain!r}, expected posted date only"
                )
            else:
                print(f"  [ok] meta={meta_plain!r}")
            flex_meta_job = _BadgeJob(
                "remote",
                "US",
                meta="US · Posted 2d ago",
                posted_ts=1_700_000_000,
            )
            flex_meta = mod.format_job_card_meta(flex_meta_job)
            if not flex_meta.startswith("Posted"):
                failures.append(
                    f"{path.name}: format_job_card_meta bare US -> {flex_meta!r}, expected posted date only"
                )
            else:
                print(f"  [ok] flex meta={flex_meta!r}")
            hybrid_meta_job = _BadgeJob(
                "remote",
                "San Francisco Bay Area or Remote (U.S.)",
                work_model="hybrid",
                meta="San Francisco Bay Area or Remote (U.S.) · Posted 2d ago",
                posted_ts=1_700_000_000,
            )
            hybrid_meta = mod.format_job_card_meta(hybrid_meta_job)
            if not hybrid_meta.startswith("Posted"):
                failures.append(
                    f"{path.name}: format_job_card_meta hybrid -> {hybrid_meta!r}, expected posted date only"
                )
            else:
                print(f"  [ok] hybrid meta={hybrid_meta!r}")
            slash_job = _BadgeJob(
                "excluded",
                "New York, NY / Sunnyvale, CA / Bellevue, WA",
            )
            slash_lines = mod.stacked_location_lines(slash_job.loc_label or "")
            slash_want = ["New York, NY", "Sunnyvale, CA", "Bellevue, WA"]
            if slash_lines != slash_want:
                failures.append(
                    f"{path.name}: stacked slash multi-loc -> {slash_lines!r}, expected {slash_want!r}"
                )
            else:
                print(f"  [ok] slash stacked={slash_lines!r}")
            stripe_segments = mod.split_location_display_segments(
                "Remote-Friendly (Travel-Required) | San Francisco, CA | Seattle, WA | New York, NY"
            )
            stripe_want = ["San Francisco, CA", "Seattle, WA", "New York, NY"]
            if stripe_segments != stripe_want:
                failures.append(
                    f"{path.name}: stripe split -> {stripe_segments!r}, expected {stripe_want!r}"
                )
            else:
                print(f"  [ok] stripe segments={stripe_segments!r}")
            print(f"=== {path.name} (location QC regressions) ===")
            github_job = _BadgeJob(
                "remote",
                None,
                meta="United States · GitHub Actions / CI platform",
                title="Staff Software Engineer, GitHub Actions",
            )
            if mod.job_is_nationwide_us_remote(github_job):
                failures.append(f"{path.name}: GitHub bare United States misread as nationwide remote US")
            elif "Remote US" in mod.badge_work_model(github_job):
                failures.append(f"{path.name}: GitHub bare United States shows Remote US work-model badge")
            else:
                print("  [ok] GitHub bare United States does not show Remote US")
            agility_loc = "Hybrid- Any Office (Fremont, CA, Salem, OR, or Pittsburgh, PA)"
            agility_sanitized = mod.sanitize_loc_label_for_badge(agility_loc)
            agility_want = "Fremont, CA\nSalem, OR\nPittsburgh, PA"
            if agility_sanitized != agility_want:
                failures.append(
                    f"{path.name}: Agility hybrid-any-office sanitize -> {agility_sanitized!r}, expected {agility_want!r}"
                )
            else:
                print(f"  [ok] Agility hybrid-any-office -> {agility_sanitized!r}")
            if mod.infer_work_model(agility_loc) != "hybrid":
                failures.append(f"{path.name}: Agility hybrid-any-office work model not hybrid")
            else:
                print("  [ok] Agility hybrid-any-office work model hybrid")
            netflix_job = _BadgeJob(
                "remote",
                None,
                meta="JR38079 · USA - Remote · Posted Mar 23, 2026",
                title="Engineering Manager",
            )
            if not mod.job_is_nationwide_us_remote(netflix_job):
                failures.append(f"{path.name}: Netflix USA - Remote not nationwide remote US")
            elif "Remote US" not in mod.badge_work_model(netflix_job):
                failures.append(f"{path.name}: Netflix USA - Remote missing Remote US badge")
            else:
                print("  [ok] Netflix USA - Remote shows Remote US")
            wwr_cases = [
                ("PREMIERSOFT", ""),
                ("ASSURESOFT", ""),
                ("HYBRID WORK ARRANGEMENT WITH FLEXIBLE SCHEDULE", ""),
                ("Full-time", ""),
                ("AUSTIN, BEAVERTON", "Austin\nBeaverton"),
                ("Austin, TX, Beaverton, OR", "Austin, TX\nBeaverton, OR"),
            ]
            for raw, expected in wwr_cases:
                got = mod.sanitize_loc_label_for_badge(raw)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] WWR sanitize {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: WWR sanitize {raw!r} -> {got!r}, expected {expected!r}"
                    )
            if mod.location_text_is_remote_us_nationwide("United States"):
                failures.append(f"{path.name}: bare United States misread as nationwide remote US")
            else:
                print("  [ok] bare United States is not nationwide remote US")
            print(f"=== {path.name} (location display fixes) ===")
            display_cases = [
                ("Bangalore,IND", "Bangalore, IN"),
                ("Bangalore, IND", "Bangalore, IN"),
                ("SINGAPORE, SG", "Singapore"),
                ("SINGAPORE,SG", "Singapore"),
                ("OFFICE BASED - TAIPEI, TP", "Taipei"),
                ("HOME BASED - EMEA", "EMEA"),
                ("INTL REMOTE", ""),
                ("Remote Nationwide", ""),
                ("Remote, Nationwide", ""),
            ]
            for raw, expected in display_cases:
                got = mod.sanitize_loc_label_for_badge(raw)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] sanitize {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: display sanitize {raw!r} -> {got!r}, expected {expected!r}"
                    )
            work_model_cases = [
                ("OFFICE BASED - TAIPEI, TP", "in-office"),
                ("HOME BASED - EMEA", "remote"),
                ("INTL REMOTE", "remote"),
                ("Remote Nationwide", "remote"),
            ]
            for raw, expected in work_model_cases:
                got = mod.infer_work_model(raw)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] work_model {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: work_model {raw!r} -> {got!r}, expected {expected!r}"
                    )
            nationwide_job = _BadgeJob(
                "remote",
                None,
                meta="Remote Nationwide · Posted 2d ago",
                posted_ts=1_700_000_000,
            )
            nationwide_excluded = _BadgeJob(
                "excluded",
                "Remote, Nationwide",
                work_model="remote",
                posted_ts=1_700_000_000,
            )
            if not mod.job_is_nationwide_us_remote(nationwide_job):
                failures.append(f"{path.name}: Remote Nationwide not nationwide remote US")
            else:
                print("  [ok] Remote Nationwide is nationwide remote US")
            nationwide_loc_html = mod.badge_loc(nationwide_job, "")
            if "US</span>" not in nationwide_loc_html:
                failures.append(
                    f"{path.name}: Remote Nationwide loc badge -> {nationwide_loc_html!r}, expected US"
                )
            else:
                print(f"  [ok] Remote Nationwide loc badge shows US: {nationwide_loc_html!r}")
            if "Remote US" not in mod.badge_work_model(nationwide_job):
                failures.append(f"{path.name}: Remote Nationwide missing Remote US work-model badge")
            else:
                print("  [ok] Remote Nationwide shows Remote US work-model badge")
            excl_loc = mod.badge_loc(nationwide_excluded, "")
            if "US</span>" not in excl_loc:
                failures.append(
                    f"{path.name}: excluded Remote, Nationwide loc badge -> {excl_loc!r}, expected US"
                )
            else:
                print(f"  [ok] excluded Remote, Nationwide loc badge shows US")
            if "Remote US" not in mod.badge_work_model(nationwide_excluded):
                failures.append(f"{path.name}: excluded Remote, Nationwide missing Remote US work-model badge")
            else:
                print("  [ok] excluded Remote, Nationwide shows Remote US work-model badge")
            or_remote_job = _BadgeJob("remote", "Remote, OR")
            ca_only_job = _BadgeJob("excluded", "Remote in California only")
            intl_only_job = _BadgeJob("remote-intl", "Remote - United Kingdom")
            intl_us_job = _BadgeJob(
                "remote-intl",
                "Remote US",
                meta="Remote US · Posted 2d ago",
            )
            nationwide_remote_job = _BadgeJob("remote", "Remote Nationwide")
            if not mod.job_is_remote_workable_from_home(or_remote_job, cfg):
                failures.append(f"{path.name}: Remote, OR not remote-workable from home")
            else:
                print("  [ok] Remote, OR is remote-workable from home")
            if mod.job_is_remote_workable_from_home(ca_only_job, cfg):
                failures.append(f"{path.name}: CA-only remote wrongly remote-workable from home")
            else:
                print("  [ok] CA-only remote excluded from remote-workable from home")
            if mod.job_is_remote_workable_from_home(intl_only_job, cfg):
                failures.append(f"{path.name}: UK-only intl remote wrongly remote-workable from home")
            else:
                print("  [ok] UK-only intl remote excluded from remote-workable from home")
            if not mod.job_is_remote_workable_from_home(intl_us_job, cfg):
                failures.append(f"{path.name}: intl employer Remote US not remote-workable from home")
            else:
                print("  [ok] intl employer Remote US is remote-workable from home")
            if not mod.job_is_remote_workable_from_home(nationwide_remote_job, cfg):
                failures.append(f"{path.name}: Remote Nationwide not remote-workable from home")
            else:
                print("  [ok] Remote Nationwide is remote-workable from home")
            if mod.profile_context(cfg).get("remote_from_home_label") != "Remote from Oregon":
                failures.append(
                    f"{path.name}: remote_from_home_label "
                    f"{mod.profile_context(cfg).get('remote_from_home_label')!r}, expected Remote from Oregon"
                )
            else:
                print("  [ok] remote_from_home_label is Remote from Oregon for 00000 profile")
            failures.extend(_run_nationwide_us_remote_matrix(mod, path.name, cfg))
            failures.extend(_run_nus_implies_remote_from_home(mod, path.name, cfg))
            print(f"=== {path.name} (location audit normalization) ===")
            audit_sanitize_cases = [
                ("gb", "", "UK"),
                ("SG", "", "Singapore"),
                ("Ka", "", "Karnataka"),
                ("IN, KA", "", "IN, Karnataka"),
                ("400604 Cluj-Napoca, RO", "", "Cluj-Napoca, RO"),
                ("Ljubljana, SI", "", "Ljubljana, SI"),
                ("United States of America", "", "US"),
                (
                    "Bengaluru, Karnātaka, India, 560066",
                    "",
                    "Bengaluru, Karnātaka, IN",
                ),
                ("Remote - Canada", "", "Canada"),
                ("Remote - Poland", "", "Poland"),
                ("Remote - SF Bay Area", "", "Bay Area"),
                ("Netherlands (remote)", "", "Netherlands"),
                ("Virtual, WA", "", "WA"),
                ("-REMOTE, BULGARIA-", "", "Bulgaria"),
                ("Work at Home, RI", "", "RI"),
                ("Hybrid - San Francisco, New York City", "", "San Francisco\nNew York City"),
                ("Hybrid-San Diego, CA", "", "San Diego, CA"),
                ("San, CA", "", "San Francisco, CA"),
                ("O Fallon, US", "", "O'Fallon, MO"),
                ("California - San Francisco", "", "San Francisco, CA"),
                ("Headquarters/Sunnyvale Office", "", "Sunnyvale, CA"),
                ("San Francisco HQ", "", "San Francisco, CA"),
                ("TX-Dallas - Fort Worth (DFW) Airport", "", "Dallas, TX"),
                ("Wilsonville - Oregon", "", "Wilsonville, OR"),
                ("Poznań, PL, 61-569", "", "Poznań, PL"),
                ("Israel - Office - Tel Aviv", "", "Tel Aviv, Israel"),
                ("Israel-Tel-Aviv Yafo Office", "", "Tel Aviv, Israel"),
                ("Amsterdam, North Holland", "", "Amsterdam, Netherlands"),
                (
                    "Kuala Lumpur, Federal Territory of Kuala Lumpur",
                    "",
                    "Kuala Lumpur",
                ),
                (
                    "2090 Parkway Office Circle, Hoover, AL 35244, US",
                    "",
                    "Hoover, AL",
                ),
                ("Austin, New York City", "", "Austin\nNew York City"),
                ("United States, Canada", "", "US\nCA"),
                (
                    "['Austin, US'] Career Site Department: ['Engineering']",
                    "",
                    "Austin, US",
                ),
                (
                    "{'displayName': 'Seattle, WA'}",
                    "",
                    "Seattle, WA",
                ),
                ("Headquarters (Lehi, UT)", "", "Lehi, UT"),
                ("06500 Mexico City, MX", "", "Mexico City, MX"),
                ("AMERICAS", "", "US"),
                ("br", "", "BR"),
                ("RA - Sao Jose dos Campos, BR", "", "Sao Jose dos Campos, BR"),
                ("Branch 26J Hattiesburg, MS1", "", "Hattiesburg, MS"),
                ("Branch 627 Mobile, AL", "", "Mobile, AL"),
                ("Branch BAA Columbia, MS", "", "Columbia, MS"),
                ("Branch D23 Gulfport, MS", "", "Gulfport, MS"),
                ("Branch L41 Flowood, MS", "", "Flowood, MS"),
                (
                    "1000 Nicollet Mall, Minneapolis, MN 55403-2542",
                    "",
                    "Minneapolis, MN",
                ),
                (
                    "1180 West Peachtree St. NW, Atlanta, GA 30309, US",
                    "",
                    "Atlanta, GA",
                ),
                ("151 Farmington Avenue, Hartford, CT", "", "Hartford, CT"),
                (
                    "16070 Leeland Rd, Upper Marlboro, MD 20774-8528",
                    "",
                    "Marlboro, MD",
                ),
                ("161 Avenue of the Americas, New York, NY", "", "New York, NY"),
                (
                    "1900 5th Avenue North, Birmingham, AL 35203, US",
                    "",
                    "Birmingham, AL",
                ),
                (
                    "19500 E. 23Rd Avenue, AURORA, CO 80011, US",
                    "",
                    "Aurora, CO",
                ),
                ("2000 16th St, Denver, CO 80202-5117", "", "Denver, CO"),
                (
                    "2240 Outer Loop, LOUISVILLE, KY 40219, US",
                    "",
                    "Louisville, KY",
                ),
                ("2535 Gomez Ave, OMAHA, NE 68107, US", "", "Omaha, NE"),
                (
                    "2855 E Lone Mountain Road, NORTH LAS VEGAS, NV 89081, US",
                    "",
                    "Las Vegas, NV",
                ),
                (
                    "305 South Bullard Avenue, GOODYEAR, AZ 85338, US",
                    "",
                    "Goodyear, AZ",
                ),
                ("3600 Minnesota Drive, Edina, MN 55435, US", "", "Edina, MN"),
                ("2200 Viking Rd, Cedar Falls, IA 50613-9526", "", "Cedar Falls, IA"),
                ("22 Corporate Drive, Lugoff, SC 29078-8767", "", "Lugoff, SC"),
                (
                    "Canberra, Australian Capital Territory",
                    "",
                    "Canberra, AU",
                ),
                ("CHEK LAP KOK, Hong Kong SAR", "", "HK"),
                (
                    "CHEUNG SHA WAN, Hong Kong SAR",
                    "",
                    "Cheung Sha Wan, Hong Kong SAR",
                ),
            ]
            audit_sanitize_desc_cases = [
                (
                    "multiple locations",
                    "",
                    "Available locations: San Diego, California; Atlanta, Georgia; "
                    "Mountain View, California; New York, New York.",
                    "San Diego, CA\nAtlanta, GA\nMountain View, CA\nNew York, NY",
                ),
                (
                    "Remote - Canada: Select locations",
                    "",
                    "Hiring in Alberta, British Columbia, Ontario, and Saskatchewan.",
                    "Canada\nAlberta\nBritish Columbia\nOntario\nSaskatchewan",
                ),
            ]
            audit_work_model_cases = [
                ("Remote - Canada", "remote"),
                ("Remote - Poland", "remote"),
                ("Remote - SF Bay Area", "remote"),
                ("Netherlands (remote)", "remote"),
                ("Virtual, WA", "remote"),
                ("-REMOTE, BULGARIA-", "remote"),
                ("Work at Home, RI", "remote"),
                ("Hybrid - San Francisco, New York City", "hybrid"),
                ("Hybrid", "hybrid"),
                ("Hybrid-San Diego, CA", "hybrid"),
            ]
            audit_abbrev_cases = [
                ("United States, Canada", "US\nCA"),
                ("Remote - Canada", "Canada"),
                ("Poznań, PL, 61-569", "Poznań, PL"),
                ("400604 Cluj-Napoca, Romania", "Cluj-Napoca, Romania"),
                ("400604 Cluj-Napoca, RO", "Cluj-Napoca, RO"),
                ("AMERICAS", "US"),
                ("br", "BR"),
                ("Headquarters (Lehi, UT)", "Lehi, UT"),
                (
                    "1000 Nicollet Mall, Minneapolis, MN 55403-2542",
                    "Minneapolis, MN",
                ),
                ("Branch 26J Hattiesburg, MS1", "Hattiesburg, MS"),
            ]
            for raw, title, expected in audit_sanitize_cases:
                got = mod.sanitize_loc_label_for_badge(raw, title=title)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] audit sanitize {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: audit sanitize {raw!r} -> {got!r}, expected {expected!r}"
                    )
            for raw, title, description, expected in audit_sanitize_desc_cases:
                got = mod.sanitize_loc_label_for_badge(
                    raw, title=title, description_text=description
                )
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(
                    f"  [{status}] audit sanitize+desc {raw!r} -> {got!r} (expected {expected!r})"
                )
                if not ok:
                    failures.append(
                        f"{path.name}: audit sanitize+desc {raw!r} -> {got!r}, expected {expected!r}"
                    )
            for raw, expected in audit_work_model_cases:
                got = mod.infer_work_model(raw)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] audit work_model {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: audit work_model {raw!r} -> {got!r}, expected {expected!r}"
                    )
            for raw, expected in audit_abbrev_cases:
                got = mod.abbreviate_location_label(raw)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] audit abbrev {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: audit abbrev {raw!r} -> {got!r}, expected {expected!r}"
                    )
            print(f"=== {path.name} (title_case_location_label) ===")
            title_case_cases = [
                ("SAN FRANCISCO, CA", "San Francisco, CA"),
                ("NORTH LAS VEGAS, NV", "North Las Vegas, NV"),
                ("LOUISVILLE, KY", "Louisville, KY"),
                ("netherlands", "Netherlands"),
                ("BULGARIA", "Bulgaria"),
                ("San Francisco\nNew York, NY", "San Francisco\nNew York, NY"),
                ("EMEA", "EMEA"),
                ("APAC", "APAC"),
            ]
            for raw, expected in title_case_cases:
                got = mod.title_case_location_label(raw)
                ok = got == expected
                status = "ok" if ok else "FAIL"
                print(f"  [{status}] title_case {raw!r} -> {got!r} (expected {expected!r})")
                if not ok:
                    failures.append(
                        f"{path.name}: title_case {raw!r} -> {got!r}, expected {expected!r}"
                    )
            print(f"=== {path.name} (amazon_jobs scrape) ===")
            amazon_job = {
                "id_icims": "10402176",
                "title": "ITS Systems Engineer, Corporate Infrastructure Services, IT",
                "location": "IN, KA, Bengaluru",
                "normalized_location": "Bengaluru, Karnataka, IND",
                "locations": [
                    '{"normalizedStateName":"Karnataka","normalizedCountryCode":"IND",'
                    '"city":"Bengaluru","countryIso2a":"IN","normalizedCountryName":"India",'
                    '"normalizedLocation":"Bengaluru, Karnataka, IND","location":"IN, KA, Bengaluru"}'
                ],
                "job_path": "/en/jobs/10402176/its-systems-engineer-corporate-infrastructure-services-it",
            }
            loc_name, search_blob, codes = mod.amazon_job_location_context(amazon_job, cfg)
            job_loc, loc_label = mod.classify_location_with_fallback(
                loc_name, "us", "remote", cfg
            )
            reject = mod.amazon_job_scrape_reject_reason(
                loc_name, search_blob, codes, job_loc, loc_label
            )
            if reject != "location_india":
                failures.append(
                    f"{path.name}: amazon Bengaluru reject -> {reject!r}, expected 'location_india'"
                )
            else:
                print("  [ok] amazon Bengaluru job rejected as location_india")
            kerala_loc, kerala_blob, kerala_codes = mod.amazon_job_location_context(
                {
                    "location": "KERALA, IN",
                    "normalized_location": "Kerala, IND",
                    "locations": [
                        '{"normalizedCountryCode":"IND","countryIso2a":"IN",'
                        '"normalizedCountryName":"India","location":"KERALA, IN"}'
                    ],
                },
                cfg,
            )
            k_loc, k_label = mod.classify_location_with_fallback(
                kerala_loc, "us", "remote", cfg
            )
            k_reject = mod.amazon_job_scrape_reject_reason(
                kerala_loc, kerala_blob, kerala_codes, k_loc, k_label
            )
            if k_reject != "location_india":
                failures.append(
                    f"{path.name}: amazon Kerala reject -> {k_reject!r}, expected 'location_india'"
                )
            else:
                print("  [ok] amazon Kerala job rejected as location_india")
            seoul_loc, seoul_blob, seoul_codes = mod.amazon_job_location_context(
                {
                    "location": "KR, Seoul",
                    "normalized_location": "Seoul, KOR",
                    "locations": [
                        '{"normalizedCountryCode":"KOR","countryIso2a":"KR",'
                        '"normalizedCountryName":"Korea","location":"KR, Seoul"}'
                    ],
                },
                cfg,
            )
            s_loc, s_label = mod.classify_location_with_fallback(
                seoul_loc, "us", "remote", cfg
            )
            s_reject = mod.amazon_job_scrape_reject_reason(
                seoul_loc, seoul_blob, seoul_codes, s_loc, s_label
            )
            if s_reject != "location_non_us":
                failures.append(
                    f"{path.name}: amazon Seoul reject -> {s_reject!r}, expected 'location_non_us'"
                )
            else:
                print("  [ok] amazon Seoul job rejected as location_non_us")
    failures.extend(_run_legend_and_filter_and_logic(cfg))
    if failures:
        print("\nFailures:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nAll location classification checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
