#!/usr/bin/env bash
#
# One-shot installer for a fresh Debian/Ubuntu VPS.
# Run as root (or with sudo) FROM INSIDE the bot folder:
#
#   sudo bash deploy/setup.sh
#
# It will:
#   1. install python3 + venv
#   2. copy the bot to /opt/apkbot
#   3. create a dedicated 'apkbot' user
#   4. create a virtualenv + install requirements
#   5. install & start the systemd service
#
# Before running, make sure you've created /opt/apkbot/.env (or you'll be
# prompted to). See .env.example.

set -euo pipefail

APP_DIR=/opt/apkbot
SERVICE=apkbot
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Please run with sudo:  sudo bash deploy/setup.sh" >&2
  exit 1
fi

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync

echo "==> Creating service user 'apkbot'"
id -u apkbot &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin apkbot

echo "==> Copying app to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '*.apk' \
      "$SRC_DIR"/ "$APP_DIR"/

echo "==> Setting up virtualenv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "!!  No .env found — created one from the template."
  echo "!!  Edit it now:   sudo nano $APP_DIR/.env"
  echo "!!  Then re-run:   sudo systemctl restart $SERVICE"
fi

chown -R apkbot:apkbot "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "==> Installing systemd service"
cp "$APP_DIR/deploy/apkbot.service" "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

echo
echo "==> Done. Useful commands:"
echo "    systemctl status $SERVICE"
echo "    journalctl -u $SERVICE -f      # live logs"
echo "    sudo nano $APP_DIR/.env        # edit config, then: systemctl restart $SERVICE"
