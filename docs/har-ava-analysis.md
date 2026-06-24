# HAR analysis: `apps.mypurecloud.com.har`

**File:** 216 entries (10 MB) · **AVA session/turn POSTs:** 4 (1 session + 3 turns)

## Conversation captured

| # | Request | User input | Response text |
|---|---------|------------|---------------|
| 1 | `POST .../sessions` | — | *(session id only)* |
| 2 | `POST .../turns` | **NoOp** | `Hello! How can I assist you today?` |
| 3 | `POST .../turns` | **schedule** | **`SCHEDULE`** |
| 4 | `POST .../turns` | **research** | **`RESEARCH`** |

Session id in HAR: `7ee74ba6-0f4b-4af5-91e5-8ca2bb95f8d4`

## Critical differences vs our failed API calls

### 1. `genesys-app` header (most important)

Studio sends on every AVA call:

```http
genesys-app: agentic-va-ui-webui
```

Without this header, client-credentials calls returned the comfort greeting even with correct bodies. **With this header + HAR body shape, client credentials returned `SCHEDULE`.**

### 2. `previousTurn` in request body (UserInput turns)

Turn 2 and 3 include the prior turn id:

```json
{
  "previousTurn": { "id": "5654935f-c307-4c0c-8e35-17794161a5f3" },
  "version": "5.0",
  "inputEvent": { ... }
}
```

### 3. Transcript-only alternatives (no top-level `text`)

Studio:

```json
"alternatives": [{
  "transcript": { "confidence": 1, "text": "schedule" }
}]
```

We had been sending both `"text"` and `"transcript"` — HAR uses **transcript only** with **`confidence: 1`**.

### 4. Auth: browser session, not Bearer in HAR

No `Authorization` header on AVA requests in the HAR — auth is via **logged-in apps.mypurecloud.com** session (cookies). Studio UI uses user session; our scripts use **Bearer client credentials**, which still works **if** `genesys-app` and body shape match.

### 5. Other headers

- `Origin: https://apps.mypurecloud.com`
- `Referer: https://apps.mypurecloud.com/`

## Session create body (confirmed)

```json
{
  "version": "5.0",
  "channel": {
    "name": "Messaging",
    "inputModes": ["Text"],
    "outputModes": ["Text"],
    "userAgent": { "name": "GenesysWebWidget" }
  },
  "inputData": {},
  "language": "en-us"
}
```

## Reproduction (verified 2026-06-04)

Client credentials + `genesys-app: agentic-va-ui-webui` + NoOp + UserInput with `previousTurn` + transcript-only → **turn2 = `SCHEDULE`**.

## Updated tooling

`ava_interactive.sh start-studio` now sets `studioHeaders=1` and uses HAR-accurate turn payloads.
