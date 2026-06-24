#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

python3 "$SCRIPT_DIR/firecrawl_demo.py" demo "$@"
