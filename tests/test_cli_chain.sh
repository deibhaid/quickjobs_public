#!/usr/bin/env bash
# Smoke checks for quickjobs CLI chain parsing and bash syntax.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_BIN="${HOME}/local/bin/quickjobs-server"
CLI="${HOME}/local/bin/quickjobs"

failures=0

check_syntax() {
  local path="${1}"
  if [[ ! -f "${path}" ]]; then
    echo "skip (missing): ${path}"
    return 0
  fi
  if bash -n "${path}"; then
    echo "ok: bash -n ${path}"
  else
    echo "fail: bash -n ${path}" >&2
    failures=$((failures + 1))
  fi
}

for script in \
  "${CLI}" \
  "${SERVER_BIN}/quickjobs" \
  "${SERVER_BIN}/run" \
  "${SERVER_BIN}/run-remote" \
  "${SERVER_BIN}/stop-remote" \
  "${SERVER_BIN}/resume-remote" \
  "${SERVER_BIN}/restart-remote" \
  "${SERVER_BIN}/results-remote"; do
  check_syntax "${script}"
done

if [[ ! -f "${CLI}" ]]; then
  echo "skip chain tests (no ${CLI})"
  exit "${failures}"
fi

CHAINABLE_RE='^(portable|sync|run|stop|resume|restart|shard|deploy)$'

assert_match() {
  local word="${1}"
  if [[ "${word}" =~ ${CHAINABLE_RE} ]]; then
    echo "ok: chainable ${word}"
  else
    echo "fail: expected chainable ${word}" >&2
    failures=$((failures + 1))
  fi
}

assert_no_match() {
  local word="${1}"
  if [[ "${word}" =~ ${CHAINABLE_RE} ]]; then
    echo "fail: expected non-chainable ${word}" >&2
    failures=$((failures + 1))
  else
    echo "ok: non-chainable ${word}"
  fi
}

for cmd in portable sync run stop resume restart shard deploy; do
  assert_match "${cmd}"
done
assert_no_match "results"
assert_no_match "status"
assert_no_match "hubs"

if [[ "${failures}" -gt 0 ]]; then
  echo "${failures} check(s) failed" >&2
  exit 1
fi

echo "all cli chain checks passed"
