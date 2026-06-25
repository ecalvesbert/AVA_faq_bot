#!/usr/bin/env bash
# Deploy AVA FAQ chat + manual ingest to Railway.
#
# Required auth — pick one:
#   RAILWAY_API_TOKEN      — account token (Account Settings → Tokens, "No workspace")
#   RAILWAY_TOKEN          — project token (Project → Settings → Tokens)
#   railway login          — interactive / browserless CLI session (no env var)
#
# Required for Genesys (unless USE_GC_PROFILE=1):
#   GENESYS_CLIENT_ID
#   GENESYS_CLIENT_SECRET
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v railway >/dev/null 2>&1; then
  echo "Install Railway CLI: npm install -g @railway/cli" >&2
  exit 1
fi

if [[ -n "${RAILWAY_TOKEN:-}" && -n "${RAILWAY_API_TOKEN:-}" ]]; then
  echo "Unset one of RAILWAY_TOKEN or RAILWAY_API_TOKEN (Railway allows only one)." >&2
  exit 1
fi

if [[ -z "${RAILWAY_TOKEN:-}" && -z "${RAILWAY_API_TOKEN:-}" ]]; then
  if ! railway whoami >/dev/null 2>&1; then
    echo "Authenticate first:" >&2
    echo "  export RAILWAY_API_TOKEN=...   # account token from railway.com/account/tokens" >&2
    echo "  or: railway login --browserless" >&2
    exit 1
  fi
fi

read_gc_profile() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path

profile = sys.argv[1]
config = Path.home() / ".gc" / "config.toml"
if not config.exists():
    sys.exit(1)
section = None
values = {}
for raw in config.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("[") and line.endswith("]"):
        section = line[1:-1]
        continue
    if section != profile or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip().strip('"').strip("'")
print(values.get("client_credentials", ""))
print(values.get("client_secret", ""))
print(values.get("environment", "mypurecloud.com"))
PY
}

if [[ "${USE_GC_PROFILE:-0}" == "1" ]]; then
  GC_BLOCK="$(read_gc_profile "${GENESYS_PROFILE:-default}" 2>/dev/null || true)"
  if [[ -n "${GC_BLOCK}" ]]; then
    GC_ID="$(echo "${GC_BLOCK}" | sed -n '1p')"
    GC_SECRET="$(echo "${GC_BLOCK}" | sed -n '2p')"
    GC_ENV="$(echo "${GC_BLOCK}" | sed -n '3p')"
    GENESYS_CLIENT_ID="${GENESYS_CLIENT_ID:-${GC_ID}}"
    GENESYS_CLIENT_SECRET="${GENESYS_CLIENT_SECRET:-${GC_SECRET}}"
    GENESYS_ENVIRONMENT="${GENESYS_ENVIRONMENT:-${GC_ENV:-mypurecloud.com}}"
  fi
fi

: "${GENESYS_CLIENT_ID:?Set GENESYS_CLIENT_ID or USE_GC_PROFILE=1}"
: "${GENESYS_CLIENT_SECRET:?Set GENESYS_CLIENT_SECRET or USE_GC_PROFILE=1}"
: "${AVA_AGENT_ID:?Set AVA_AGENT_ID for the deployed chat bot}"

GENESYS_ENVIRONMENT="${GENESYS_ENVIRONMENT:-mypurecloud.com}"
AVA_VERSION="${AVA_VERSION:-6.0}"
PIPELINE_API_KEY="${PIPELINE_API_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')}"
CHAT_API_KEY="${CHAT_API_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')}"
PROJECT_NAME="${RAILWAY_PROJECT_NAME:-ava-faq-chat}"
SERVICE_NAME="${RAILWAY_SERVICE_NAME:-${PROJECT_NAME}}"
WORKSPACE="${RAILWAY_WORKSPACE:-}"

echo "==> Railway project: ${PROJECT_NAME}"
echo "==> Workspace: ${WORKSPACE}"
echo "==> Genesys environment: ${GENESYS_ENVIRONMENT}"
echo "==> AVA: ${AVA_AGENT_ID} v${AVA_VERSION}"
echo "==> Pipeline API key (save for /admin): ${PIPELINE_API_KEY}" >&2
echo "==> Chat API key (embedded in web UI): ${CHAT_API_KEY}" >&2

if ! railway status >/dev/null 2>&1; then
  if [[ -z "${WORKSPACE}" ]]; then
    echo "Set RAILWAY_WORKSPACE (run 'railway list' to see workspace names)." >&2
    exit 1
  fi
  echo "==> Creating Railway project in workspace: ${WORKSPACE}..."
  railway init -n "${PROJECT_NAME}" -w "${WORKSPACE}"
fi

# New projects have no service until the first deploy.
if ! railway service status >/dev/null 2>&1; then
  echo "==> First deploy (creates service)..."
  railway up --detach -y
fi

echo "==> Linking service ${SERVICE_NAME}..."
railway service link "${SERVICE_NAME}" 2>/dev/null || true

echo "==> Setting service variables..."
railway variables set \
  "GENESYS_CLIENT_ID=${GENESYS_CLIENT_ID}" \
  "GENESYS_CLIENT_SECRET=${GENESYS_CLIENT_SECRET}" \
  "GENESYS_ENVIRONMENT=${GENESYS_ENVIRONMENT}" \
  "AVA_AGENT_ID=${AVA_AGENT_ID}" \
  "AVA_VERSION=${AVA_VERSION}" \
  "AVA_STUDIO_MODE=1" \
  "DATA_DIR=/data" \
  "PIPELINE_API_KEY=${PIPELINE_API_KEY}" \
  "REQUIRE_PIPELINE_KEY=1" \
  "CHAT_API_KEY=${CHAT_API_KEY}" \
  "REQUIRE_CHAT_KEY=1" \
  "CHAT_TITLE=FAQ Assistant" \
  "CHAT_SUBTITLE=Ask questions about our products and services."

if [[ -n "${FIRECRAWL_API_KEY:-}" ]]; then
  railway variables set "FIRECRAWL_API_KEY=${FIRECRAWL_API_KEY}"
fi

if [[ -n "${KNOWLEDGE_SOURCE_ID:-}" ]]; then
  railway variables set "KNOWLEDGE_SOURCE_ID=${KNOWLEDGE_SOURCE_ID}"
fi

echo "==> Ensuring /data volume..."
if railway volume list 2>/dev/null | grep -q /data; then
  echo "    /data volume already present"
else
  railway volume add --mount-path /data
fi

echo "==> Redeploying with variables and volume..."
railway redeploy -y 2>/dev/null || railway up --detach -y

echo "==> Public domain..."
railway domain 2>/dev/null || echo "    Generate a domain in Railway dashboard if missing."

echo
echo "Done."
echo "  Chat:   /"
echo "  Admin:  /?tab=admin  (pipeline API key printed above)"
echo
echo "Ingest is manual-only — nothing crawls until you click Start ingest on /admin."
