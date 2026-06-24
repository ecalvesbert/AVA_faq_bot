#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_FILE="$SCRIPT_DIR/.cursor/mcp.json"
MCP_KEYED="$SCRIPT_DIR/.cursor/mcp.with-api-key.json.example"
ENV_FILE="$SCRIPT_DIR/.env"

mkdir -p "$SCRIPT_DIR/.cursor"

if [[ -f "$ENV_FILE" ]] && grep -q '^FIRECRAWL_API_KEY=fc-' "$ENV_FILE" 2>/dev/null; then
  cp "$MCP_KEYED" "$MCP_FILE"
  echo "Configured Firecrawl MCP with API key from .env"
else
  cat > "$MCP_FILE" <<'EOF'
{
  "mcpServers": {
    "firecrawl": {
      "url": "https://mcp.firecrawl.dev/v2/mcp"
    }
  }
}
EOF
  echo "Configured Firecrawl MCP (keyless free tier)"
  echo "Optional: copy .env.example to .env, add FIRECRAWL_API_KEY, then re-run this script"
fi

echo
echo "Next steps in Cursor:"
echo "  1. Open Settings → MCP (or reload the window)"
echo "  2. Enable the 'firecrawl' server if it is off"
echo "  3. In Agent chat, try: 'Use Firecrawl to search Genesys AVA session API docs'"
echo
echo "Config file: $MCP_FILE"
