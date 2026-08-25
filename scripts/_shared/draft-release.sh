#!/usr/bin/env bash
# Draft the next GitHub release for quickjobs (tenths versioning).
# Mac-only: uses your personal `gh` auth. Agents must not run this for you.
#
# Installed copy: ~/local/bin/quickjobs-server/draft-release
# (keep in sync when editing).
#
# Versioning (see github-releases.mdc):
#   Highest existing release (published or draft) + one tenths bump.
#   0.0.9 → 0.1.0 → 0.1.1 … → 0.1.9 → 0.2.0
#   Tag: vX.Y.Z   Title: X.Y.Z (no leading v)
#
# Notes cover commits since the previous release (draft or published), not only
# the last published tag. Drafts also create/push the git tag so the next draft
# has a real baseline (and the release URL is not untagged-…).
set -euo pipefail

SERVER_BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# When run from repo scripts/_shared, prefer sibling server lib if present.
if [[ -f "${HOME}/local/bin/quickjobs-server/lib/output.sh" ]]; then
  # shellcheck source=/dev/null
  source "${HOME}/local/bin/quickjobs-server/lib/output.sh"
elif [[ -f "${SERVER_BIN}/lib/output.sh" ]]; then
  # shellcheck source=/dev/null
  source "${SERVER_BIN}/lib/output.sh"
fi

REPO="${QUICKJOBS_GITHUB_REPO:-YOUR_GITHUB_USER/quickjobs}"
REPO_DIR="${QUICKJOBS_DIR:-${HOME}/ws/github/quickjobs}"
DRY_RUN=0
NOTES_FILE=""
NOTES_FROM_COMMITS=1
SKIP_TAG=0

usage() {
  cat <<'EOF'
Usage: quickjobs draft [--dry-run] [--notes-file PATH] [--no-commit-notes] [--no-tag]

  Create a GitHub draft release at the next tenths version after the highest
  existing release (published or draft).

  Tag:   vX.Y.Z (created and pushed at draft time unless --no-tag)
  Title: X.Y.Z
  Notes: git commits since the previous release (draft or published)

Options:
  --dry-run         Print next version + notes; do not create the release
  --notes-file PATH Use this file as release notes (skip auto git log)
  --no-commit-notes Skip git log; use a short placeholder body
  --no-tag          Do not create/push a git tag (legacy untagged draft URL)
  -h, --help        Show this help

Examples:
  quickjobs draft --dry-run
  quickjobs draft
  quickjobs draft --notes-file /tmp/notes.md
EOF
}

log() {
  if declare -F qj_log >/dev/null 2>&1; then
    qj_log "${1}"
  else
    echo "${1}"
  fi
}

log_err() {
  if declare -F qj_log_stderr >/dev/null 2>&1; then
    qj_log_stderr "${1}"
  else
    echo "${1}" >&2
  fi
}

while [[ "${#}" -gt 0 ]]; do
  case "${1}" in
    -h|--help)
      usage
      exit 0
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --notes-file)
      NOTES_FILE="${2:-}"
      [[ -n "${NOTES_FILE}" ]] || { log_err "quickjobs draft: --notes-file needs a path"; exit 1; }
      shift 2
      ;;
    --no-commit-notes)
      NOTES_FROM_COMMITS=0
      shift
      ;;
    --no-tag)
      SKIP_TAG=1
      shift
      ;;
    *)
      log_err "quickjobs draft: unknown argument: ${1}"
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  log_err "quickjobs draft: gh not found (install GitHub CLI)"
  exit 1
fi

PY="${HOME}/.v/bin/python"
[[ -x "${PY}" ]] || PY="$(command -v python3)"
if [[ -z "${PY}" ]]; then
  log_err "quickjobs draft: python3 not found"
  exit 1
fi

mapfile -t RAW_TAGS < <(
  gh release list --repo "${REPO}" --limit 100 --json tagName \
    --jq '.[].tagName' 2>/dev/null || true
)

eval "$(
  "${PY}" - "${RAW_TAGS[@]:-}" <<'PY'
import re
import sys

def parse(tag: str):
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (tag or "").strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())

versions = []
for raw in sys.argv[1:]:
    if not raw:
        continue
    parsed = parse(raw)
    if parsed is None:
        continue
    tag = raw if raw.startswith("v") else f"v{raw}"
    versions.append((parsed, tag))

if not versions:
    print('HIGHEST=""')
    print('HIGHEST_TAG=""')
    print('NEXT_VERSION="0.0.1"')
    raise SystemExit(0)

versions.sort(key=lambda item: item[0])
(major, minor, patch), highest_tag = versions[-1]
if patch >= 9:
    next_major, next_minor, next_patch = major, minor + 1, 0
else:
    next_major, next_minor, next_patch = major, minor, patch + 1

print(f'HIGHEST="{major}.{minor}.{patch}"')
print(f'HIGHEST_TAG="{highest_tag}"')
print(f'NEXT_VERSION="{next_major}.{next_minor}.{next_patch}"')
PY
)"

NEXT_TAG="v${NEXT_VERSION}"

if gh release view "${NEXT_TAG}" --repo "${REPO}" >/dev/null 2>&1; then
  log_err "quickjobs draft: ${NEXT_TAG} already exists — publish or delete it first"
  exit 1
fi

PUBLISHED_TAG="$(
  gh release list --repo "${REPO}" --limit 100 --json tagName,isDraft \
    --jq '[.[] | select(.isDraft == false) | .tagName] | .[0]' 2>/dev/null || true
)"
PUBLISHED_TAG="${PUBLISHED_TAG//\"/}"

HIGHEST_CREATED=""
if [[ -n "${HIGHEST_TAG}" ]]; then
  HIGHEST_CREATED="$(
    gh release view "${HIGHEST_TAG}" --repo "${REPO}" --json createdAt --jq .createdAt 2>/dev/null || true
  )"
  HIGHEST_CREATED="${HIGHEST_CREATED//\"/}"
fi

NOTES_TMP="$(mktemp "${TMPDIR:-/tmp}/quickjobs-draft-notes.XXXXXX")"
cleanup() { rm -f "${NOTES_TMP}"; }
trap cleanup EXIT

NOTES_BASELINE_LABEL=""
NOTES_RANGE_MODE=""

if [[ -n "${NOTES_FILE}" ]]; then
  [[ -f "${NOTES_FILE}" ]] || { log_err "quickjobs draft: notes file not found: ${NOTES_FILE}"; exit 1; }
  cp "${NOTES_FILE}" "${NOTES_TMP}"
elif [[ "${NOTES_FROM_COMMITS}" -eq 1 && -d "${REPO_DIR}/.git" ]]; then
  RANGE_START=""
  SINCE_DATE=""
  # Prefer previous release (draft or published) over "latest published only",
  # otherwise every draft repeats the same commit list since v0.0.2.
  if [[ -n "${HIGHEST_TAG}" ]] && git -C "${REPO_DIR}" rev-parse --verify "${HIGHEST_TAG}^{commit}" >/dev/null 2>&1; then
    RANGE_START="${HIGHEST_TAG}"
    NOTES_BASELINE_LABEL="${HIGHEST_TAG} (previous release tag)"
    NOTES_RANGE_MODE="tag"
  elif [[ -n "${HIGHEST_CREATED}" ]]; then
    SINCE_DATE="${HIGHEST_CREATED}"
    NOTES_BASELINE_LABEL="${HIGHEST_TAG:-previous} @ ${HIGHEST_CREATED} (no git tag yet)"
    NOTES_RANGE_MODE="since"
  elif [[ -n "${PUBLISHED_TAG}" ]] && git -C "${REPO_DIR}" rev-parse --verify "${PUBLISHED_TAG}^{commit}" >/dev/null 2>&1; then
    RANGE_START="${PUBLISHED_TAG}"
    NOTES_BASELINE_LABEL="${PUBLISHED_TAG} (latest published tag)"
    NOTES_RANGE_MODE="tag"
  fi
  {
    echo "## Summary"
    echo
    if [[ "${NOTES_RANGE_MODE}" == "tag" && -n "${RANGE_START}" ]]; then
      git -C "${REPO_DIR}" log --reverse --pretty=format:'- %s' "${RANGE_START}..HEAD"
      echo
      echo
      echo "_Commits since ${RANGE_START}._"
    elif [[ "${NOTES_RANGE_MODE}" == "since" && -n "${SINCE_DATE}" ]]; then
      git -C "${REPO_DIR}" log --reverse --pretty=format:'- %s' --since="${SINCE_DATE}"
      echo
      echo
      echo "_Commits since previous release ${HIGHEST_TAG} (${SINCE_DATE})._"
    else
      git -C "${REPO_DIR}" log --reverse --pretty=format:'- %s' -n 40
      echo
      echo
      echo "_Recent commits (no previous-release baseline found)._"
    fi
    echo
    echo "## Validation"
    echo
    echo "- [ ] Board rebuild / scrape checks as needed"
    echo
  } >"${NOTES_TMP}"
else
  cat >"${NOTES_TMP}" <<EOF
## Summary

- (edit release notes)

## Validation

- [ ] Board rebuild / scrape checks as needed
EOF
fi

log "Highest existing: ${HIGHEST:-none} (${HIGHEST_TAG:-})"
log "Next draft:       ${NEXT_VERSION}  (tag ${NEXT_TAG})"
if [[ -n "${NOTES_BASELINE_LABEL}" ]]; then
  log "Notes baseline:   ${NOTES_BASELINE_LABEL}"
elif [[ -n "${PUBLISHED_TAG}" ]]; then
  log "Latest published: ${PUBLISHED_TAG}"
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo
  echo "----- notes -----"
  cat "${NOTES_TMP}"
  echo "----- end -----"
  echo
  if [[ "${SKIP_TAG}" -eq 0 ]]; then
    cat <<EOF
# Would run:
git -C ${REPO_DIR} tag -a ${NEXT_TAG} -m "quickjobs ${NEXT_VERSION}"
git -C ${REPO_DIR} push origin ${NEXT_TAG}
gh release create ${NEXT_TAG} \\
  --repo ${REPO} \\
  --title "${NEXT_VERSION}" \\
  --draft \\
  --notes-file <generated-notes>
EOF
  else
    cat <<EOF
# Would run:
gh release create ${NEXT_TAG} \\
  --repo ${REPO} \\
  --title "${NEXT_VERSION}" \\
  --draft \\
  --notes-file <generated-notes>
EOF
  fi
  exit 0
fi

if [[ "${SKIP_TAG}" -eq 0 ]]; then
  if [[ ! -d "${REPO_DIR}/.git" ]]; then
    log_err "quickjobs draft: repo dir missing git: ${REPO_DIR}"
    exit 1
  fi
  if git -C "${REPO_DIR}" rev-parse --verify "${NEXT_TAG}^{commit}" >/dev/null 2>&1; then
    log "Git tag already exists: ${NEXT_TAG}"
  else
    git -C "${REPO_DIR}" tag -a "${NEXT_TAG}" -m "quickjobs ${NEXT_VERSION}"
    log "Created git tag: ${NEXT_TAG}"
  fi
  git -C "${REPO_DIR}" push origin "${NEXT_TAG}"
  log "Pushed git tag: ${NEXT_TAG}"
fi

gh release create "${NEXT_TAG}" \
  --repo "${REPO}" \
  --title "${NEXT_VERSION}" \
  --draft \
  --notes-file "${NOTES_TMP}"

URL="$(gh release view "${NEXT_TAG}" --repo "${REPO}" --json url --jq .url 2>/dev/null || true)"
log "Draft created: ${NEXT_VERSION}"
if [[ -n "${URL}" ]]; then
  log "URL: ${URL}"
fi
