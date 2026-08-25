#!/usr/bin/env bash
# Run one quickjobs pipeline step in isolation (see step-isolation-runbook.md).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPORTS_DIR="${HOME}/ws/scriptdir/output/quickjobs-reports"
TIMING_PY="${HOME}/.v/bin/python"
BASELINES="${SCRIPT_DIR}/timing-baselines.yaml"
CHECK_TIMING="${SCRIPT_DIR}/check_run_timing.py"
SYNC_REMOTE="${HOME}/local/bin/quickjobs-server/sync-remote"
QUICKJOBS_DIR="${REPO_ROOT}"
SSH_PORT="${QUICKJOBS_SSH_PORT:-222}"
REMOTE_USER="${QUICKJOBS_REMOTE_USER:-user}"
REMOTE_HOST="${QUICKJOBS_REMOTE_HOST:-remote.example}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
SSH_OPTS="-p ${SSH_PORT} -o ConnectTimeout=15"

mkdir -p "${REPORTS_DIR}"

ts_utc() { date -u '+%Y-%m-%dT%H%M%SZ'; }

STEP_LOG=""
STEP_RC=0
TIMING_LOG=""
TIMING_STATUS=""
RESULT="FAIL"

log() { printf '%s\n' "$*" | tee -a "${STEP_LOG}"; }

init_step_log() {
  local name="$1"
  STEP_LOG="${REPORTS_DIR}/step-${name}-$(ts_utc).log"
  : >"${STEP_LOG}"
  log "step: ${name}"
  log "started: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  log "host: $(hostname)"
  log "---"
}

remote_ssh() {
  ssh ${SSH_OPTS} "${REMOTE}" "$@"
}

wulf_scrape_running() {
  remote_ssh 'pgrep -f quickjobs\.py >/dev/null 2>&1'
}

scrape_guard() {
  if [[ "${QUICKJOBS_ISOLATION_FORCE:-0}" == "1" ]]; then
    log "scrape_guard: QUICKJOBS_ISOLATION_FORCE=1 (skipping lock check)"
    return 0
  fi
  if wulf_scrape_running; then
    log "FAIL: remote quickjobs.py already running (see quickjobs results)"
    log "Stop the stuck run or set QUICKJOBS_ISOLATION_FORCE=1 to override."
    return 1
  fi
  return 0
}

# All 25 Playwright-browser company ids (Jun 2026 profile).
PW_EXCLUDE_ARGS=(
  --exclude alaska-airlines --exclude alaska-airlines-it --exclude american-airlines
  --exclude atlas-air --exclude avelo-airlines --exclude breeze-airways --exclude cisco
  --exclude delta-air-lines --exclude frontier-airlines --exclude google
  --exclude hawaiian-airlines --exclude ibm --exclude meta --exclude microsoft
  --exclude nike --exclude nvidia --exclude ohsu --exclude pilotsglobal-us
  --exclude rivian --exclude saic --exclude schwab --exclude skywest-airlines
  --exclude spirit-airlines --exclude statefarm --exclude sun-country-airlines
)

PW_ONLY_ARGS=(
  --only alaska-airlines --only alaska-airlines-it --only american-airlines
  --only atlas-air --only avelo-airlines --only breeze-airways --only cisco
  --only delta-air-lines --only frontier-airlines --only google
  --only hawaiian-airlines --only ibm --only meta --only microsoft
  --only nike --only nvidia --only ohsu --only pilotsglobal-us
  --only rivian --only saic --only schwab --only skywest-airlines
  --only spirit-airlines --only statefarm --only sun-country-airlines
)

STALL_BATCH_ARGS=(
  --only at-t --only autozone --only bae-systems
  --only baker-hughes --only baxter-international
)

HTTP_BATCH_ARGS=(
  --only bae-systems --only baker-hughes --only baxter-international
)

run_remote_scrape() {
  local workers="${1:-16}"
  shift
  scrape_guard || return 1
  log "remote scrape: QUICKJOBS_HTTP_WORKERS=${workers} $*"
  set +e
  QUICKJOBS_SYNC_BEFORE_RUN=0 QUICKJOBS_RUN_QUIET=1 \
    QUICKJOBS_HTTP_WORKERS="${workers}" \
    "${HOME}/local/bin/quickjobs-server/run-remote" "$@" 2>&1 | tee -a "${STEP_LOG}"
  local rc=${PIPESTATUS[0]}
  set -e
  return "${rc}"
}

fetch_latest_remote_run_log() {
  remote_ssh 'ls -t ~/ws/scriptdir/output/quickjobs-reports/quickjobs-run-*.log 2>/dev/null | head -1'
}

run_timing_check() {
  local log_path="${1:-}"
  if [[ -z "${log_path}" ]]; then
    log_path="$(fetch_latest_remote_run_log 2>/dev/null || true)"
  fi
  if [[ -z "${log_path}" ]]; then
    log "timing: no quickjobs-run log found (skip)"
    return 0
  fi
  TIMING_LOG="${log_path}"
  log "timing: ${log_path}"
  local out rc
  set +e
  out="$(remote_ssh "/home/user/.venv/bin/python ${CHECK_TIMING} --baselines ${BASELINES} ${log_path}" 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "${out}" >>"${STEP_LOG}"
  TIMING_STATUS="$(printf '%s\n' "${out}" | awk '/^overall:/ {print $2; exit}')"
  log "timing exit=${rc} overall=${TIMING_STATUS:-unknown}"
  return "${rc}"
}

finalize_result() {
  local step_rc="${1:-0}"
  STEP_RC="${step_rc}"
  if [[ "${step_rc}" -ne 0 ]]; then
    RESULT="FAIL"
  elif [[ -n "${TIMING_STATUS}" ]]; then
    case "${TIMING_STATUS}" in
      OK|RUNNING) RESULT="OK" ;;
      WARN) RESULT="WARN" ;;
      STALL|*) RESULT="FAIL" ;;
    esac
  else
    RESULT="OK"
  fi
  log "---"
  log "finished: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  log "step_log: ${STEP_LOG}"
  [[ -n "${TIMING_LOG}" ]] && log "scrape_log: ${TIMING_LOG}"
  log "RESULT: ${RESULT}"
  echo ""
  echo "RESULT: ${RESULT}  (log: ${STEP_LOG})"
  case "${RESULT}" in
    OK) return 0 ;;
    WARN) return 1 ;;
    *) return 2 ;;
  esac
}

step_portable() {
  init_step_log "portable"
  set +e
  QUICKJOBS_PORTABLE_QUIET=1 quickjobs portable 2>&1 | tee -a "${STEP_LOG}"
  STEP_RC=$?
  set -e
  if [[ "${STEP_RC}" -eq 0 && -f "${HOME}/ws/scriptdir/output/quickjobs-portable.zip" ]]; then
    log "zip: $(du -h "${HOME}/ws/scriptdir/output/quickjobs-portable.zip" | awk '{print $1}')"
  else
    STEP_RC=1
  fi
  finalize_result "${STEP_RC}"
}

step_ssh_ping() {
  init_step_log "ssh-ping"
  set +e
  remote_ssh 'echo OK; hostname; date -u' 2>&1 | tee -a "${STEP_LOG}"
  STEP_RC=$?
  set -e
  if [[ "${STEP_RC}" -eq 0 ]] && grep -q '^OK$' "${STEP_LOG}"; then
    finalize_result 0
  else
    finalize_result 1
  fi
}

step_sync_validate() {
  init_step_log "sync-validate"
  set +e
  "${TIMING_PY}" "${QUICKJOBS_DIR}/quickjobs.py" validate-static-config -q \
    --dir "${QUICKJOBS_DIR}" 2>&1 | tee -a "${STEP_LOG}"
  finalize_result $?
}

step_sync_code() {
  init_step_log "sync-code"
  local py="${TIMING_PY}"
  local remote_dir='~/ws/scriptdir/scripts/personal/quickjobs'
  set +e
  {
    "${py}" "${QUICKJOBS_DIR}/quickjobs.py" validate-static-config -q --dir "${QUICKJOBS_DIR}"
    remote_ssh "mkdir -p ${remote_dir}"
    rsync -az -e "ssh ${SSH_OPTS}" --delete \
      --include 'quickjobs.py' \
      --include 'quickjobs.base.json' \
      --include 'quickjobs.profile.json' \
      --include 'quickjobs.unconvertible-careers.json' \
      --include 'quickjobs.manual-career-meta.json' \
      --include 'run_log.py' \
      --include 'README.md' \
      --include 'portable/' \
      --include 'portable/quickjobs-favicon.png' \
      --include 'portable/quickjobs-apple-touch-icon.png' \
      --exclude '*' \
      "${QUICKJOBS_DIR}/" "${REMOTE}:${remote_dir}/"
  } 2>&1 | tee -a "${STEP_LOG}"
  finalize_result $?
}

step_sync_bins() {
  init_step_log "sync-bins"
  local server_bin="${HOME}/local/bin/quickjobs-server"
  set +e
  {
    remote_ssh 'mkdir -p ~/local/bin ~/local/bin/quickjobs-server/lib'
    for pair in "run:quickjobs-run" "run-shard:quickjobs-run-shard" "raise-nofile:quickjobs-raise-nofile"; do
      src="${server_bin}/${pair%%:*}"
      dst="${pair##*:}"
      [[ -f "${src}" ]] && rsync -az -e "ssh ${SSH_OPTS}" "${src}" "${REMOTE}:~/local/bin/${dst}"
    done
    for lib in output.sh dns.sh; do
      [[ -f "${server_bin}/lib/${lib}" ]] && \
        rsync -az -e "ssh ${SSH_OPTS}" "${server_bin}/lib/${lib}" \
          "${REMOTE}:~/local/bin/quickjobs-server/lib/${lib}"
    done
    remote_ssh 'chmod 755 ~/local/bin/quickjobs-run ~/local/bin/quickjobs-run-shard ~/local/bin/quickjobs-raise-nofile 2>/dev/null || true'
  } 2>&1 | tee -a "${STEP_LOG}"
  finalize_result $?
}

step_sync_pipeline() {
  init_step_log "sync-pipeline"
  local local_data="${HOME}/.job_search/quickjobs/quickjobs"
  local runtime="${local_data}/job-board-runtime.json"
  local remote_board='/mnt/Uploads/html/quickjobs'
  if [[ ! -f "${runtime}" ]]; then
    log "no runtime at ${runtime}"
    finalize_result 1
    return
  fi
  set +e
  {
    remote_ssh "mkdir -p '${remote_board}'"
    rsync -rltz --omit-dir-times --no-perms --no-owner --no-group \
      -e "ssh ${SSH_OPTS}" \
      "${runtime}" "${REMOTE}:${remote_board}/job-board-runtime.json"
  } 2>&1 | tee -a "${STEP_LOG}"
  finalize_result $?
}

step_sync_glassdoor() {
  init_step_log "sync-glassdoor"
  local src="${HOME}/.job_search/quickjobs/quickjobs/glassdoor"
  if [[ ! -d "${src}" ]]; then
    log "skip: no glassdoor cache at ${src}"
    finalize_result 0
    return
  fi
  set +e
  {
    remote_ssh "mkdir -p /mnt/Uploads/html/quickjobs/glassdoor"
    rsync -rltz --omit-dir-times --no-perms --no-owner --no-group \
      -e "ssh ${SSH_OPTS}" "${src}/" "${REMOTE}:/mnt/Uploads/html/quickjobs/glassdoor/"
  } 2>&1 | tee -a "${STEP_LOG}"
  finalize_result $?
}

step_sync_data() {
  init_step_log "sync-data"
  set +e
  QUICKJOBS_SYNC_PUSH_DATA=1 QUICKJOBS_SYNC_QUIET=1 quickjobs sync 2>&1 | tee -a "${STEP_LOG}"
  finalize_result $?
}

step_sync_full() {
  init_step_log "sync-full"
  set +e
  QUICKJOBS_SYNC_QUIET=1 quickjobs sync 2>&1 | tee -a "${STEP_LOG}"
  finalize_result $?
}

step_run_no_sync() {
  init_step_log "run-no-sync"
  scrape_guard || { finalize_result 1; return; }
  set +e
  QUICKJOBS_SYNC_BEFORE_RUN=0 QUICKJOBS_RUN_QUIET=1 quickjobs run 2>&1 | tee -a "${STEP_LOG}"
  STEP_RC=$?
  set -e
  run_timing_check || true
  finalize_result "${STEP_RC}"
}

step_only_company() {
  local cid="$1"
  init_step_log "only-${cid}"
  set +e
  run_remote_scrape 16 --only "${cid}"
  STEP_RC=$?
  set -e
  run_timing_check || true
  finalize_result "${STEP_RC}"
}

step_stall_batch() {
  init_step_log "stall-batch"
  set +e
  run_remote_scrape 16 "${STALL_BATCH_ARGS[@]}"
  STEP_RC=$?
  set -e
  run_timing_check || true
  finalize_result "${STEP_RC}"
}

step_http_workers_batch() {
  local workers="$1"
  local name="$2"
  init_step_log "${name}"
  set +e
  run_remote_scrape "${workers}" "${HTTP_BATCH_ARGS[@]}"
  STEP_RC=$?
  set -e
  run_timing_check || true
  finalize_result "${STEP_RC}"
}

step_http_all() {
  local workers="$1"
  local name="$2"
  init_step_log "${name}"
  set +e
  run_remote_scrape "${workers}" "${PW_EXCLUDE_ARGS[@]}"
  STEP_RC=$?
  set -e
  run_timing_check || true
  finalize_result "${STEP_RC}"
}

step_playwright_sample() {
  init_step_log "playwright-sample"
  set +e
  run_remote_scrape 8 --only nike --only microsoft --only google
  STEP_RC=$?
  set -e
  run_timing_check || true
  finalize_result "${STEP_RC}"
}

step_playwright_all() {
  init_step_log "playwright-all"
  set +e
  run_remote_scrape 8 "${PW_ONLY_ARGS[@]}"
  STEP_RC=$?
  set -e
  run_timing_check || true
  finalize_result "${STEP_RC}"
}

step_verify_small() {
  init_step_log "verify-small"
  scrape_guard || { finalize_result 1; return; }
  set +e
  QUICKJOBS_VERIFY_ALL=1 QUICKJOBS_VERIFY_WORKERS=4 QUICKJOBS_SYNC_BEFORE_RUN=0 \
    QUICKJOBS_RUN_QUIET=1 quickjobs run --only affirm --only coupa --only 1password 2>&1 | tee -a "${STEP_LOG}"
  STEP_RC=${PIPESTATUS[0]}
  set -e
  run_timing_check || true
  finalize_result "${STEP_RC}"
}

step_post_scrape_rebuild() {
  init_step_log "post-scrape-rebuild"
  set +e
  remote_ssh \
    'cd ~/ws/scriptdir/scripts/personal/quickjobs && \
     QUICKJOBS_JOBS_DIR=/mnt/Uploads/html JOB_SEARCH_DIR=/mnt/Uploads/html \
     ~/.v/bin/python quickjobs.py rebuild-snapshot' 2>&1 | tee -a "${STEP_LOG}"
  STEP_RC=$?
  set -e
  if [[ "${STEP_RC}" -eq 0 ]] && grep -q '^Wrote ' "${STEP_LOG}"; then
    finalize_result 0
  else
    finalize_result 1
  fi
}

step_check_stalled_log() {
  local stalled="${REPORTS_DIR}/quickjobs-run-2026-06-23T180936Z.log"
  init_step_log "check-stalled-log"
  if [[ ! -f "${stalled}" ]]; then
  # try fetch from remote
    set +e
    scp ${SSH_OPTS} "${REMOTE}:~/ws/scriptdir/output/quickjobs-reports/quickjobs-run-2026-06-23T180936Z.log" \
      "${stalled}" 2>&1 | tee -a "${STEP_LOG}"
    set -e
  fi
  if [[ ! -f "${stalled}" ]]; then
    log "missing stalled log"
    finalize_result 1
    return
  fi
  set +e
  "${TIMING_PY}" "${CHECK_TIMING}" --baselines "${BASELINES}" "${stalled}" 2>&1 | tee -a "${STEP_LOG}"
  set -e
  TIMING_LOG="${stalled}"
  TIMING_STATUS="$(awk '/^overall:/ {print $2; exit}' "${STEP_LOG}")"
  RESULT="${TIMING_STATUS:-FAIL}"
  log "---"
  log "finished: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  log "step_log: ${STEP_LOG}"
  log "scrape_log: ${TIMING_LOG}"
  log "RESULT: ${RESULT}"
  echo ""
  echo "RESULT: ${RESULT}  (log: ${STEP_LOG})"
  case "${RESULT}" in
    OK|RUNNING) return 0 ;;
    WARN) return 1 ;;
    *) return 2 ;;
  esac
}

print_list() {
  cat <<'EOF'
Steps (run: ./run_step_isolation.sh <name>):

  portable              Build portable zip (Mac)
  ssh-ping              SSH connectivity to remote
  sync-validate         Static config validate only
  sync-code             Rsync code/config to remote
  sync-bins             Rsync quickjobs-run wrappers to remote
  sync-pipeline         Push job-board-runtime.json
  sync-glassdoor        Push glassdoor cache
  sync-data             Sync with QUICKJOBS_SYNC_PUSH_DATA=1
  sync-full             Full quickjobs sync (default skip HTML)
  run-no-sync           Full board, QUICKJOBS_SYNC_BEFORE_RUN=0
  only-<id>             Single company --only on remote (e.g. only-bae-systems)
  stall-batch           Stall zone 5-company batch
  http-w1-batch         3-co batch, QUICKJOBS_HTTP_WORKERS=1
  http-w16-batch        3-co batch, QUICKJOBS_HTTP_WORKERS=16
  http-w1-all           All HTTP cos (excl. 25 pw), workers=1
  http-w16-all          All HTTP cos, workers=16
  playwright-sample     nike, microsoft, google
  playwright-all        All 25 Playwright companies
  verify-small          QUICKJOBS_VERIFY_ALL=1 on 3 HTTP companies
  post-scrape-rebuild   rebuild-snapshot on remote (no scrape)
  check-stalled-log     Timing check on 180936Z stalled run
  list                  This help

See step-isolation-runbook.md for pass criteria and expected durations.
EOF
}

main() {
  local step="${1:-list}"
  case "${step}" in
    list|-h|--help|help) print_list; exit 0 ;;
    portable) step_portable ;;
    ssh-ping) step_ssh_ping ;;
    sync-validate) step_sync_validate ;;
    sync-code) step_sync_code ;;
    sync-bins) step_sync_bins ;;
    sync-pipeline) step_sync_pipeline ;;
    sync-glassdoor) step_sync_glassdoor ;;
    sync-data) step_sync_data ;;
    sync-full) step_sync_full ;;
    run-no-sync) step_run_no_sync ;;
    only-*) step_only_company "${step#only-}" ;;
    stall-batch) step_stall_batch ;;
    http-w1-batch) step_http_workers_batch 1 "http-w1-batch" ;;
    http-w16-batch) step_http_workers_batch 16 "http-w16-batch" ;;
    http-w1-all) step_http_all 1 "http-w1-all" ;;
    http-w16-all) step_http_all 16 "http-w16-all" ;;
    playwright-sample) step_playwright_sample ;;
    playwright-all) step_playwright_all ;;
    verify-small) step_verify_small ;;
    post-scrape-rebuild) step_post_scrape_rebuild ;;
    check-stalled-log) step_check_stalled_log ;;
    *)
      echo "Unknown step: ${step}" >&2
      print_list >&2
      exit 2
      ;;
  esac
}

main "$@"
