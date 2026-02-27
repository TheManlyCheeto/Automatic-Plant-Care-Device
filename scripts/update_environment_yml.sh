#!/usr/bin/env bash
set -euo pipefail
ENV_NAME="cv"
OUT_FILE="../environment_droplet.yml"
conda env export -n "$ENV_NAME" --from-history > "$OUT_FILE"