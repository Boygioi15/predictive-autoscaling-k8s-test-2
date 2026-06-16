#!/bin/sh
set -eu

exec locust \
  -f /mnt/locust/locustfile.py \
  --web-host=0.0.0.0 \
  "$@"
