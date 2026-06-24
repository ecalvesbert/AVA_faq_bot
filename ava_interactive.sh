#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$SCRIPT_DIR/.ava-session.json"
PROFILE="${GENESYS_PROFILE:-default}"
ENVIRONMENT="${GENESYS_ENVIRONMENT:-mypurecloud.com}"

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
  ' "$HOME/.gc/config.toml"
}

get_token() {
  local client_id client_secret
  client_id="${GENESYS_CLIENT_ID:-$(read_profile_value client_credentials)}"
  client_secret="${GENESYS_CLIENT_SECRET:-$(read_profile_value client_secret)}"
  ENVIRONMENT="${ENVIRONMENT:-$(read_profile_value environment)}"
  ENVIRONMENT="${ENVIRONMENT:-mypurecloud.com}"

  curl -sS --noproxy '*' \
    -X POST "https://login.${ENVIRONMENT}/oauth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials" \
    -u "${client_id}:${client_secret}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
}

api_post() {
  local path="$1"
  local body="$2"
  local extra_headers=()
  if [[ "${STUDIO_HEADERS:-0}" == "1" ]]; then
    extra_headers=(
      -H "genesys-app: agentic-va-ui-webui"
      -H "Origin: https://apps.${ENVIRONMENT}"
    )
  fi
  curl -sS --noproxy '*' -w "\n__HTTP__:%{http_code}" \
    -X POST "https://api.${ENVIRONMENT}${path}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    "${extra_headers[@]}" \
    -d "$body"
}

extract_agent_text() {
  python3 -c "
import json, sys
raw = sys.stdin.read()
if '__HTTP__:' in raw:
    body, _, code = raw.rpartition('__HTTP__:')
else:
    body, code = raw, '?'
try:
    d = json.loads(body)
except json.JSONDecodeError:
    print('HTTP', code)
    print(body[:500])
    sys.exit(1)
segments = d.get('prompts', {}).get('text', {}).get('segments', [])
text = ' '.join(s.get('text', '') for s in segments if s.get('text'))
next_action = d.get('nextAction', {}).get('type', '')
print('HTTP', code)
print('AVA:', text or '(no text)')
if next_action:
    print('Next:', next_action)
if d.get('id'):
    print('TurnId:', d['id'])
"
}

cmd="${1:-}"
shift || true

case "$cmd" in
  start|start-studio)
    AGENT_ID="${1:-1f7dd771-c326-44bf-a12e-eff153fd2da1}"
    if [[ "$cmd" == "start-studio" ]]; then
      VERSION="${2:-5.0}"
      STUDIO_MODE=1
      STUDIO_HEADERS=1
    else
      VERSION="${2:-1.0}"
      STUDIO_MODE=0
      STUDIO_HEADERS=0
    fi
    CHANNEL="${3:-Messaging}"
    TOKEN="$(get_token)"
    if [[ "$STUDIO_MODE" == "1" ]]; then
      SESSION_BODY='{"version":"5.0","channel":{"name":"Messaging","inputModes":["Text"],"outputModes":["Text"],"userAgent":{"name":"GenesysWebWidget"}},"inputData":{},"language":"en-us"}'
      VERSION="5.0"
    else
      SESSION_BODY="$(AGENT_CHANNEL="$CHANNEL" AGENT_VERSION="$VERSION" python3 <<'PY'
import json, os
print(json.dumps({
  "channel": {
    "name": os.environ["AGENT_CHANNEL"],
    "userAgent": {"name": "Unknown", "version": "1.0"},
    "inputModes": ["text"],
    "outputModes": ["text"],
  },
  "version": os.environ["AGENT_VERSION"],
  "language": "en-US",
}))
PY
)"
    fi
    RESPONSE="$(api_post "/api/v2/apps/agentic/virtualagents/${AGENT_ID}/sessions" "$SESSION_BODY")"
    python3 -c "
import json, sys
raw = sys.stdin.read()
body, _, code = raw.rpartition('__HTTP__:')
d = json.loads(body)
if not str(code).startswith('2'):
    print('Failed to create session HTTP', code)
    print(body)
    sys.exit(1)
state = {
  'agentId': '$AGENT_ID',
  'sessionId': d['id'],
  'version': '$VERSION',
  'channel': '$CHANNEL',
  'environment': '$ENVIRONMENT',
  'studioMode': $STUDIO_MODE,
  'studioHeaders': $STUDIO_HEADERS,
  'noopDone': False,
  'lastTurnId': ''
}
json.dump(state, open('$STATE_FILE', 'w'), indent=2)
print('Session started:', d['id'])
print('Agent: Simple front door | Channel: $CHANNEL | Version: $VERSION')
if $STUDIO_MODE:
    print('Studio mode: run noop next (or first say will auto-noop)')
" <<< "$RESPONSE"
    ;;
  noop)
    if [[ ! -f "$STATE_FILE" ]]; then
      echo "No session. Run: $0 start-studio" >&2
      exit 1
    fi
    TOKEN="$(get_token)"
    read -r AGENT_ID SESSION_ID VERSION STUDIO_MODE STUDIO_HEADERS <<< "$(python3 -c "
import json
s=json.load(open('$STATE_FILE'))
print(s['agentId'], s['sessionId'], s['version'], s.get('studioMode', 0), s.get('studioHeaders', 0))
")"
    export STUDIO_HEADERS="${STUDIO_HEADERS:-0}"
    BODY="$(VERSION="$VERSION" python3 -c "import json,os; print(json.dumps({'version':os.environ['VERSION'],'inputEvent':{'type':'NoOp','mode':'Text'}}))")"
    RAW="$(api_post "/api/v2/apps/agentic/virtualagents/${AGENT_ID}/sessions/${SESSION_ID}/turns" "$BODY")"
    echo "$RAW" | extract_agent_text
    python3 -c "
import json, sys
raw = sys.stdin.read()
body, _, _ = raw.rpartition('__HTTP__:')
d = json.loads(body)
s = json.load(open('$STATE_FILE'))
s['noopDone'] = True
s['lastTurnId'] = d.get('id', '')
json.dump(s, open('$STATE_FILE', 'w'), indent=2)
" <<< "$RAW"
    ;;
  say)
    MESSAGE="$*"
    if [[ -z "$MESSAGE" ]]; then
      echo "Usage: $0 say <message>" >&2
      exit 1
    fi
    if [[ ! -f "$STATE_FILE" ]]; then
      echo "No session. Run: $0 start-studio" >&2
      exit 1
    fi
    TOKEN="$(get_token)"
    read -r AGENT_ID SESSION_ID VERSION STUDIO_MODE STUDIO_HEADERS NOOP_DONE LAST_TURN <<< "$(python3 -c "
import json
s=json.load(open('$STATE_FILE'))
print(s['agentId'], s['sessionId'], s['version'], s.get('studioMode', 0), s.get('studioHeaders', 0), s.get('noopDone', False), s.get('lastTurnId', ''))
")"
    export STUDIO_HEADERS="${STUDIO_HEADERS:-0}"
    if [[ "$STUDIO_MODE" == "1" && "$NOOP_DONE" != "True" ]]; then
      echo "Running Studio NoOp turn first..."
      NOOP_BODY="$(VERSION="$VERSION" python3 -c "import json,os; print(json.dumps({'version':os.environ['VERSION'],'inputEvent':{'type':'NoOp','mode':'Text'}}))")"
      RAW="$(api_post "/api/v2/apps/agentic/virtualagents/${AGENT_ID}/sessions/${SESSION_ID}/turns" "$NOOP_BODY")"
      echo "$RAW" | extract_agent_text
      LAST_TURN="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('id',''))" <<< "${RAW%%__HTTP__*}")"
      python3 -c "import json; s=json.load(open('$STATE_FILE')); s['noopDone']=True; s['lastTurnId']=sys.argv[1]; json.dump(s,open('$STATE_FILE','w'),indent=2)" "$LAST_TURN"
      echo "---"
    fi
    BODY="$(MESSAGE="$MESSAGE" VERSION="$VERSION" LAST_TURN="$LAST_TURN" STUDIO_MODE="$STUDIO_MODE" python3 <<'PY'
import json, os
msg = os.environ["MESSAGE"]
ver = os.environ["VERSION"]
payload = {
  "version": ver,
  "inputEvent": {
    "type": "UserInput",
    "mode": "Text",
    "alternatives": [{
      "transcript": {"confidence": 1, "text": msg},
    }],
  },
}
if os.environ.get("STUDIO_MODE") == "1" and os.environ.get("LAST_TURN"):
    payload["previousTurn"] = {"id": os.environ["LAST_TURN"]}
print(json.dumps(payload))
PY
)"
    RAW="$(api_post "/api/v2/apps/agentic/virtualagents/${AGENT_ID}/sessions/${SESSION_ID}/turns" "$BODY")"
    echo "$RAW" | extract_agent_text
    python3 -c "
import json, sys
raw = sys.stdin.read()
body, _, _ = raw.rpartition('__HTTP__:')
d = json.loads(body)
s = json.load(open('$STATE_FILE'))
s['lastTurnId'] = d.get('id', s.get('lastTurnId', ''))
json.dump(s, open('$STATE_FILE', 'w'), indent=2)
" <<< "$RAW"
    ;;
  status)
    if [[ ! -f "$STATE_FILE" ]]; then
      echo "No active session."
      exit 0
    fi
    cat "$STATE_FILE"
    ;;
  end)
    rm -f "$STATE_FILE"
    echo "Session cleared."
    ;;
  *)
    echo "Usage: $0 {start|start-studio|noop|say|status|end} [args...]" >&2
    exit 1
    ;;
esac
