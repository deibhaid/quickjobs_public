#!/usr/bin/env bash
# Publish the public quickjobs tree, then draft the next GitHub release.
#
# Runs (unless skipped):
#   1. sync_public_repo.sh  (private → public: stub, scrub, rename stem, assert)
#   2. git add/commit       (if the public tree has changes)
#   3. git push             (origin current branch)
#   4. draft-release        (tag + gh draft on YOUR_GITHUB_USER/quickjobs_public)
#
# Mac-only: uses your personal gh/git auth. Agents must not run this for you.
#
# Installed copy: ~/local/bin/quickjobs-server/draft-release-public
set -euo pipefail

SERVER_BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${HOME}/local/bin/quickjobs-server/lib/output.sh" ]]; then
  # shellcheck source=/dev/null
  source "${HOME}/local/bin/quickjobs-server/lib/output.sh"
elif [[ -f "${SERVER_BIN}/lib/output.sh" ]]; then
  # shellcheck source=/dev/null
  source "${SERVER_BIN}/lib/output.sh"
fi

PRIVATE_DIR="${QUICKJOBS_DIR:-${HOME}/ws/github/quickjobs}"
PUBLIC_DIR="${QUICKJOBS_PUBLIC_DIR:-${HOME}/ws/github/quickjobs_public}"
SYNC_SCRIPT="${PRIVATE_DIR}/scripts/_shared/sync_public_repo.sh"
DRAFT_RELEASE="${SERVER_BIN}/draft-release"
if [[ ! -x "${DRAFT_RELEASE}" && -x "${PRIVATE_DIR}/scripts/_shared/draft-release.sh" ]]; then
  DRAFT_RELEASE="${PRIVATE_DIR}/scripts/_shared/draft-release.sh"
fi

DRY_RUN=0
NO_SYNC=0
NO_COMMIT=0
NO_PUSH=0
DRAFT_ARGS=()

usage() {
  cat <<'EOF'
Usage: quickjobs draft_public [options]

  Sync private → public, commit + push the public tree, then draft the next
  GitHub release on YOUR_GITHUB_USER/quickjobs_public (same tenths rules as draft).

Options:
  --dry-run         Show sync/commit/push/draft plan; do not change remotes
  --no-sync         Skip sync_public_repo.sh (use current public working tree)
  --no-commit       Do not git commit (fail if the public tree is dirty)
  --no-push         Do not git push (still creates local tag + draft if possible)
  --notes-file PATH Passed through to draft-release
  --no-commit-notes Passed through to draft-release
  --no-tag          Passed through to draft-release
  -h, --help        Show this help

Examples:
  quickjobs draft_public --dry-run
  quickjobs draft_public
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
    -h|--help) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; DRAFT_ARGS+=(--dry-run); shift ;;
    --no-sync) NO_SYNC=1; shift ;;
    --no-commit) NO_COMMIT=1; shift ;;
    --no-push) NO_PUSH=1; shift ;;
    --notes-file)
      [[ -n "${2:-}" ]] || { log_err "quickjobs draft_public: --notes-file needs a path"; exit 1; }
      DRAFT_ARGS+=(--notes-file "${2}")
      shift 2
      ;;
    --no-commit-notes) DRAFT_ARGS+=(--no-commit-notes); shift ;;
    --no-tag) DRAFT_ARGS+=(--no-tag); shift ;;
    *)
      log_err "quickjobs draft_public: unknown argument: ${1}"
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "${PUBLIC_DIR}/.git" ]]; then
  log_err "quickjobs draft_public: public git dir missing: ${PUBLIC_DIR}"
  exit 1
fi

if [[ "${NO_SYNC}" -eq 0 ]]; then
  if [[ ! -x "${SYNC_SCRIPT}" ]]; then
    log_err "quickjobs draft_public: sync script missing: ${SYNC_SCRIPT}"
    exit 1
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "Would sync: ${SYNC_SCRIPT}"
    "${SYNC_SCRIPT}" --dry-run
  else
    log "Syncing private → public …"
    QUICKJOBS_DIR="${PRIVATE_DIR}" QUICKJOBS_PUBLIC_DIR="${PUBLIC_DIR}" \
      "${SYNC_SCRIPT}"
  fi
else
  log "Skipping sync (--no-sync)"
fi

# Working tree status after sync (or current tree if --no-sync / dry-run skipped writes).
dirty=0
if [[ -n "$(git -C "${PUBLIC_DIR}" status --porcelain 2>/dev/null)" ]]; then
  dirty=1
fi

if [[ "${dirty}" -eq 1 ]]; then
  log "Public tree has local changes"
  git -C "${PUBLIC_DIR}" status -sb
  if [[ "${NO_COMMIT}" -eq 1 ]]; then
    log_err "quickjobs draft_public: public tree is dirty and --no-commit was set"
    exit 1
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "Would commit all changes in ${PUBLIC_DIR}"
  else
    git -C "${PUBLIC_DIR}" add -A
    if [[ -n "$(git -C "${PUBLIC_DIR}" status --porcelain)" ]]; then
      git -C "${PUBLIC_DIR}" commit -m "$(cat <<'EOF'
Sync shareable tree from private (scrubbed, neutral stem).

EOF
)"
      log "Committed public tree changes"
    else
      log "Nothing to commit after staging"
    fi
  fi
else
  log "Public tree clean (nothing to commit)"
fi

branch="$(git -C "${PUBLIC_DIR}" rev-parse --abbrev-ref HEAD)"
needs_push=0
if ! git -C "${PUBLIC_DIR}" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  needs_push=1
else
  ahead="$(git -C "${PUBLIC_DIR}" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"
  if [[ "${ahead}" != "0" ]]; then
    needs_push=1
  fi
fi

if [[ "${NO_PUSH}" -eq 1 ]]; then
  log "Skipping push (--no-push)"
elif [[ "${needs_push}" -eq 1 ]] || [[ "${DRY_RUN}" -eq 1 && "${dirty}" -eq 1 ]]; then
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "Would push: git -C ${PUBLIC_DIR} push -u origin ${branch}"
  else
    log "Pushing ${branch} to origin …"
    git -C "${PUBLIC_DIR}" push -u origin "${branch}"
    log "Pushed origin/${branch}"
  fi
else
  log "Remote already up to date"
fi

export QUICKJOBS_GITHUB_REPO="${QUICKJOBS_GITHUB_REPO:-YOUR_GITHUB_USER/quickjobs_public}"
export QUICKJOBS_DIR="${PUBLIC_DIR}"

if [[ ! -x "${DRAFT_RELEASE}" ]]; then
  log_err "quickjobs draft_public: draft-release missing: ${DRAFT_RELEASE}"
  exit 1
fi

log "Drafting release for ${QUICKJOBS_GITHUB_REPO} …"
exec "${DRAFT_RELEASE}" "${DRAFT_ARGS[@]+"${DRAFT_ARGS[@]}"}"
