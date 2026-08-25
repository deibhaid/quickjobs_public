#!/usr/bin/env python3
"""First-run setup for portable quickjobs: venv, deps, profile from resume."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from aviation_company_ids import load_aviation_company_ids
from no_visa_sponsor_company_ids import load_no_visa_sponsor_company_ids
from portable_runtime import ROOT, VENV_PY, get_quickjobs_root

VENV_DIR = ROOT / "python_venv"
VENV_PIP = VENV_DIR / "bin" / "pip"
PROFILE_PATH = ROOT / "quickjobs.profile.json"
SETUP_PATH = ROOT / "config" / "setup.json"
BASE_PATH = ROOT / "quickjobs.base.json"
RESIDENT_CHOICES = ("citizen", "green_card", "h1b")
RESIDENT_PROMPT_HINT = "citizen, green_card, visa"
RESUME_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md"}


def _prompt(label: str, *, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    value = input(f"{label}{hint}: ").strip()
    return value or default


def _prompt_yes_no(label: str, *, default: bool = False) -> bool:
    default_s = "y" if default else "n"
    while True:
        raw = _prompt(label, default=default_s).lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("Enter y or n.")


def _prompt_resident_status() -> str:
    while True:
        value = _prompt(f"Resident status ({RESIDENT_PROMPT_HINT})").lower().replace(" ", "_").replace(
            "-", "_"
        )
        if value in ("visa", "work_visa", "h1b"):
            return "h1b"
        if value in ("greencard", "permanent_resident", "lpr", "green_card_holder"):
            return "green_card"
        if value in RESIDENT_CHOICES:
            return value
        print(f"Choose one of: {RESIDENT_PROMPT_HINT}")


def _maybe_build_visa_employer_index() -> None:
    fetch_script = ROOT / "fetch_h1b_employer_index.py"
    if not fetch_script.is_file():
        print("Skipping DOL index build (fetch_h1b_employer_index.py not found in package).")
        return
    if not _prompt_yes_no(
        "Build DOL visa employer index now? (recommended — skips non-filers at scrape and shows company badges)",
        default=True,
    ):
        return
    _run([str(VENV_PY), str(fetch_script)], label="fetch DOL visa employer index")


def _prompt_choice(label: str, choices: tuple[str, ...]) -> str:
    opts = ", ".join(choices)
    while True:
        value = _prompt(f"{label} ({opts})").lower().replace(" ", "_").replace("-", "_")
        if value in choices:
            return value
        print(f"Choose one of: {opts}")


def _prompt_int(label: str, *, default: int | None = None) -> int:
    while True:
        raw = _prompt(label, default=str(default) if default is not None else "")
        try:
            return int(raw.replace(",", "").replace("$", "").strip())
        except ValueError:
            print("Enter a whole number (e.g. 200000).")


def _pick_resume_via_finder() -> Path | None:
    """macOS Finder open panel (resume may live outside quickjobs/)."""
    if sys.platform != "darwin":
        return None
    print("Opening Finder — choose your resume…")
    proc = subprocess.run(
        [
            "osascript",
            "-e",
            'POSIX path of (choose file with prompt "Select your resume (PDF, Word, or text)")',
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "User canceled" in err or "(-128)" in err:
            print("Finder selection canceled.")
        elif err:
            print(f"Finder could not open: {err}", file=sys.stderr)
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _validate_resume_path(path: Path) -> Path | None:
    if not path.is_file():
        print(f"File not found: {path}")
        return None
    if path.suffix.lower() not in RESUME_SUFFIXES:
        print("Use .pdf, .docx, .doc, or .txt/.md")
        return None
    return path


def _prompt_resume_path() -> Path:
    if sys.platform == "darwin":
        picked = _pick_resume_via_finder()
        if picked:
            ok = _validate_resume_path(picked)
            if ok:
                print(f"Selected: {ok}")
                return ok

    hint = "press Enter to open Finder" if sys.platform == "darwin" else ""
    while True:
        raw = _prompt(
            f"Path to resume (.pdf, .docx, .doc, or .txt)"
            + (f"; {hint}" if hint else ""),
        )
        if not raw and sys.platform == "darwin":
            picked = _pick_resume_via_finder()
            if picked:
                ok = _validate_resume_path(picked)
                if ok:
                    print(f"Selected: {ok}")
                    return ok
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        ok = _validate_resume_path(path)
        if ok:
            return ok


def _resume_looks_aviation(resume_text: str, skills: list[str]) -> bool:
    hints = (
        "cfi",
        "cfii",
        "pilot",
        "aviation",
        "flight instructor",
        "certified flight instructor",
        "asel",
        "atp",
        "commercial pilot",
        "first officer",
        "airline pilot",
    )
    lower = resume_text.lower()
    if any(h in lower for h in hints):
        return True
    return any(any(h in skill.lower() for h in hints) for skill in skills)


def _infer_name_from_resume(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 80:
            continue
        if "@" in line or re.search(r"https?://", line, re.I):
            continue
        if re.match(r"^[\w\s.'-]+$", line) and 2 <= len(line.split()) <= 5:
            return line
    return ""


def _ensure_portable_env() -> None:
    root = get_quickjobs_root()
    os.environ["QUICKJOBS_ROOT"] = str(root)
    os.environ["JOB_SEARCH_DIR"] = str(root / "cache" / "data")
    os.environ["JOB_BOARD_TMP_ROOT"] = str(root / "cache" / "tmp")
    os.environ["QUICKJOBS_JOBS_DIR"] = str(root / "output")
    os.environ["QUICKJOBS_NO_REMOTE_SYNC"] = "1"
    for sub in ("cache/data", "cache/tmp", "cache/scrape", "output", "config"):
        (root / sub).mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str], *, label: str) -> None:
    print(f"\n→ {label}")
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def _create_venv() -> None:
    if VENV_PY.is_file():
        print(f"Using existing venv: {VENV_DIR}")
        return
    py = sys.executable
    print(f"Creating venv with {py}")
    _run([py, "-m", "venv", str(VENV_DIR)], label="python -m venv python_venv")


def _install_dependencies() -> None:
    req = ROOT / "requirements.txt"
    if not req.is_file():
        raise SystemExit(f"Missing {req}")
    _run([str(VENV_PIP), "install", "--upgrade", "pip"], label="upgrade pip")
    _run([str(VENV_PIP), "install", "-r", str(req)], label="pip install -r requirements.txt")
    _run([str(VENV_PY), "-m", "playwright", "install", "chromium"], label="playwright install chromium")


def _extract_resume(resume_path: Path) -> tuple[str, list[str], list[str]]:
    """Return resume text, inferred skills, extra keywords via quickjobs.py."""
    script = """
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
resume = Path(sys.argv[2])
sys.path.insert(0, str(root))
import hub_tools  # noqa: E402
import quickjobs as qj  # noqa: E402

text = qj.extract_resume_text(resume)
base = hub_tools.load_base_bundle()
skills = qj.infer_skills_from_resume(text)
keywords = qj.infer_keywords_from_resume(text, base)
print(json.dumps({"text": text, "skills": skills, "keywords": keywords}))
"""
    proc = subprocess.run(
        [str(VENV_PY), "-c", script, str(ROOT), str(resume_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
        raise SystemExit("Resume extraction failed (see above)")
    payload = json.loads(proc.stdout.strip())
    return payload["text"], payload["skills"], payload["keywords"]


def _write_profile(
    *,
    name: str,
    home_zip: str,
    resident_status: str,
    salary_floor: int,
    skills: list[str],
    extra_keywords: list[str],
    resume_path: Path,
    include_aviation: bool,
    aviation_search: bool = False,
    company_ids_exclude: list[str] | None = None,
) -> None:
    profile_block: dict = {
            "name": name,
            "home_zip": home_zip,
            "local_radius_miles": 50,
            "salary_floor": salary_floor,
            "resident_status": resident_status,
            "jobs_dir": str(ROOT / "output"),
            "skills": skills,
            "jd_blocklist": [],
            "board_ui": {
                "hide_zero_yield_sidebar": True,
                "hide_empty_stub_entries": True,
            },
    }
    if aviation_search:
        profile_block["aviation_search"] = True
    profile: dict = {
        "profile": profile_block,
        "remote_sync": {"enabled": False},
        "company_ids_exclude": list(company_ids_exclude or []),
    }
    if extra_keywords:
        profile["keywords_include"] = extra_keywords
    PROFILE_PATH.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    SETUP_PATH.write_text(
        json.dumps(
            {
                "resume_path": str(resume_path),
                "salary_floor": salary_floor,
                "home_zip": home_zip,
                "resident_status": resident_status,
                "name": name,
                "inferred_skills": skills,
                "extra_keywords": extra_keywords,
                "include_aviation": include_aviation,
                "aviation_search": aviation_search,
                "company_ids_exclude": profile["company_ids_exclude"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _verify_paths() -> None:
    """Confirm profile and output paths stay under QUICKJOBS_ROOT."""
    root = get_quickjobs_root()
    prof = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    jobs_dir = Path(str(prof["profile"]["jobs_dir"])).resolve()
    if not str(jobs_dir).startswith(str(root.resolve())):
        raise SystemExit(f"jobs_dir must be inside {root}: {jobs_dir}")
    for rel in ("cache/data", "cache/tmp", "output", "config"):
        p = (root / rel).resolve()
        if not p.is_dir():
            raise SystemExit(f"Missing directory: {p}")


def main() -> int:
    print("Quickjobs portable setup")
    print(f"Package root: {ROOT}\n")
    if not BASE_PATH.is_file() or not (ROOT / "quickjobs.py").is_file():
        print("Run this script from the unzipped quickjobs/ directory.", file=sys.stderr)
        return 1

    _ensure_portable_env()
    _create_venv()
    _install_dependencies()

    resume_path = _prompt_resume_path()
    resident = _prompt_resident_status()
    include_aviation = _prompt_yes_no(
        "Include aviation, airline, and pilot jobs in your search? (y/n)",
        default=False,
    )
    home_zip = _prompt("Home ZIP code")
    if not re.match(r"^\d{5}(-\d{4})?$", home_zip):
        print("Warning: expected US ZIP like 00000 or 10001-1234")

    salary_floor = _prompt_int("Desired base salary (USD)", default=150000)

    print("\nReading resume…")
    resume_text, skills, extra_kw = _extract_resume(resume_path)
    if len(resume_text.strip()) < 80:
        print("Warning: very little text extracted; matching may be weak.")

    name = _infer_name_from_resume(resume_text)
    if not name:
        name = _prompt("Your full name (for board header)")
    else:
        confirmed = _prompt("Your full name", default=name)
        name = confirmed or name

    aviation_search = include_aviation and _resume_looks_aviation(resume_text, skills)
    company_ids_exclude: list[str] = []
    if not include_aviation:
        company_ids_exclude = load_aviation_company_ids(ROOT)
    if resident == "h1b":
        company_ids_exclude = sorted(
            set(company_ids_exclude) | set(load_no_visa_sponsor_company_ids(ROOT))
        )

    _write_profile(
        name=name,
        home_zip=home_zip,
        resident_status=resident,
        salary_floor=salary_floor,
        skills=skills,
        extra_keywords=extra_kw,
        resume_path=resume_path,
        include_aviation=include_aviation,
        aviation_search=aviation_search,
        company_ids_exclude=company_ids_exclude,
    )
    _verify_paths()

    if resident == "h1b":
        _maybe_build_visa_employer_index()

    print("\nSetup complete.")
    print(f"  Profile: {PROFILE_PATH}")
    print(f"  Skills inferred: {len(skills)}")
    print(f"  Extra keywords: {len(extra_kw)}")
    if aviation_search:
        print("  Mode: aviation (pilot employers only; flight instructor → pilot job search)")
    elif not include_aviation:
        print(f"  Aviation employers excluded: {len(company_ids_exclude)}")
    if resident == "h1b":
        non_sponsor = load_no_visa_sponsor_company_ids(ROOT)
        print(f"  Non-sponsoring employers excluded: {len(non_sponsor)}")
    print(f"  Output HTML: {ROOT / 'output' / 'job-search-quickjobs.html'}")
    from portable_runtime import run_cmd

    print("\nNext:")
    print(run_cmd())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
