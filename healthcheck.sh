# Render healthcheck script (used by Dockerfile.healthcheck).
# Renders /status endpoint returns JSON; we just need it to not time out.
# If curl fails (container truly down), exit code 1 → Render restarts.

#!/usr/bin/env bash
set -euo pipefail

# The bot's /status route (defined in main.py) returns {"connected": True, ...}
# We don't strictly need the body; just that the HTTP 200 is reachable.
curl -fsS http://localhost:8080/status > /dev/null 2>&1