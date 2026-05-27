#!/bin/sh
set -eu

MODE_VALUE="${MODE:-manual}"
NORMALIZED_MODE="$(printf '%s' "$MODE_VALUE" | awk '{print tolower($1)}')"

if [ "$NORMALIZED_MODE" = "script" ]; then
  exec locust \
    -f /mnt/locust/locustfile.py \
    --autostart \
    --web-host=0.0.0.0 \
    --users "${SCRIPT_DRIVER_USERS:-1}" \
    --spawn-rate "${SCRIPT_DRIVER_SPAWN_RATE:-1}"
fi

exec locust \
  -f /mnt/locust/locustfile.py \
  --web-host=0.0.0.0
