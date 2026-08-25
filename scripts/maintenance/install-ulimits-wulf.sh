#!/usr/bin/env bash
# Install permanent higher open-file limits on wulf (run once: sudo bash install-ulimits-wulf.sh).
set -euo pipefail

LIMITS_FILE="/etc/security/limits.d/99-dawib-nofile.conf"
SYSTEMD_DROPIN_DIR="/etc/systemd/system/user-.slice.d"
SYSTEMD_DROPIN="${SYSTEMD_DROPIN_DIR}/nofile.conf"
TARGET=65536

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi

install -d -m 0755 /etc/security/limits.d
cat >"${LIMITS_FILE}" <<EOF
# quickjobs / Playwright / tail -f on wulf (installed by install-ulimits-wulf.sh)
dawib soft nofile ${TARGET}
dawib hard nofile ${TARGET}
EOF
chmod 0644 "${LIMITS_FILE}"
echo "Wrote ${LIMITS_FILE}"

if systemctl --version >/dev/null 2>&1; then
  install -d -m 0755 "${SYSTEMD_DROPIN_DIR}"
  cat >"${SYSTEMD_DROPIN}" <<EOF
[Slice]
DefaultLimitNOFILE=${TARGET}
EOF
  chmod 0644 "${SYSTEMD_DROPIN}"
  systemctl daemon-reload 2>/dev/null || true
  echo "Wrote ${SYSTEMD_DROPIN} (user sessions / systemd units)"
fi

echo "Done. Log out and SSH in again, then check: ulimit -n"
echo "Expected soft limit: ${TARGET}"
