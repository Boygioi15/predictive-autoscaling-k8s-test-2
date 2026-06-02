#!/bin/sh
set -eu

OUTPUT_PATH="${1:-shares/ingress_raw.log}"
SINCE_WINDOW="${SINCE_WINDOW:-1s}"

mkdir -p "$(dirname "$OUTPUT_PATH")"
: > "$OUTPUT_PATH"

kubectl logs -n ingress-nginx \
  -l app.kubernetes.io/component=controller \
  --all-containers=true \
  --all-pods=true \
  --follow \
  --since="$SINCE_WINDOW" \
  --max-log-requests=20 \
  --ignore-errors=true  > "$OUTPUT_PATH"