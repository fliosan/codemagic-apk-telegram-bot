#!/usr/bin/env bash
#
# Deploy the Codemagic->Slack->Telegram bot to alwaysdata.
#
# Run this from your Mac, from inside the bot folder:
#     bash deploy/alwaysdata_deploy.sh
#
# It uploads the code, builds a virtualenv on the server, and installs deps.
# You'll be asked for your alwaysdata SSH password once (unless you've already
# installed the deploy key — see STEP 0 below).
#
# Configure via environment variables (or edit the defaults below):
#     ADATA_USER=myuser ADATA_HOST=ssh-myuser.alwaysdata.net \
#       bash deploy/alwaysdata_deploy.sh
#
# STEP 0 (optional, one time — lets everything after run password-free):
#     ssh-copy-id -i ~/.ssh/alwaysdata_deploy.pub "$ADATA_USER@$ADATA_HOST"
#
# After this script finishes, create the keep-alive Service in the alwaysdata
# panel (see deploy/alwaysdata_process.md), and set the tokens.

set -euo pipefail

SSH_USER="${ADATA_USER:?set ADATA_USER to your alwaysdata SSH user}"
SSH_HOST="${ADATA_HOST:-ssh-${SSH_USER}.alwaysdata.net}"
REMOTE_DIR="${ADATA_DIR:-/home/${SSH_USER}/codemagic-apk-telegram-bot}"
KEY="${ADATA_KEY:-$HOME/.ssh/alwaysdata_${SSH_USER}}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Use the deploy key if it's been installed; otherwise fall back to password.
SSH_OPTS=()
[ -f "$KEY" ] && SSH_OPTS=(-i "$KEY")

echo "==> Uploading bot to ${SSH_USER}@${SSH_HOST}:${REMOTE_DIR}"
rsync -az --delete \
  -e "ssh ${SSH_OPTS[*]}" \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.env' --exclude '*.apk' \
  "$SRC_DIR"/ "${SSH_USER}@${SSH_HOST}:${REMOTE_DIR}/"

echo "==> Building virtualenv + installing deps on the server"
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" bash -s <<REMOTE
set -euo pipefail
cd "${REMOTE_DIR}"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
# Create .env from template if missing (tokens filled in later).
[ -f .env ] || cp .env.example .env
echo "Remote setup done. Python: \$(./.venv/bin/python --version)"
REMOTE

echo
echo "==> Code is deployed. Next:"
echo "   1. Set your tokens:   ssh ${SSH_OPTS[*]} ${SSH_USER}@${SSH_HOST} nano ${REMOTE_DIR}/.env"
echo "   2. Create the keep-alive Site in the panel — see deploy/alwaysdata_process.md"
