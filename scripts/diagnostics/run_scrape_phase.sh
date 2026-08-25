#!/usr/bin/env bash
# Run isolated in-scrape-phase diagnostics (see scrape-phase-runbook.md).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BASELINES="${SCRIPT_DIR}/timing-baselines.yaml"
CHECK_TIMING="${SCRIPT_DIR}/check_run_timing.py"
LIST_POSITIONS="${SCRIPT_DIR}/list_scrape_positions.py"
LOG_DIR="${QUICKJOBS_PHASE_LOG_DIR:-${HOME}/ws/scriptdir/output/quickjobs-reports/phase-isolation}"
PYTHON="${QUICKJOBS_PYTHON:-${HOME}/.v/bin/python}"

SSH_HOST="${QUICKJOBS_SSH_HOST:-dawib@dawib.synology.me}"
SSH_PORT="${QUICKJOBS_SSH_PORT:-222}"
REMOTE=0
DRY_RUN=0

WINDOW_IDS=(
  arm-american
  at-t
  autozone
  bae-systems
  baker-hughes
  baxter-international
  becton-dickinson
  blackrock
  bny-mellon
)

usage() {
  cat <<'EOF'
Usage: run_scrape_phase.sh [--remote] [--dry-run] [--list-window] <test-name>

In-run scrape phase isolation tests. See scrape-phase-runbook.md.

Tests:
  list-window              Print companies at scrape positions 188-196
  window-188-196-single    One --only run per window company (verify off)
  window-188-196-batch     Single run with all window --only flags
  window-autozone          Bisect position 190 (oracle_hcm)
  window-autozone-verify-on  autozone with default URL verify
  window-autozone-workers-1  autozone, QUICKJOBS_HTTP_WORKERS=1
  phenom-pair              bae-systems + baker-hughes
  oracle-pair              autozone + bny-mellon
  talentbrew-triple        arm-american, at-t, baxter-international
  playwright-all           All Playwright-phase companies (verify off)
  playwright-single-cisco  Single PW company smoke
  verify-off-openai        Verify disabled smoke
  verify-on-openai         Verify enabled smoke
  post-rolling-backup      test-rolling-backup (no scrape)
  check-latest             check_run_timing on latest phase log

Options:
  --remote    Run quickjobs-run on wulf via ssh (default: local quickjobs-run)
  --dry-run   Print commands only
  --list-window  Same as test list-window

After each test, runs check_run_timing.py on the new log when available.
EOF
}

log() { printf '[phase] %s\n' "$*"; }

ensure_tools() {
  if [[ ! -x "${PYTHON}" ]]; then
    echo "Python not found: ${PYTHON}" >&2
    exit 1
  fi
  if [[ ! -f "${CHECK_TIMING}" ]]; then
    echo "Missing ${CHECK_TIMING}" >&2
    exit 1
  fi
  mkdir -p "${LOG_DIR}"
}

quickjobs_cmd() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    if [[ "${REMOTE}" -eq 1 ]]; then
      printf 'ssh -p %s %s quickjobs-run' "${SSH_PORT}" "${SSH_HOST}"
    else
      printf 'quickjobs-run'
    fi
    return 0
  fi
  if [[ "${REMOTE}" -eq 1 ]]; then
    printf 'ssh -p %s %s quickjobs-run' "${SSH_PORT}" "${SSH_HOST}"
  elif [[ -x "${HOME}/local/bin/quickjobs-run" ]]; then
    printf '%s' "${HOME}/local/bin/quickjobs-run"
  else
    echo "quickjobs-run not found (install to ~/local/bin or use --remote)" >&2
    exit 1
  fi
}

run_shell() {
  local label=$1
  shift
  local cmd=$*
  log "TEST ${label}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "  ${cmd}"
    return 0
  fi
  local start_ts
  start_ts=$(date -u +%Y-%m-%dT%H%M%SZ)
  local log_file="${LOG_DIR}/phase-${label}-${start_ts}.log"
  log "  log -> ${log_file}"
  # shellcheck disable=SC2086
  if eval "${cmd}" > >(tee "${log_file}") 2>&1; then
    log "  exit 0"
  else
    local rc=$?
    log "  exit ${rc}"
    check_log_timing "${log_file}" || true
    return "${rc}"
  fi
  check_log_timing "${log_file}"
}

check_log_timing() {
  local log_file=$1
  if [[ ! -s "${log_file}" ]]; then
    log "  timing: skip (empty log)"
    return 0
  fi
  log "  timing:"
  "${PYTHON}" "${CHECK_TIMING}" --baselines "${BASELINES}" "${log_file}" || true
}

only_flags() {
  local id
  for id in "$@"; do
    printf -- '--only %s ' "${id}"
  done
}

test_list_window() {
  "${PYTHON}" "${LIST_POSITIONS}" --start 188 --end 196
}

test_window_single() {
  local runner
  runner=$(quickjobs_cmd)
  local id rc=0
  for id in "${WINDOW_IDS[@]}"; do
    run_shell "only-${id}" \
      "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only ${id} --force-snapshot -q" \
      || rc=1
  done
  return "${rc}"
}

test_window_batch() {
  local runner flags
  runner=$(quickjobs_cmd)
  flags=$(only_flags "${WINDOW_IDS[@]}")
  # shellcheck disable=SC2086
  run_shell "window-batch" \
    "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} ${flags} --force-snapshot -q"
}

test_autozone() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "autozone" \
    "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only autozone --force-snapshot -q"
}

test_autozone_verify_on() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "autozone-verify-on" \
    "QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only autozone --force-snapshot -q"
}

test_autozone_workers_1() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "autozone-workers-1" \
    "QUICKJOBS_HTTP_WORKERS=1 QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only autozone --force-snapshot -q"
}

test_phenom_pair() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "phenom-pair" \
    "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only bae-systems --only baker-hughes --force-snapshot -q"
}

test_oracle_pair() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "oracle-pair" \
    "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only autozone --only bny-mellon --force-snapshot -q"
}

test_talentbrew_triple() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "talentbrew-triple" \
    "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only arm-american --only at-t --only baxter-international --force-snapshot -q"
}

test_playwright_all() {
  local runner flags id
  runner=$(quickjobs_cmd)
  flags=""
  while IFS= read -r id; do
    flags+=" --only ${id}"
  done < <("${PYTHON}" "${LIST_POSITIONS}" --playwright-only --ids-only)
  # shellcheck disable=SC2086
  run_shell "playwright-all" \
    "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} ${flags} --force-snapshot -q"
}

test_playwright_cisco() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "playwright-cisco" \
    "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only cisco --force-snapshot -q"
}

test_verify_off_openai() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "verify-off-openai" \
    "QUICKJOBS_VERIFY_ALL=0 QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only openai --force-snapshot -q"
}

test_verify_on_openai() {
  local runner
  runner=$(quickjobs_cmd)
  run_shell "verify-on-openai" \
    "QUICKJOBS_SYNC_BEFORE_RUN=0 ${runner} --only openai --force-snapshot -q"
}

test_post_rolling_backup() {
  run_shell "rolling-backup" \
    "${PYTHON} ${REPO_ROOT}/quickjobs.david.py test-rolling-backup -q"
}

test_check_latest() {
  local latest
  latest=$(ls -t "${LOG_DIR}"/phase-*.log 2>/dev/null | head -1 || true)
  if [[ -z "${latest}" ]]; then
    echo "No phase logs in ${LOG_DIR}" >&2
    return 1
  fi
  check_log_timing "${latest}"
}

main() {
  ensure_tools
  local test_name=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --remote) REMOTE=1; shift ;;
      --dry-run) DRY_RUN=1; shift ;;
      --list-window) test_list_window; exit 0 ;;
      -h|--help) usage; exit 0 ;;
      *) test_name=$1; shift; break ;;
    esac
  done

  if [[ -z "${test_name}" ]]; then
    usage >&2
    exit 1
  fi

  case "${test_name}" in
    list-window) test_list_window ;;
    window-188-196-single) test_window_single ;;
    window-188-196-batch) test_window_batch ;;
    window-autozone) test_autozone ;;
    window-autozone-verify-on) test_autozone_verify_on ;;
    window-autozone-workers-1) test_autozone_workers_1 ;;
    phenom-pair) test_phenom_pair ;;
    oracle-pair) test_oracle_pair ;;
    talentbrew-triple) test_talentbrew_triple ;;
    playwright-all) test_playwright_all ;;
    playwright-single-cisco) test_playwright_cisco ;;
    verify-off-openai) test_verify_off_openai ;;
    verify-on-openai) test_verify_on_openai ;;
    post-rolling-backup) test_post_rolling_backup ;;
    check-latest) test_check_latest ;;
    *)
      echo "Unknown test: ${test_name}" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
