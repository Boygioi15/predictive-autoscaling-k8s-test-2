#!/bin/sh
set -eu

# Load the image-bundled environment before starting the sender.
set -a
. /app/custom_load_generator.env
set +a

exec python -u /app/load_sender.py
