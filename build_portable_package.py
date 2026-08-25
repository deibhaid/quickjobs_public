#!/usr/bin/env python3
"""Assemble the portable quickjobs/ zip bundle from quickjobs.david.* sources."""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_PY = SCRIPT_DIR / "quickjobs.david.py"
SOURCE_BASE = SCRIPT_DIR / "quickjobs.david.base.json"
SOURCE_COMPANIES = SCRIPT_DIR / "quickjobs.david.companies.json"
SOURCE_HUB_TOOLS = SCRIPT_DIR / "scripts" / "hubs" / "hub_tools.py"
SOURCE_HUBS = SCRIPT_DIR / "quickjobs_hubs.py"
SCRIPTDIR_ROOT = Path(__file__).resolve().parents[2] / "scriptdir"
OUTPUT_ROOT = SCRIPTDIR_ROOT / "output" / "quickjobs"
ZIP_PATH = SCRIPTDIR_ROOT / "output" / "quickjobs-portable.zip"

PORTABLE_BOOTSTRAP = '''
QUICKJOBS_ROOT = Path(os.environ.get("QUICKJOBS_ROOT", str(SCRIPT_DIR))).resolve()


def _ensure_portable_env() -> None:
    """Cache, sidecars, and temp stay under QUICKJOBS_ROOT/cache/ (not ~/.job_search)."""
    cache_root = QUICKJOBS_ROOT / "cache"
    os.environ.setdefault("QUICKJOBS_ROOT", str(QUICKJOBS_ROOT))
    os.environ.setdefault("JOB_SEARCH_DIR", str(cache_root / "data"))
    os.environ.setdefault("QUICKJOBS_JOBS_DIR", str(QUICKJOBS_ROOT / "output"))
    for sub in ("data", "scrape", "glassdoor", "h1b", "pycache", "run"):
        (cache_root / sub).mkdir(parents=True, exist_ok=True)
    (QUICKJOBS_ROOT / "output").mkdir(parents=True, exist_ok=True)
    (QUICKJOBS_ROOT / "config").mkdir(parents=True, exist_ok=True)


_ensure_portable_env()
'''

PORTABLE_TMP_BLOCK_OLD = """TMP_ROOT = Path(os.environ.get("JOB_BOARD_TMP_ROOT", "/tmp/quickjobs")).expanduser()
TMP_BOARD_ROOT = TMP_ROOT / BOARD_SUFFIX
TMP_CACHE_ROOT = TMP_BOARD_ROOT / "cache"
TMP_PYCACHE_ROOT = TMP_BOARD_ROOT / "pycache"
TMP_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
TMP_PYCACHE_ROOT.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(TMP_PYCACHE_ROOT)"""

PORTABLE_TMP_BLOCK_NEW = """TMP_BOARD_ROOT = QUICKJOBS_ROOT / "cache" / "run"
TMP_CACHE_ROOT = QUICKJOBS_ROOT / "cache" / "scrape"
TMP_PYCACHE_ROOT = QUICKJOBS_ROOT / "cache" / "pycache"
TMP_BOARD_ROOT.mkdir(parents=True, exist_ok=True)
TMP_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
TMP_PYCACHE_ROOT.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(TMP_PYCACHE_ROOT)"""

PORTABLE_GLASSDOOR_CACHE_OLD = """def glassdoor_meta_cache_root() -> Path:
    portable_root = globals().get("QUICKJOBS_ROOT")
    if portable_root is not None:
        path = Path(portable_root) / "cache" / "glassdoor"
    else:
        root = Path(os.environ.get("JOB_SEARCH_DIR", str(DEFAULT_JOB_SEARCH_DIR))).expanduser()
        path = root / BOARD_SUFFIX / "glassdoor"
    path.mkdir(parents=True, exist_ok=True)
    legacy_dir = cache_dir(SCRIPT_DIR) / "glassdoor"
    if legacy_dir.is_dir():
        for legacy in legacy_dir.glob("*.json"):
            _migrate_legacy_sidecar(path / legacy.name, legacy)
    return path


def glassdoor_meta_cache_path(company_id: str) -> Path:
    return glassdoor_meta_cache_root() / f"{company_id}.json"
"""

PORTABLE_GLASSDOOR_CACHE_NEW = """def glassdoor_meta_cache_root() -> Path:
    path = QUICKJOBS_ROOT / "cache" / "glassdoor"
    path.mkdir(parents=True, exist_ok=True)
    return path


def glassdoor_meta_cache_path(company_id: str) -> Path:
    path = glassdoor_meta_cache_root() / f"{company_id}.json"
    _assert_portable_path(path)
    return path"""

PATH_REPLACEMENTS = [
    (
        'DEFAULT_JOB_SEARCH_DIR = Path.home() / ".job_search" / "quickjobs"',
        "DEFAULT_JOB_SEARCH_DIR = QUICKJOBS_ROOT / \"cache\" / \"data\"",
    ),
    (
        "return Path.home() / \"Downloads\" / \"jobs\"",
        "return QUICKJOBS_ROOT / \"output\"",
    ),
    (
        "Sidecars: ~/.job_search/quickjobs/<name>/ (pipeline, state, digest, snapshot)",
        "Sidecars: <QUICKJOBS_ROOT>/cache/data/<name>/ (pipeline, state, digest, snapshot)",
    ),
    (
        "Output: <jobs_dir>/job-search-<name>.html (jobs_dir from profile)",
        "Output: <QUICKJOBS_ROOT>/output/job-search-<name>.html (override via profile jobs_dir)",
    ),
    (
        "Requires: ~/.v/bin/pip install playwright && playwright install chromium",
        "Requires: pip install -r requirements.txt && playwright install chromium (see configure.py)",
    ),
]

EXTRACT_RESUME_PATCH = '''def extract_resume_text(resume_path: Path) -> str:
    suffix = resume_path.suffix.lower()
    if suffix in {".txt", ".md", ".rst", ".log"}:
        return resume_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".docx":
        with zipfile.ZipFile(resume_path) as zf:
            data = zf.read("word/document.xml").decode("utf-8", "ignore")
        text = re.sub(r"<[^>]+>", " ", data)
        return html.unescape(re.sub(r"\\s+", " ", text)).strip()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF resume requires pypdf (run configure.py first)") from exc
        reader = PdfReader(str(resume_path))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return re.sub(r"\\s+", " ", "\\n".join(parts)).strip()
    if suffix == ".doc":
        for cmd in (
            ["textutil", "-convert", "txt", "-stdout", str(resume_path)],
            ["antiword", str(resume_path)],
        ):
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue
            if proc.returncode == 0 and (proc.stdout or "").strip():
                return proc.stdout.strip()
        raise RuntimeError(
            "Legacy .doc resume: convert to .docx or .pdf, or install antiword/textutil."
        )
    raise RuntimeError(
        "Unsupported resume format. Use .pdf, .docx, .doc, or .txt/.md."
    )'''

GENERATE_CONFIG_PATCH = '''def generate_personalized_config(
    base_cfg: dict[str, Any],
    name: str,
    home_zip: str,
    resident_status: str,
    resume_text: str,
    jobs_dir: str | None = None,
    salary_floor: int | None = None,
) -> dict[str, Any]:
    cfg = json.loads(json.dumps(base_cfg))
    profile = cfg.setdefault("profile", {})
    profile["name"] = name
    profile["home_zip"] = str(home_zip)
    status = resident_status.lower().strip().replace("-", "_")
    if status in ("visa", "work_visa"):
        status = "h1b"
    profile["resident_status"] = status
    if jobs_dir:
        profile["jobs_dir"] = jobs_dir
    if salary_floor is not None:
        profile["salary_floor"] = int(salary_floor)
    profile["skills"] = infer_skills_from_resume(resume_text)
    extra_kw = infer_keywords_from_resume(resume_text, base_cfg)
    if extra_kw:
        tier2 = [str(x).lower() for x in (cfg.get("keywords_include_tier2") or [])]
        for kw in extra_kw:
            lower = str(kw).strip().lower()
            if lower and lower not in tier2:
                tier2.append(lower)
        cfg["keywords_include_tier2"] = tier2
    return cfg'''


def infer_keywords_helper() -> str:
    return '''

def infer_keywords_from_resume(resume_text: str, base_cfg: dict[str, Any] | None = None) -> list[str]:
    """Role/search keywords inferred from resume (not David IT defaults)."""
    _ = base_cfg
    lower = resume_text.lower()
    found: list[str] = []
    patterns = (
        r"\\b(devops|sre|platform engineer|infrastructure engineer|site reliability engineer|"
        r"cloud engineer|kubernetes|terraform|ci/cd|observability|data platform|"
        r"release engineer|build engineer|automation engineer|software engineer)\\b",
        r"\\b(flight instructor|certified flight instructor|cfi|cfii|chief flight instructor|"
        r"commercial pilot|private pilot|first officer|airline pilot|flight training|"
        r"ground instructor|flight school|aviation)\\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, lower):
            phrase = re.sub(r"\\s+", " ", match.group(1).strip())
            if phrase and phrase not in found:
                found.append(phrase)
    for skill in infer_skills_from_resume(resume_text):
        if skill not in found:
            found.append(skill)
    return found[:20]
'''


def patch_quickjobs_py(text: str) -> str:
    anchor = "SCRIPT_DIR = Path(__file__).resolve().parent\n"
    if anchor not in text:
        raise RuntimeError("Could not find SCRIPT_DIR anchor in source")
    text = text.replace(anchor, anchor + PORTABLE_BOOTSTRAP)
    if PORTABLE_TMP_BLOCK_OLD not in text:
        raise RuntimeError("TMP_ROOT/TMP_BOARD_ROOT block not found")
    text = text.replace(PORTABLE_TMP_BLOCK_OLD, PORTABLE_TMP_BLOCK_NEW)
    if PORTABLE_GLASSDOOR_CACHE_OLD not in text:
        raise RuntimeError("glassdoor_meta_cache_path block not found")
    text = text.replace(PORTABLE_GLASSDOOR_CACHE_OLD, PORTABLE_GLASSDOOR_CACHE_NEW)
    for old, new in PATH_REPLACEMENTS:
        if old not in text:
            raise RuntimeError(f"Missing expected snippet: {old[:60]}...")
        text = text.replace(old, new)
    old_extract = '''def extract_resume_text(resume_path: Path) -> str:
    suffix = resume_path.suffix.lower()
    if suffix in {".txt", ".md", ".rst", ".log"}:
        return resume_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".docx":
        with zipfile.ZipFile(resume_path) as zf:
            data = zf.read("word/document.xml").decode("utf-8", "ignore")
        text = re.sub(r"<[^>]+>", " ", data)
        return html.unescape(re.sub(r"\\s+", " ", text)).strip()
    raise RuntimeError(
        "Unsupported resume format. Use .txt/.md/.docx (or convert PDF to text first)."
    )'''
    if old_extract not in text:
        raise RuntimeError("extract_resume_text block not found")
    text = text.replace(old_extract, EXTRACT_RESUME_PATCH)
    if "def infer_keywords_from_resume" not in text:
        text = text.replace(
            "def infer_skills_from_resume(resume_text: str) -> list[str]:",
            infer_keywords_helper() + "\ndef infer_skills_from_resume(resume_text: str) -> list[str]:",
        )
    old_gen = '''def generate_personalized_config(
    base_cfg: dict[str, Any],
    name: str,
    home_zip: str,
    resident_status: str,
    resume_text: str,
    jobs_dir: str | None = None,
) -> dict[str, Any]:
    cfg = json.loads(json.dumps(base_cfg))
    profile = cfg.setdefault("profile", {})
    profile["name"] = name
    profile["home_zip"] = str(home_zip)
    status = resident_status.lower().strip().replace("-", "_")
    if status in ("visa", "work_visa"):
        status = "h1b"
    profile["resident_status"] = status
    if jobs_dir:
        profile["jobs_dir"] = jobs_dir
    profile["skills"] = infer_skills_from_resume(resume_text)
    extra_kw = infer_keywords_from_resume(resume_text, base_cfg)
    if extra_kw:
        tier2 = [str(x).lower() for x in (cfg.get("keywords_include_tier2") or [])]
        for kw in extra_kw:
            lower = str(kw).strip().lower()
            if lower and lower not in tier2:
                tier2.append(lower)
        cfg["keywords_include_tier2"] = tier2
    return cfg'''
    if old_gen not in text:
        raise RuntimeError("generate_personalized_config block not found")
    text = text.replace(old_gen, GENERATE_CONFIG_PATCH)
    strict = '''

def _assert_portable_path(path: Path) -> None:
    if os.environ.get("QUICKJOBS_STRICT") != "1":
        return
    root = QUICKJOBS_ROOT.resolve()
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"QUICKJOBS_STRICT: path outside package: {path}") from exc

'''
    if "def _assert_portable_path" not in text:
        text = text.replace("_ensure_portable_env()\n", "_ensure_portable_env()\n" + strict)
        text = text.replace(
            "    path = (root / suffix).resolve()\n    path.mkdir(parents=True, exist_ok=True)\n    return path",
            "    path = (root / suffix).resolve()\n    _assert_portable_path(path)\n    path.mkdir(parents=True, exist_ok=True)\n    return path",
        )
        text = text.replace(
            "    jobs_dir = resolve_jobs_dir(cfg)\n    jobs_dir.mkdir(parents=True, exist_ok=True)",
            "    jobs_dir = resolve_jobs_dir(cfg)\n    _assert_portable_path(jobs_dir)\n    jobs_dir.mkdir(parents=True, exist_ok=True)",
        )
        text = text.replace(
            "def cache_dir(script_dir: Path) -> Path:\n    _ = script_dir  # retained for call compatibility\n    path = TMP_CACHE_ROOT\n    path.mkdir(parents=True, exist_ok=True)\n    return path",
            "def cache_dir(script_dir: Path) -> Path:\n    _ = script_dir  # retained for call compatibility\n    path = TMP_CACHE_ROOT\n    _assert_portable_path(path)\n    path.mkdir(parents=True, exist_ok=True)\n    return path",
        )
        text = text.replace(
            "def h1b_cache_root() -> Path:\n    \"\"\"DOL LCA employer index and per-company work visa lookup cache.\"\"\"\n    portable_root = globals().get(\"QUICKJOBS_ROOT\")\n    if portable_root is not None:\n        path = Path(portable_root) / \"cache\" / \"h1b\"\n    else:\n        path = TMP_BOARD_ROOT / \"h1b\"\n    path.mkdir(parents=True, exist_ok=True)\n    return path",
            "def h1b_cache_root() -> Path:\n    \"\"\"DOL LCA employer index and per-company work visa lookup cache.\"\"\"\n    path = QUICKJOBS_ROOT / \"cache\" / \"h1b\"\n    _assert_portable_path(path)\n    path.mkdir(parents=True, exist_ok=True)\n    return path",
        )
        text = text.replace(
            "def glassdoor_meta_cache_path(company_id: str) -> Path:\n    path = QUICKJOBS_ROOT / \"cache\" / \"glassdoor\" / f\"{company_id}.json\"\n    path.parent.mkdir(parents=True, exist_ok=True)\n    return path",
            "def glassdoor_meta_cache_path(company_id: str) -> Path:\n    path = QUICKJOBS_ROOT / \"cache\" / \"glassdoor\" / f\"{company_id}.json\"\n    _assert_portable_path(path)\n    path.parent.mkdir(parents=True, exist_ok=True)\n    return path",
        )
    return text


def patch_hub_tools(text: str) -> str:
    """hub_tools.py resolves dev vs portable layout at import time; no build-time patch."""
    return text


def patch_hubs_py(text: str) -> str:
    """quickjobs_hubs.py resolves dev vs portable layout at import time; no build-time patch."""
    return text


def patch_base_json(data: dict) -> dict:
    intro = (
        "Permanent application log — stored under quickjobs/cache/data/ "
        "(job-board-pipeline.json next to your board HTML)."
    )
    for section in data.get("sections") or []:
        if isinstance(section, dict) and section.get("id") == "applied":
            section["intro"] = intro
    return data


def write_aviation_company_ids_config(base: dict, output_root: Path) -> None:
    """Emit config/aviation-company-ids.json from sector=aviation employers in base."""
    ids = sorted(
        str(c["id"])
        for c in base.get("companies", [])
        if c.get("id") and str(c.get("sector") or "").lower() == "aviation"
    )
    dest = output_root / "config" / "aviation-company-ids.json"
    dest.write_text(
        json.dumps({"company_ids": ids}, indent=2) + "\n",
        encoding="utf-8",
    )


def write_no_visa_sponsor_company_ids_config(output_root: Path) -> None:
    """Copy config/no-visa-sponsor-company-ids.json into the portable package."""
    source = SCRIPT_DIR / "config" / "no-visa-sponsor-company-ids.json"
    dest = output_root / "config" / "no-visa-sponsor-company-ids.json"
    if source.is_file():
        shutil.copy2(source, dest)
        return
    from portable.no_visa_sponsor_company_ids import CANONICAL_NO_VISA_SPONSOR_COMPANY_IDS

    dest.write_text(
        json.dumps({"company_ids": list(CANONICAL_NO_VISA_SPONSOR_COMPANY_IDS)}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def write_package() -> Path:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True)
    for sub in (
        "cache/data",
        "cache/scrape",
        "cache/glassdoor",
        "cache/h1b",
        "cache/pycache",
        "cache/run",
        "output",
        "config",
    ):
        (OUTPUT_ROOT / sub).mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "cache" / ".gitkeep").write_text("", encoding="utf-8")
    (OUTPUT_ROOT / "output" / ".gitkeep").write_text("", encoding="utf-8")
    (OUTPUT_ROOT / "config" / ".gitkeep").write_text("", encoding="utf-8")

    py_text = SOURCE_PY.read_text(encoding="utf-8")
    (OUTPUT_ROOT / "quickjobs.py").write_text(patch_quickjobs_py(py_text), encoding="utf-8")
    shutil.copy2(SCRIPT_DIR / "run_log.py", OUTPUT_ROOT / "run_log.py")
    shutil.copy2(SCRIPT_DIR / "h1b_employer.py", OUTPUT_ROOT / "h1b_employer.py")

    base = json.loads(SOURCE_BASE.read_text(encoding="utf-8"))
    companies_doc = json.loads(SOURCE_COMPANIES.read_text(encoding="utf-8"))
    patched_base = patch_base_json(base)
    (OUTPUT_ROOT / "quickjobs.base.json").write_text(
        json.dumps(patched_base, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_ROOT / "quickjobs.companies.json").write_text(
        json.dumps(companies_doc, indent=2) + "\n",
        encoding="utf-8",
    )
    merged_base = {**patched_base, "companies": companies_doc.get("companies") or []}
    write_aviation_company_ids_config(merged_base, OUTPUT_ROOT)
    write_no_visa_sponsor_company_ids_config(OUTPUT_ROOT)
    (OUTPUT_ROOT / "quickjobs.unconvertible-careers.json").write_text(
        '{"employers": []}\n',
        encoding="utf-8",
    )

    hub_tools = patch_hub_tools(SOURCE_HUB_TOOLS.read_text(encoding="utf-8"))
    (OUTPUT_ROOT / "hub_tools.py").write_text(hub_tools, encoding="utf-8")
    if SOURCE_HUBS.is_file():
        hubs = patch_hubs_py(SOURCE_HUBS.read_text(encoding="utf-8"))
        (OUTPUT_ROOT / "quickjobs_hubs.py").write_text(hubs, encoding="utf-8")

    extras = [
        "aviation_company_ids.py",
        "no_visa_sponsor_company_ids.py",
        "configure.py",
        "requirements.txt",
        "README.md",
        "ARCHITECTURE.txt",
        "portable_runtime.py",
        "worker_tuning.py",
        "run.py",
        "fetch_glassdoor.py",
        "quickjobs-favicon.png",
        "quickjobs-apple-touch-icon.png",
    ]
    fetch_h1b = SCRIPT_DIR / "scripts" / "maintenance" / "fetch_h1b_employer_index.py"
    if fetch_h1b.is_file():
        fetch_h1b_text = fetch_h1b.read_text(encoding="utf-8").replace(
            "quickjobs.david.py",
            "quickjobs.py",
        ).replace(
            "REPO_ROOT = Path(__file__).resolve().parents[2]",
            "REPO_ROOT = Path(__file__).resolve().parent",
        )
        _h1b_main = 'if __name__ == "__main__":\n    raise SystemExit(main())'
        _h1b_main_portable = (
            'if __name__ == "__main__":\n'
            "    import portable_runtime as pr\n"
            "\n"
            "    pr.ensure_venv_python()\n"
            "    pr.apply_portable_env()\n"
            "    raise SystemExit(main())"
        )
        if _h1b_main not in fetch_h1b_text:
            raise RuntimeError("fetch_h1b_employer_index.py main guard changed; update portable patch")
        fetch_h1b_text = fetch_h1b_text.replace(_h1b_main, _h1b_main_portable)
        (OUTPUT_ROOT / "fetch_h1b_employer_index.py").write_text(fetch_h1b_text, encoding="utf-8")
    for name in extras:
        src = SCRIPT_DIR / "portable" / name
        if not src.is_file():
            raise RuntimeError(f"Missing portable template: {src}")
        shutil.copy2(src, OUTPUT_ROOT / name)

    david_meta = SCRIPT_DIR / "quickjobs.david.manual-career-meta.json"
    portable_meta = OUTPUT_ROOT / "quickjobs.manual-career-meta.json"
    if david_meta.is_file():
        shutil.copy2(david_meta, portable_meta)
    else:
        portable_meta.write_text('{"employers": {}}\n', encoding="utf-8")

    favicon_domains = SCRIPT_DIR / "quickjobs.david.favicon-domains.json"
    portable_favicon = OUTPUT_ROOT / "quickjobs.favicon-domains.json"
    if favicon_domains.is_file():
        shutil.copy2(favicon_domains, portable_favicon)
    else:
        portable_favicon.write_text(
            json.dumps(
                {
                    "by_company_id": {},
                    "by_greenhouse_board": {},
                    "by_ashby_board": {},
                    "by_lever_site": {},
                    "by_workday_site": {},
                    "by_smartrecruiters_company": {},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return OUTPUT_ROOT


def write_zip(root: Path) -> Path:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    skip_dirs = {"python_venv", ".venv", "__pycache__"}
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if any(part in skip_dirs for part in path.parts):
                continue
            if path.is_file():
                zf.write(path, path.relative_to(root.parent))
    return ZIP_PATH


def main() -> int:
    from run_log import install_run_log_stream

    install_run_log_stream(enable_timing=False)
    if not os.environ.get("QUICKJOBS_BUILD_QUIET"):
        if os.environ.get("QUICKJOBS_VERBOSE") == "1":
            print("[step] portable build")
    root = write_package()
    zip_path = write_zip(root)
    if os.environ.get("QUICKJOBS_BUILD_QUIET"):
        return 0
    size_kb = zip_path.stat().st_size // 1024
    if os.environ.get("QUICKJOBS_VERBOSE") == "1":
        prefix = os.environ.get("QUICKJOBS_OUTPUT_PREFIX", "")
        print(f"{prefix}package  {root}")
        print(f"{prefix}zip      {zip_path} ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
