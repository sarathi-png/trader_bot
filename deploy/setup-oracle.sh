#!/usr/bin/env bash
# Bootstrap an Oracle Cloud Always Free Ubuntu VM for the Quotex Signal Bot.
#
# Idempotent: safe to re-run after code updates (reinstalls deps, restarts service).
#
# Prerequisites (do these first, see DEPLOY.md):
#   1. Project code copied to INSTALL_DIR, e.g.:
#        rsync -avz --exclude .venv --exclude data --exclude logs --exclude sessions \
#          ./ ubuntu@<VM-IP>:/opt/quotex-signal-bot/
#   2. A real .env created at INSTALL_DIR/.env (chmod 600).
#
# Usage:  sudo bash deploy/setup-oracle.sh [INSTALL_DIR] [SERVICE_USER]
# Example: sudo bash deploy/setup-oracle.sh /opt/quotex-signal-bot ubuntu
set -euo pipefail

INSTALL_DIR="${1:-/opt/quotex-signal-bot}"
SERVICE_USER="${2:-ubuntu}"
SERVICE_NAME="quotex-bot"
UNIT_SRC="$INSTALL_DIR/deploy/quotex-bot.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run as root (sudo bash deploy/setup-oracle.sh)" >&2
  exit 1
fi

if [[ ! -f "$INSTALL_DIR/run.py" ]]; then
  echo "ERROR: $INSTALL_DIR/run.py not found. Copy the project there first (see DEPLOY.md)." >&2
  exit 1
fi

echo "==> [1/7] Installing OS packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git sqlite3 curl build-essential cron > /dev/null
echo "    done."

echo "==> [2/7] Ensuring 4G swapfile (skipped if swap already active)..."
if ! swapon --show=NAME --noheadings | grep -q .; then
  fallocate -l 4G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none
  chmod 600 /swapfile
  mkswap /swapfile > /dev/null
  swapon /swapfile
  grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
  echo "    4G swapfile created and enabled."
else
  echo "    swap already active, skipping."
fi

echo "==> [3/7] Creating Python venv + installing requirements (as $SERVICE_USER)..."
sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/.venv" 2>/dev/null || true
sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
echo "    done."

echo "==> [4/7] Installing Playwright Chromium (shared store /ms-playwright)..."
mkdir -p /ms-playwright
# --with-deps pulls Chromium's OS libraries via apt; browsers land in
# PLAYWRIGHT_BROWSERS_PATH so the unprivileged service user can use them.
PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  "$INSTALL_DIR/.venv/bin/python" -m playwright install --with-deps chromium
chmod -R a+rX /ms-playwright
echo "    done."

echo "==> [5/7] Preparing state directories..."
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/sessions" "$INSTALL_DIR/logs"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/data" "$INSTALL_DIR/sessions" "$INSTALL_DIR/logs" /ms-playwright 2>/dev/null || true
if [[ -f "$INSTALL_DIR/.env" ]]; then
  chmod 600 "$INSTALL_DIR/.env"
else
  echo "    WARNING: $INSTALL_DIR/.env missing — create it before starting (see DEPLOY.md §4)."
fi

echo "==> [6/7] Installing systemd unit..."
sed -e "s|INSTALL_DIR|$INSTALL_DIR|g" -e "s|SERVICE_USER|$SERVICE_USER|g" \
  "$UNIT_SRC" > "$UNIT_DST"
systemctl daemon-reload
systemctl enable -q "$SERVICE_NAME"
echo "    installed -> $UNIT_DST"

echo "==> [7/7] Starting service..."
if [[ -f "$INSTALL_DIR/.env" ]]; then
  systemctl restart "$SERVICE_NAME"
  sleep 3
  systemctl --no-pager status "$SERVICE_NAME" | head -12
else
  echo "    skipped start (no .env). Run after creating .env:"
  echo "      sudo systemctl start $SERVICE_NAME"
fi

echo ""
echo "Next steps (DEPLOY.md):"
echo "  1. sudo journalctl -u $SERVICE_NAME -f        # watch startup"
echo "  2. /start the Telegram bot, run /status       # expect live/demo + connected"
echo "  3. Add cron healthcheck: (crontab -l; echo '*/5 * * * * $INSTALL_DIR/deploy/healthcheck.sh >> $INSTALL_DIR/logs/healthcheck.log 2>&1') | crontab -"
