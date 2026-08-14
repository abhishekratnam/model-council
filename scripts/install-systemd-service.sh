#!/usr/bin/env bash
# Install Model Council as a minimal systemd service bound to loopback only.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE="${APP_DIR}/deploy/model-council.service"
DESTINATION="/etc/systemd/system/model-council.service"

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "Service template not found: ${TEMPLATE}" >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -- "$0" "$@"
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemd is required to install the service." >&2
  exit 1
fi

APP_USER="${SUDO_USER:-${USER}}"
if ! id "${APP_USER}" >/dev/null 2>&1; then
  echo "Cannot determine the account that should run Model Council." >&2
  exit 1
fi

escaped_app_dir="$(printf '%s' "${APP_DIR}" | sed 's/[&|]/\\&/g')"
escaped_user="$(printf '%s' "${APP_USER}" | sed 's/[&|]/\\&/g')"
sed \
  -e "s|__APP_DIR__|${escaped_app_dir}|g" \
  -e "s|__APP_USER__|${escaped_user}|g" \
  "${TEMPLATE}" >"${DESTINATION}"

systemctl daemon-reload
systemctl enable --now model-council.service
systemctl --no-pager --full status model-council.service
