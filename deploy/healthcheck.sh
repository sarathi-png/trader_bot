#!/usr/bin/env bash
# Stale-feed guard for the Quotex Signal Bot. Run from cron every 5 minutes:
#   */5 * * * * /opt/quotex-signal-bot/deploy/healthcheck.sh >> /opt/quotex-signal-bot/logs/healthcheck.log 2>&1
#
# Restarts the service when (a) systemd reports it down, or (b) logs/bot.log
# has not been written for STALE_SECONDS (hung event loop / dead feed).
# Adjust INSTALL_DIR below if you deployed elsewhere.
set -uo pipefail

INSTALL_DIR="/opt/quotex-signal-bot"
SERVICE_NAME="quotex-bot"
LOG_FILE="$INSTALL_DIR/logs/bot.log"
STALE_SECONDS=600

log() { echo "$(date -u +%FT%TZ) healthcheck: $*"; }

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  log "service not active; restarting"
  systemctl restart "$SERVICE_NAME"
  exit 0
fi

if [[ -f "$LOG_FILE" ]]; then
  age=$(( $(date +%s) - $(stat -c %Y "$LOG_FILE") ))
  if (( age > STALE_SECONDS )); then
    log "bot.log stale for ${age}s; restarting"
    systemctl restart "$SERVICE_NAME"
    exit 0
  fi
else
  log "bot.log missing; restarting"
  systemctl restart "$SERVICE_NAME"
  exit 0
fi
