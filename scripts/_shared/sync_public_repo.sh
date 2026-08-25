#!/usr/bin/env bash
# Sync shareable files from private quickjobs → quickjobs_public.
# Never copies the real profile; installs placeholder profile; applies ToS stubs.
# Does not push to GitHub (you push with your own gh auth).
set -euo pipefail

PRIVATE_DIR="${QUICKJOBS_DIR:-${HOME}/ws/github/quickjobs}"
PUBLIC_DIR="${QUICKJOBS_PUBLIC_DIR:-${HOME}/ws/github/quickjobs_public}"
PY="${HOME}/.v/bin/python"
[[ -x "${PY}" ]] || PY="$(command -v python3)"

usage() {
  cat <<'EOF'
Usage: sync_public_repo.sh [--dry-run]

  Copy shareable sources from the private quickjobs tree into quickjobs_public,
  install quickjobs.david.profile.json from the example placeholder, and apply
  LinkedIn/Glassdoor no-network stubs. Does not git commit or push.

Environment:
  QUICKJOBS_DIR          Private tree (default: ~/ws/github/quickjobs)
  QUICKJOBS_PUBLIC_DIR   Public tree  (default: ~/ws/github/quickjobs_public)
EOF
}

DRY_RUN=0
while [[ "${#}" -gt 0 ]]; do
  case "${1}" in
    -h|--help) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown arg: ${1}" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ ! -d "${PRIVATE_DIR}" ]]; then
  echo "Private dir missing: ${PRIVATE_DIR}" >&2
  exit 1
fi
if [[ ! -d "${PUBLIC_DIR}" ]]; then
  echo "Public dir missing: ${PUBLIC_DIR} (clone YOUR_GITHUB_USER/quickjobs_public first)" >&2
  exit 1
fi

EXAMPLE_PROFILE="${PRIVATE_DIR}/quickjobs.david.profile.example.json"
if [[ ! -f "${EXAMPLE_PROFILE}" ]]; then
  echo "Missing placeholder template: ${EXAMPLE_PROFILE}" >&2
  exit 1
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[dry-run] would sync from ${PRIVATE_DIR} → ${PUBLIC_DIR}"
  echo "[dry-run] would install placeholder profile + apply stubs"
  exit 0
fi

copy_file() {
  local rel="${1}"
  local src="${PRIVATE_DIR}/${rel}"
  local dst="${PUBLIC_DIR}/${rel}"
  [[ -e "${src}" ]] || return 0
  mkdir -p "$(dirname "${dst}")"
  rsync -a "${src}" "${dst}"
}

copy_tree() {
  local rel="${1}"
  local src="${PRIVATE_DIR}/${rel}"
  local dst="${PUBLIC_DIR}/${rel}"
  [[ -d "${src}" ]] || return 0
  mkdir -p "${dst}"
  rsync -a \
    --exclude '.DS_Store' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache/' \
    "${src}/" "${dst}/"
}

# Files
for f in \
  HOWTO.md \
  README.md \
  build_portable_package.py \
  h1b_employer.py \
  run_log.py \
  quickjobs_hubs.py \
  test_ats_api_timing.py \
  quickjobs.david.py \
  quickjobs.david.base.json \
  quickjobs.david.companies.json \
  quickjobs.david.favicon-domains.json \
  quickjobs.david.manual-career-meta.json \
  quickjobs.david.unconvertible-careers.json \
  quickjobs.david.profile.example.json \
  scripts/_shared/draft-release.sh \
  scripts/_shared/sync_public_repo.sh \
  scripts/_shared/apply_public_stubs.py
 do
  copy_file "${f}"
done
# sanitize_public_tree.py stays private-only (its pattern table contains personal needles)

# Trees (omit personal remote-host setup helpers)
for d in config portable scripts tests; do
  copy_tree "${d}"
done
# Personal / private-only tooling — never publish
rm -f "${PUBLIC_DIR}/scripts/maintenance/install-ulimits-remote.sh"
rm -f "${PUBLIC_DIR}/scripts/_shared/sanitize_public_tree.py"

# Public .gitignore: track placeholder profile (do not ignore *.profile.json).
cat >"${PUBLIC_DIR}/.gitignore" <<'EOF'
# Secrets
.env
.env.*
*credentials*
*.pem

# Python
__pycache__/
*.py[cod]
*.pyo
.Python
.mypy_cache/
.pytest_cache/
.ruff_cache/

# Local runtime cache
cache/
data/

# Generated portable packages
*.zip

# OS / editor
.DS_Store
*.swp
.idea/
.vscode/

# Note: quickjobs.david.profile.json IS tracked here (public placeholder only).
# The private repo gitignores the real personal profile.
EOF

cp -f "${EXAMPLE_PROFILE}" "${PUBLIC_DIR}/quickjobs.david.profile.json"

"${PY}" "${PRIVATE_DIR}/scripts/_shared/apply_public_stubs.py" --public-dir "${PUBLIC_DIR}"
"${PY}" "${PRIVATE_DIR}/scripts/_shared/sanitize_public_tree.py" --public-dir "${PUBLIC_DIR}"

echo "Synced private → public: ${PUBLIC_DIR}"
echo "Placeholder profile installed; stubs + personal scrub applied."
echo "Review, commit, and push from ${PUBLIC_DIR} with your own gh auth."
