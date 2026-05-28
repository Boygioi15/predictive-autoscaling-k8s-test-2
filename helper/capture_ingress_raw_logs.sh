#!/bin/sh
set -eu

OUTPUT_PATH="${1:-shares/ingress_raw.log}"
SINCE_WINDOW="${SINCE_WINDOW:-1s}"

mkdir -p "$(dirname "$OUTPUT_PATH")"
: > "$OUTPUT_PATH"

kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --follow --since="$SINCE_WINDOW" > "$OUTPUT_PATH"
