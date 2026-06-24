#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export DATA_DIR="${DATA_DIR:-artifacts}"
export PORT="${PORT:-8080}"

exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
