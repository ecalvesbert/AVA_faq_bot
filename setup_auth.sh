#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="$HOME/.gc"
CONFIG_FILE="$CONFIG_DIR/config.toml"

echo "Genesys Cloud CLI auth setup"
echo "Creates $CONFIG_FILE for gc and for API scripts in this project."
echo

read -r -p "Profile name [default]: " PROFILE
PROFILE="${PROFILE:-default}"

read -r -p "Environment (e.g. mypurecloud.com, inindca.com) [mypurecloud.com]: " ENVIRONMENT
ENVIRONMENT="${ENVIRONMENT:-mypurecloud.com}"

read -r -p "OAuth Client ID: " CLIENT_ID
if [[ -z "$CLIENT_ID" ]]; then
  echo "Client ID is required." >&2
  exit 1
fi

read -r -s -p "OAuth Client Secret: " CLIENT_SECRET
echo
if [[ -z "$CLIENT_SECRET" ]]; then
  echo "Client secret is required." >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"

if [[ -f "$CONFIG_FILE" ]]; then
  backup="$CONFIG_FILE.bak.$(date +%Y%m%d%H%M%S)"
  cp "$CONFIG_FILE" "$backup"
  echo "Backed up existing config to $backup"
fi

cat > "$CONFIG_FILE" <<EOF
[$PROFILE]
access_token = ''
client_credentials = '$CLIENT_ID'
client_secret = '$CLIENT_SECRET'
environment = '$ENVIRONMENT'
grant_type = '1'
secure_login_enabled = false
redirect_uri = ''
oauth_token_data = ''
EOF

chmod 600 "$CONFIG_FILE"
echo
echo "Wrote profile [$PROFILE] to $CONFIG_FILE"
echo "Testing OAuth token..."

TOKEN_RESPONSE="$(
  curl -sS --noproxy '*' \
    -X POST "https://login.${ENVIRONMENT}/oauth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials" \
    -u "${CLIENT_ID}:${CLIENT_SECRET}"
)"

if ! python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('access_token') else 1)" <<< "$TOKEN_RESPONSE"; then
  echo "OAuth failed:" >&2
  echo "$TOKEN_RESPONSE" >&2
  exit 1
fi

echo "OAuth token: OK"

echo "Testing API access (GET /api/v2/guides)..."
TOKEN="$(python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])" <<< "$TOKEN_RESPONSE")"
HTTP_CODE="$(
  curl -sS --noproxy '*' -o /tmp/genesys-api-test.json -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    "https://api.${ENVIRONMENT}/api/v2/guides?pageSize=1"
)"

echo "API test HTTP $HTTP_CODE"
if [[ "$HTTP_CODE" == "200" ]]; then
  TOTAL="$(python3 -c "import json; print(json.load(open('/tmp/genesys-api-test.json')).get('total','?'))")"
  echo "Guides total: $TOTAL"
else
  cat /tmp/genesys-api-test.json
  echo
  echo "Token works, but this API call failed. Check OAuth client scopes for your org." >&2
fi

echo
echo "Done. Use:"
echo "  gc -p $PROFILE guides list --outputformat json"
echo "  GENESYS_PROFILE=$PROFILE ./run_api.sh /api/v2/guides"
