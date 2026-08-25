#!/usr/bin/env bash
# Bootstrap a freshly cloned public quickjobs tree (venv + deps + validate).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

PY_SYS="${PYTHON:-python3}"
VENV="${ROOT}/.venv"
PIP="${VENV}/bin/pip"
PY="${VENV}/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "Creating ${VENV} ..."
  "${PY_SYS}" -m venv "${VENV}"
fi

echo "Installing requirements ..."
"${PIP}" install -U pip
"${PIP}" install -r "${ROOT}/requirements.txt"
echo "Installing Playwright Chromium ..."
"${PY}" -m playwright install chromium

echo "Validating static config ..."
"${PY}" "${ROOT}/quickjobs.david.py" validate-static-config --dir "${ROOT}"

echo
echo "Bootstrap OK."
echo "Activate:  source ${VENV}/bin/activate"
echo "Try:       python quickjobs.david.py --only remotive,remoteok"
echo "Docs:      GETTING_STARTED.md"
