# Agentic Virtual Agent (AVA) Session API

Documentation extracted from **Genesys API Central API Explorer** ([apicentral.genesys.cloud/api-explorer-standalone](https://apicentral.genesys.cloud/api-explorer-standalone)) and the official **PureCloud Platform API** OpenAPI spec (`swaggerall`, internal).

**Source spec:** `GET https://api.{region}/api/v2/docs/swaggerall` → `publicapi-v2-latest-internal.json`  
**Tags:** `AI Studio`, `Virtual Agents`  
**OAuth scope:** `agentic-virtualagents-internal`  
**Content-Type:** `application/json`

---

## Endpoints overview

| Method | Path | Summary | Visibility |
|--------|------|---------|------------|
| `POST` | `/api/v2/apps/agentic/virtualagents/{agentId}/sessions` | Create a virtual agent session | **Internal** |
| `POST` | `/api/v2/apps/agentic/virtualagents/{virtualAgentId}/sessions/{virtualAgentSessionId}/turns` | Add a turn to a virtual agent session | **Internal** |

There are **no** documented `GET` (or other) operations under `virtualagents/.../sessions` in the current OpenAPI spec. In particular:

- **GET session** — not documented; live probes returned **HTTP 404**.
- **GET turns** — not documented; live probes returned **HTTP 405**.
- **GET session/messages** — not documented; no matching path in spec.

---

## 1. Create session

### Method + path

`POST /api/v2/apps/agentic/virtualagents/{agentId}/sessions`

### Description

Create a virtual agent session.

- **Operation ID:** `postAppsAgenticVirtualagentSessions`
- **Required permission:** `agentic:virtualAgentSession:add` (type: ALL)
- **Produces:** `application/json`

### Visibility

**Internal** (`x-genesys-visibility: internal`)

### Path parameters

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `agentId` | path | string (UUID) | Yes | The virtual agent ID |

### Query parameters

None.

### Request body — `CreateVirtualAgentSession`

| Field | Type | Required (schema) | Description | Valid values / notes |
|-------|------|-------------------|-------------|----------------------|
| `version` | string | **Yes** | Version of the virtual agent (e.g. published version) | e.g. `"1.0"` |
| `channel` | object (`VirtualAgentSessionChannel`) | **Yes** | Channel configuration | See below |
| `channel.name` | string | **Yes** | Channel name | `Messaging`, `Call` |
| `channel.inputModes` | string[] | No | Input modes supported | Items: `Text` (request often uses lowercase `"text"`; response may normalize to `Text`) |
| `channel.outputModes` | string[] | No | Output modes supported | Items: `Text` |
| `channel.userAgent` | object | No* | User agent metadata | See below |
| `channel.userAgent.name` | string | **Yes** (if `userAgent` present) | User agent name | `GenesysWebWidget`, `Unknown` |
| `language` | string | No† | Language code for the session | e.g. `en-US` (response may return `en-us`) |
| `inputData` | object | No | Arbitrary input data map | `additionalProperties`: object |

\* `userAgent` is commonly sent in practice even when optional in schema.  
† OpenAPI lists `language` as optional, but the API returns **400** if `channel`, `version`, and `language` are all missing/null (`Validation failed: channel: must not be null, version: must not be null, language: must not be null`).

#### Example request body

```json
{
  "channel": {
    "name": "Messaging",
    "userAgent": {
      "name": "Unknown",
      "version": "1.0"
    },
    "inputModes": ["text"],
    "outputModes": ["text"]
  },
  "version": "1.0",
  "language": "en-US"
}
```

### Response schemas

#### `200` / `201` — `VirtualAgentSessionResponse`

| Field | Type | Required | Description | Valid values |
|-------|------|----------|-------------|--------------|
| `id` | string (UUID) | No (readOnly in schema) | Session ID | Use as `virtualAgentSessionId` for turns |
| `version` | string | No | Virtual agent version | |
| `channel` | `VirtualAgentSessionChannel` | No | Echo/normalized channel | `name`: `Messaging` \| `Call`; modes often returned as `Text` |
| `language` | string | No | Session language | e.g. `en-us` |
| `inputData` | object | No | Input data map | `additionalProperties`: object |

#### Example `201` response

```json
{
  "id": "05db6ac7-4b19-4853-ae71-36f6a85f2e35",
  "version": "1.0",
  "channel": {
    "name": "Messaging",
    "inputModes": ["Text"],
    "outputModes": ["Text"],
    "userAgent": {
      "name": "Unknown"
    }
  },
  "language": "en-us"
}
```

#### Error responses

Standard Genesys `ErrorBody` for `400`, `401`, `403`, `404`, `408`, `409`, `413`, `415`, `429`, `500`, `503`, `504`.

### Example curl (API Explorer style)

From API Explorer (host reflects logged-in region; replace placeholders):

```bash
curl -X POST "https://api.mypurecloud.com/api/v2/apps/agentic/virtualagents/{agentId}/sessions" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": {
      "name": "Messaging",
      "userAgent": { "name": "Unknown", "version": "1.0" },
      "inputModes": ["text"],
      "outputModes": ["text"]
    },
    "version": "1.0",
    "language": "en-US"
  }'
```

Explorer raw request line:

```http
POST /api/v2/apps/agentic/virtualagents/{agentId}/sessions HTTP/1.1
Host: api.{your-region-host}
Authorization: Bearer {access_token}
Content-Type: application/json
```

---

## 2. Add turn

### Method + path

`POST /api/v2/apps/agentic/virtualagents/{virtualAgentId}/sessions/{virtualAgentSessionId}/turns`

### Description

Add a turn to a virtual agent session. Creates a new turn in the specified virtual agent session with the provided request data.

**Note from spec:** If the session ID does not exist, a new session may be created automatically (per operation description).

- **Operation ID:** `postAppsAgenticVirtualagentSessionTurns`
- **Required permission:** `agentic:virtualAgentSessionTurn:add` (type: ALL)
- **Produces:** `application/json`

### Visibility

**Internal** (`x-genesys-visibility: internal`)

### Path parameters

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `virtualAgentId` | path | string (UUID) | Yes | Virtual Agent ID (same value as `agentId` on create session) |
| `virtualAgentSessionId` | path | string (UUID) | Yes | Virtual Agent Session ID (`id` from create session response) |

### Query parameters

None.

### Request body — `VirtualAgentSessionTurnRequest`

| Field | Type | Required | Description | Valid values / notes |
|-------|------|----------|-------------|----------------------|
| `version` | string | **Yes** | Version for this turn | e.g. `"1.0"` |
| `inputEvent` | object (`VirtualAgentSessionInputEvent`) | **Yes** | Input event | See below |
| `inputEvent.type` | string | **Yes** | Input event type | `UserInput`, `NoOp`, `UserDisconnect` |
| `inputEvent.mode` | string | **Yes** | Input mode | `Voice`, `Text` (tenant testing: **Text** works; Voice may be rejected) |
| `inputEvent.alternatives` | array | No | User input alternatives | Required for user text turns |
| `inputEvent.alternatives[].transcript` | object | **Yes** (per item) | Transcript | See below |
| `inputEvent.alternatives[].transcript.text` | string | **Yes** | Transcript text | User utterance |
| `inputEvent.alternatives[].transcript.confidence` | number (float) | **Yes** (schema) | Confidence score | Often omitted in practice; API may accept `transcript` with `text` only |
| `previousTurn` | object | No | Previous turn reference | |
| `previousTurn.id` | string | No | ID of previous turn | |

**Runtime validation notes (from integration tests):**

- `inputEvent` is required (400: `[inputEvent is required]` if missing).
- `inputEvent.alternatives[0].transcript` must not be null for `UserInput` + `Text`.
- `NoOp` events require `inputEvent.mode`.
- A top-level `input` string field is **not** valid.

#### Example request body — user text turn

```json
{
  "version": "1.0",
  "inputEvent": {
    "type": "UserInput",
    "mode": "Text",
    "alternatives": [
      {
        "text": "I need to schedule a meeting for tomorrow",
        "transcript": {
          "text": "I need to schedule a meeting for tomorrow"
        }
      }
    ]
  }
}
```

### Response schemas

#### `201` — `VirtualAgentSessionTurnResponse`

| Field | Type | Required | Description | Valid values |
|-------|------|----------|-------------|--------------|
| `id` | string | No | Turn ID | |
| `previousTurn` | `VirtualAgentSessionTurnReference` | No | Previous turn | `id`: string |
| `prompts` | `VirtualAgentSessionTurnPrompts` | No | Agent prompts | |
| `prompts.outputLanguage` | string | **Yes** (if `prompts` present) | ISO output language | e.g. `en-us` |
| `prompts.text` | `VirtualAgentSessionTurnTextPrompt` | No | Text prompt | |
| `prompts.text.segments` | array | **Yes** (if `text` present) | Prompt segments | |
| `prompts.text.segments[].type` | string | No | Segment type | `Text` |
| `prompts.text.segments[].text` | string | No | Spoken/display text | Agent reply |
| `nextAction` | `VirtualAgentSessionTurnNextAction` | No | What client should do next | |
| `nextAction.type` | string | No | Next action type | `WaitForInput`, `NoOp`, `Disconnect`, `Exit` |
| `nextAction.reason` | string | No | Reason | `AgentRequestedByUser`, `Error`, `TriggeredByUser`, `Guardrails` |
| `nextAction.outputData` | object | No | Structured output from AVA | `additionalProperties`: object |
| `events` | object | No | Metadata for next action | |

#### Example `201` response

```json
{
  "id": "a1a50f26-6e23-44d4-814e-735dfc1967d8",
  "prompts": {
    "outputLanguage": "en-us",
    "text": {
      "segments": [
        {
          "type": "Text",
          "text": "Hello! How can I assist you today?"
        }
      ]
    }
  },
  "nextAction": {
    "type": "WaitForInput"
  }
}
```

#### Error responses

`ErrorBody` for `400`, `401`, `403`, `404`, `408`, `409`, `413`, `415`, `429`, `500`, `503`, `504` (no `200` success code documented; success is **201**).

### Example curl (API Explorer style)

```bash
curl -X POST "https://api.mypurecloud.com/api/v2/apps/agentic/virtualagents/${VIRTUAL_AGENT_ID}/sessions/${SESSION_ID}/turns" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "1.0",
    "inputEvent": {
      "type": "UserInput",
      "mode": "Text",
      "alternatives": [
        {
          "text": "Hello",
          "transcript": { "text": "Hello" }
        }
      ]
    }
  }'
```

---

## 3. GET session / messages (not documented)

The internal OpenAPI spec (`swaggerall`) defines **only** the two `POST` operations above for AVA sessions. No paths match:

- `GET .../sessions/{sessionId}`
- `GET .../sessions/{sessionId}/turns`
- `GET .../sessions/{sessionId}/messages`

Observed behavior when calling undocumented read paths:

| Probe | HTTP | Notes |
|-------|------|-------|
| `GET /api/v2/apps/agentic/virtualagents/{id}/sessions/{sessionId}` | **404** | Not found |
| `GET /api/v2/apps/agentic/virtualagents/{id}/sessions/{sessionId}/turns` | **405** | Method not allowed |

Use **POST turns** responses (`prompts`, `nextAction`, `events`) as the conversation interface; do not rely on GET for session history unless Genesys publishes new endpoints.

---

## Authentication

All endpoints require a valid OAuth bearer token with scope **`agentic-virtualagents-internal`**.

```bash
# Client credentials example
curl -X POST "https://login.mypurecloud.com/oauth/token" \
  -u "${CLIENT_ID}:${CLIENT_SECRET}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials"
```

Replace `api.mypurecloud.com` / `login.mypurecloud.com` with your org region (e.g. `mypurecloud.ie`, `mypurecloud.de`).

---

## Related virtual agent paths (non-session)

For completeness, other `virtualagents` paths in the same spec (not session runtime):

- `GET/POST /api/v2/apps/agentic/virtualagents`
- `GET/PATCH /api/v2/apps/agentic/virtualagents/{virtualAgentId}`
- Version and job management under `.../versions/...` and `.../jobs/...`

---

## Document metadata

| Item | Value |
|------|-------|
| Extracted | 2026-06-03 |
| API Explorer | [apicentral.genesys.cloud/api-explorer-standalone](https://apicentral.genesys.cloud/api-explorer-standalone) |
| OpenAPI | `https://api.mypurecloud.com/api/v2/docs/swaggerall` (redirects to latest internal JSON) |
| Spec version | PureCloud Platform API v2 (`swagger: 2.0`) |
