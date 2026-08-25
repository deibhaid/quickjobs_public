#!/usr/bin/env python3
"""Apply LinkedIn/Glassdoor no-network stubs to a public quickjobs tree.

Markers use ``# PUBLIC_BUILD_STUB`` so re-runs are idempotent.
Does not modify the private source tree — only paths under --public-dir.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_func_body_start(lines: list[str], func_name: str) -> int | None:
    """Return index of first body line after def + optional docstring, or None."""
    prefix = f"def {func_name}("
    start = None
    for i, line in enumerate(lines):
        if line.startswith(prefix) or line.startswith(f"async def {func_name}("):
            start = i
            break
    if start is None:
        return None
    # Walk to end of signature (line ending with ':')
    sig_end = start
    while sig_end < len(lines) and not lines[sig_end].rstrip().endswith(":"):
        sig_end += 1
    if sig_end >= len(lines):
        return None
    body = sig_end + 1
    if body < len(lines):
        stripped = lines[body].lstrip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.count(quote) >= 2 and len(stripped) > 3:
                # one-line docstring
                body += 1
            else:
                body += 1
                while body < len(lines) and quote not in lines[body]:
                    body += 1
                if body < len(lines):
                    body += 1
    return body


def _inject_stub(lines: list[str], func_name: str, stub_lines: list[str]) -> bool:
    body = _find_func_body_start(lines, func_name)
    if body is None:
        return False
    # Idempotent
    if body < len(lines) and "# PUBLIC_BUILD_STUB" in lines[body]:
        return False
    # Also check a few lines ahead in case of blank line
    for j in range(body, min(body + 3, len(lines))):
        if "# PUBLIC_BUILD_STUB" in lines[j]:
            return False
    lines[body:body] = [ln if ln.endswith("\n") else ln + "\n" for ln in stub_lines]
    return True


LINKEDIN_STUB = [
    "    # PUBLIC_BUILD_STUB — no LinkedIn network calls in the public repo\n",
    '    print("LinkedIn scrape disabled in public build", flush=True)\n',
    '    return [], "disabled in public build"\n',
]

GLASSDOOR_HTML_STUB = [
    "    # PUBLIC_BUILD_STUB — no Glassdoor network calls in the public repo\n",
    '    return ""\n',
]

GLASSDOOR_PREFETCH_STUB = [
    "    # PUBLIC_BUILD_STUB — no Glassdoor network calls in the public repo\n",
    "    return 0\n",
]

EDIT_CONFIG_ROOT_STUB = [
    "    # PUBLIC_BUILD_STUB — use the cloned repo path (no private Mac mapping)\n",
    '    env = os.environ.get("QUICKJOBS_EDIT_CONFIG_ROOT", "").strip()\n',
    "    if env:\n",
    "        return Path(env).expanduser()\n",
    "    return Path(SCRIPT_DIR).expanduser().resolve()\n",
]


def stub_quickjobs_py(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    changed: list[str] = []
    for name, stub in (
        ("fetch_linkedin", LINKEDIN_STUB),
        ("fetch_glassdoor_search_html", GLASSDOOR_HTML_STUB),
        ("prefetch_glassdoor_ratings", GLASSDOOR_PREFETCH_STUB),
        ("prefetch_glassdoor_for_all_companies", GLASSDOOR_PREFETCH_STUB),
        ("edit_config_root_for_board", EDIT_CONFIG_ROOT_STUB),
    ):
        if _inject_stub(lines, name, stub):
            changed.append(name)
    if changed:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


def stub_cli_glassdoor(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if "# PUBLIC_BUILD_STUB" in text:
        return False
    marker = 'if __name__ == "__main__":'
    if marker not in text:
        return False
    stub_main = (
        'if __name__ == "__main__":\n'
        "    # PUBLIC_BUILD_STUB — Glassdoor fetch disabled in the public repo\n"
        '    print("Glassdoor fetch disabled in public build", flush=True)\n'
        "    raise SystemExit(0)\n"
    )
    path.write_text(text.replace(marker, stub_main, 1), encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-dir",
        type=Path,
        required=True,
        help="Path to quickjobs_public working tree",
    )
    args = parser.parse_args(argv)
    root = args.public_dir.expanduser().resolve()
    if not root.is_dir():
        print(f"Public dir not found: {root}", file=sys.stderr)
        return 1
    py_path = root / "quickjobs.david.py"
    if not py_path.is_file():
        print(f"Missing {py_path}", file=sys.stderr)
        return 1
    changed = stub_quickjobs_py(py_path)
    portable = stub_cli_glassdoor(root / "portable" / "fetch_glassdoor.py")
    maint = stub_cli_glassdoor(
        root / "scripts" / "maintenance" / "fetch_manual_career_glassdoor.py"
    )
    if changed:
        print(f"Stubbed in quickjobs.david.py: {', '.join(changed)}")
    else:
        print("quickjobs.david.py stubs already present or unchanged")
    if portable:
        print("Stubbed portable/fetch_glassdoor.py")
    if maint:
        print("Stubbed scripts/maintenance/fetch_manual_career_glassdoor.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
