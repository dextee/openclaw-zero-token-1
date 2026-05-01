#!/usr/bin/env bash
set -euo pipefail

PORTAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="sg-portal"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
VENV_DIR="${PORTAL_DIR}/.venv"
DEFAULT_PORT="3030"

echo "=== SG Pipeline Portal Installer ==="

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --quiet -r "${PORTAL_DIR}/requirements.txt"

read -rp "Username [admin]: " PORTAL_USERNAME
PORTAL_USERNAME="${PORTAL_USERNAME:-admin}"

while true; do
  read -rsp "Password: " PORTAL_PASSWORD
  echo ""
  read -rsp "Confirm password: " PORTAL_PASSWORD2
  echo ""
  [[ "${PORTAL_PASSWORD}" == "${PORTAL_PASSWORD2}" ]] && break
  echo "Passwords do not match. Try again."
done

PORTAL_PASSWORD_HASH=$(
  "${VENV_DIR}/bin/python3" -c "
import sys
sys.path.insert(0, '${PORTAL_DIR}')
from auth import hash_password
print(hash_password('${PORTAL_PASSWORD}'))
"
)

read -rp "Port [${DEFAULT_PORT}]: " PORTAL_PORT
PORTAL_PORT="${PORTAL_PORT:-${DEFAULT_PORT}}"

CSRF_SECRET=$(openssl rand -hex 32)

sudo tee "${SERVICE_FILE}" > /dev/null << EOF
[Unit]
Description=SG Pipeline Portal
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${PORTAL_DIR}
ExecStart=${VENV_DIR}/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port ${PORTAL_PORT} --no-access-log
Restart=on-failure
RestartSec=5
Environment=PORTAL_USERNAME=${PORTAL_USERNAME}
Environment=PORTAL_PASSWORD_HASH=${PORTAL_PASSWORD_HASH}
Environment=PORTAL_PORT=${PORTAL_PORT}
Environment=PORTAL_CSRF_SECRET=${CSRF_SECRET}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "=== Done! Portal at: http://$(hostname -I | awk '{print $1}'):${PORTAL_PORT} ==="
echo "Commands: systemctl status ${SERVICE_NAME} | journalctl -u ${SERVICE_NAME} -f"
