#!/bin/sh
set -eu

INGRESS_NAME="${1:-ingress-backend}"
OUTPUT_PATH="${2:-shares/ingress_request_report.csv}"
SINCE_WINDOW="${SINCE_WINDOW:-1s}"

kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --follow --since="$SINCE_WINDOW" | \
python3 helper/summarize_ingress_logs.py --stream --ingress "$INGRESS_NAME" --output "$OUTPUT_PATH"
