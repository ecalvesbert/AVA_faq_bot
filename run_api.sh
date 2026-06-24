#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${GENESYS_PROFILE:-default}"
ENVIRONMENT="${GENESYS_ENVIRONMENT:-}"
ENDPOINT="${1:-/api/v2/apps/agentic/copilots/agents}"
METHOD="${METHOD:-GET}"
PAGE_SIZE="${PAGE_SIZE:-5}"
PAGE_NUMBER="${PAGE_NUMBER:-1}"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

CONFIG="$HOME/.gc/config.toml"
if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG" >&2
  echo "Run: $SCRIPT_DIR/setup_auth.sh" >&2
  exit 1
fi

read_profile_value() {
  awk -v profile="$PROFILE" -v key="$1" '
    $0 ~ "^\\[" profile "\\]" { in_section=1; next }
    /^\[/ { in_section=0 }
    in_section && $1 == key {
      sub(/^[^=]*=[[:space:]]*/, "", $0)
      gsub(/^["'"'"']|["'"'"']$/, "", $0)
      print $0
      exit
    }
  ' "$CONFIG"
}

CLIENT_ID="${GENESYS_CLIENT_ID:-$(read_profile_value client_credentials)}"
CLIENT_SECRET="${GENESYS_CLIENT_SECRET:-$(read_profile_value client_secret)}"
ENVIRONMENT="${ENVIRONMENT:-$(read_profile_value environment)}"
ENVIRONMENT="${ENVIRONMENT:-mypurecloud.com}"

if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" ]]; then
  echo "Missing OAuth credentials for profile '$PROFILE'" >&2
  exit 1
fi

echo "Environment: $ENVIRONMENT"
echo "Fetching token from login.$ENVIRONMENT ..."

TOKEN="$(
  curl -sS --noproxy '*' \
    -X POST "https://login.${ENVIRONMENT}/oauth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials" \
    -u "${CLIENT_ID}:${CLIENT_SECRET}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])"
)"

echo "Token acquired."

if [[ "$ENDPOINT" != /* ]]; then
  ENDPOINT="/${ENDPOINT}"
fi

URL="https://api.${ENVIRONMENT}${ENDPOINT}"
if [[ "$METHOD" == "GET" && "$ENDPOINT" == */agents ]]; then
  URL="${URL}?pageSize=${PAGE_SIZE}&pageNumber=${PAGE_NUMBER}"
fi

echo "${METHOD} ${URL}"

curl -sS --noproxy '*' -w "\nHTTP:%{http_code}\n" \
  -X "$METHOD" "$URL" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  ${BODY:+-d "$BODY"}
