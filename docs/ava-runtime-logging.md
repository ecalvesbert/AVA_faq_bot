# AVA session API — runtime logs, traces, and proving user input was received

Research date: **2026-06-04**  
Environment probed: **mypurecloud.com** (profile `default`, OAuth client credentials; no secrets recorded here)  
OpenAPI source: `GET https://api.mypurecloud.com/api/v2/docs/swaggerall` (internal PureCloud Platform API v2 JSON, ~30 MB)

Related repo docs: [ava-session-api-doc.md](./ava-session-api-doc.md), [simple-front-door-ava-report.json](./simple-front-door-ava-report.json), [simple-front-door-ava-debug.json](./simple-front-door-ava-debug.json)

---

## Executive answer

| Question | Answer |
|----------|--------|
| **Is there a platform log/trace API you can pull after a session turn to prove the user prompt was received?** | **No public/internal Platform API** under `apps/agentic/virtualagents/...` exposes turn-level runtime traces, conversation history, or server-side input echo for the **direct Session + Turns** integration. |
| **What can you analyze?** | (1) **Your integrator’s own request/response logs** (you already sent `inputEvent` in the POST body). (2) **`ININ-Correlation-Id`** on each HTTP response — ties one API call to Genesys backend logs for **support**, not customer retrieval. (3) **UI-only** testing: AI Studio preview widget; **Architect** bot flow simulator + replay when the AVA is wired through a Virtual Agent flow. (4) **Analytics `reportingturns`** only for **Architect bot flow** sessions (includes `userInput`), not for arbitrary AVA session UUIDs from the session API. |
| **How to use correlation ID?** | Read response header `ININ-Correlation-Id` from `POST .../sessions` and each `POST .../turns`. Open a Genesys support case and provide correlation ID + timestamp + `virtualAgentId`, `virtualAgentSessionId`, turn `id`. **Do not expect** a self-service API to fetch traces by that ID. |
| **What is NOT available via API?** | GET session/turn history; messages list; trace/logs under session; correlation lookup; full prompt/LLM trace; guaranteed `events` / `outputData` on every turn; echo of user `inputEvent` in turn response. |

---

## 1. OpenAPI — virtual agent sessions / turns

### Documented runtime endpoints (only two)

| Method | Path |
|--------|------|
| `POST` | `/api/v2/apps/agentic/virtualagents/{agentId}/sessions` |
| `POST` | `/api/v2/apps/agentic/virtualagents/{virtualAgentId}/sessions/{virtualAgentSessionId}/turns` |

Scope: `agentic-virtualagents-internal`. Visibility: **internal**.

**No** `GET` (or other) operations exist in swaggerall for:

- `.../sessions/{sessionId}`
- `.../sessions/{sessionId}/turns`
- `.../sessions/{sessionId}/messages`
- `.../trace`, `.../traces`, `.../logs`
- `.../conversations`, `.../analytics`

Prior probes in this repo (`simple-front-door-ava-report.json`, live probes 2026-06-04) match: **404** on session GET, **405** on turns GET, **404** on hypothetical trace/log paths.

### Turn response schema (`VirtualAgentSessionTurnResponse`)

| Field | OpenAPI meaning | Observed in session API testing |
|-------|-----------------|--------------------------------|
| `id` | Turn UUID | Always present on **201** |
| `previousTurn` | Link to prior turn | Often omitted |
| `prompts` | Agent text/voice segments | Always present for successful text turns |
| `nextAction` | Client instruction (`WaitForInput`, etc.) | Always present |
| `nextAction.outputData` | Structured agent output map | Documented; **often absent** unless agent returns structured output |
| `events` | “Metadata for the next action” (`type: object`, **no sub-schema**) | **Usually omitted** in live turn bodies; not a runtime trace |

**Turn request** (`VirtualAgentSessionTurnRequest`) carries user text only in **`inputEvent`** (`UserInput` + `alternatives[].transcript.text`). That is the sole API payload field for the user prompt.

### Turn response does **not** echo input or history

Live turn (2026-06-04, agent `Simple front door`, version `2.0`):

```json
{
  "id": "ca36a8a3-d10d-4737-84bb-5898f1e0c228",
  "prompts": { "outputLanguage": "en-us", "text": { "segments": [{ "type": "Text", "text": "..." }] } },
  "nextAction": { "type": "WaitForInput" }
}
```

Request body contained `inputEvent` with `"research topic"`; **response body did not reference it**. No conversation transcript array is defined on the turn response.

To prove “we sent this prompt,” the integrator must **log the outbound POST body** (and optionally correlate with turn `id` + `ININ-Correlation-Id`). A **201** proves the platform accepted the turn, not that a specific model path consumed the text as expected.

---

## 2. `apps/agentic` — analytics, traces, logs, conversations

### Entire `apps/agentic` surface (swaggerall, 19 path templates)

**Virtual Agents (AVA):** CRUD/publish for agents and versions + **session create** + **turn create** only.

**Agent Copilot (different product API):** includes readable session history:

- `GET /api/v2/apps/agentic/copilots/sessions`
- `GET /api/v2/apps/agentic/copilots/sessions/{sessionId}`
- `GET /api/v2/apps/agentic/copilots/sessions/{sessionId}/messages`
- `GET /api/v2/apps/agentic/copilots/sessions/{sessionId}/messages/{messageId}`

Copilot messages expose `content`, `originatingEntity` (`User` / `Assistant` / `System`), `dateSent` — **not** exposed for AVA session turns.

**Searched and absent** under `apps/agentic`:

- `/api/v2/apps/agentic/traces`, `/logs`
- Per-agent `.../virtualagents/{id}/analytics|conversations|audit|history` (repo probes → **404**)

### Platform “trace” paths (unrelated to AVA turns)

swaggerall lists only **6** paths containing `trace`:

- `/api/v2/diagnostics/trace` — **POST** client diagnostic trace upload (`TraceList`), not AVA retrieval
- `/api/v2/diagnostics/trace/backgroundassistant`
- Telephony SIP trace paths under `/api/v2/telephony/siptraces/...`

None reference virtual agent sessions or AI Studio agent turns.

### Analytics that *do* include user input (bot flows, not session API)

`GET /api/v2/analytics/botflows/{botFlowId}/reportingturns` returns `ReportingTurn` entities with **`userInput`**, `botPrompts`, `sessionId`, `askActionResult`, etc.

- Intended for **Architect bot flow** / Dialog Engine reporting sessions.
- Optional filter: `sessionId` query param (bot session id).
- **Probe (2026-06-04):** `reportingturns?sessionId=<AVA session UUID from POST /sessions>` returned **`{"entities":[]}`** whether `botFlowId` was a placeholder UUID or the virtual agent id — AVA session ids are **not** surfaced here for direct session-API traffic.

Other analytics (`/api/v2/analytics/conversations/...`, `/api/v2/analytics/agentcopilots/...`, `/api/v2/analytics/copilots/...`) are conversation/copilot aggregates — **no** documented link to AVA `virtualAgentSessionId` or turn-level prompt receipt for the internal session API.

---

## 3. Genesys Help / product surfaces (non-API)

Articles fetched from [Genesys Cloud Resource Center](https://help.mypurecloud.com/) (static/RSC content where available):

| Topic | What docs say | Relevance to session API turns |
|-------|----------------|--------------------------------|
| [About agentic virtual agents](https://help.mypurecloud.com/articles/about-agentic-virtual-agents/) | Monitoring via **Flow Insights**, **Optimization** dashboard, **Architect replay** when deployed through flows | Operational metrics / flow debugging — **not** a REST API for turn logs |
| [Test and troubleshoot agentic virtual agents](https://help.mypurecloud.com/articles/test-and-troubleshoot-agentic-virtual-agents/) | **AI Studio preview widget**, **Architect bot flow simulator**, **Architect replay** for flows connected to AVAs | UI validation; replay is for **bot flows**, not `POST .../turns` clients |
| [Preview an agentic virtual agent](https://help.mypurecloud.com/articles/preview-an-agentic-virtual-agent/) | In-product preview (roles, guardrails, channels); session restart in widget | No documented export of trace or transcript via Platform API |

**AI Studio “trace”** as a customer-retrievable log: **not** found in swaggerall and **not** described in AVA session API docs. Any in-UI trace (e.g. preview or future AI Studio features) should be treated as **console-only** unless Genesys publishes an API.

**Architect replay** applies when the AVA is reached through an **Architect Virtual Agent flow** (digital/voice bot path). Direct integrators calling `virtualagents/.../sessions/.../turns` bypass that path; replay will not show those HTTP turns unless the same interaction also runs through a flow.

### `ININ-Correlation-Id`

- Returned on **every** successful AVA session/turn response in this project (see `simple-front-door-ava-debug.json` response headers).
- Error bodies often include `contextId` (UUID); in probes it **matches** the response `ININ-Correlation-Id` header for that failed call.
- **Client-supplied** `ININ-Correlation-Id` on the request was **not** honored (server generated a new id per response in 2026-06-04 test).
- OpenAPI does **not** document a “get trace by correlation id” endpoint for AVA.
- Standard Genesys practice: provide correlation id to **Customer Care / support** for backend log correlation — not for tenant self-service download via Public API.

---

## 4. Practical logging strategy for integrators

### What to log on each turn (client-side)

1. **Request:** full `VirtualAgentSessionTurnRequest` JSON (`inputEvent`, `version`, `previousTurn.id` if used).
2. **Response:** HTTP status, body (`id`, `prompts`, `nextAction`, `events` if present), headers **`ININ-Correlation-Id`**, `Date`.
3. **Identifiers:** `virtualAgentId`, `virtualAgentSessionId`, turn `id`, agent `version`.
4. **Clock:** UTC timestamp; keep request/response pairs immutable for audits.

### What **201** means vs what it does not

- **Means:** Turn accepted; platform returned agent `prompts` and `nextAction`.
- **Does not mean:** You can later GET the same turn, retrieve server-side STT/NLU trace, or verify classification unless reflected in `prompts` / `nextAction.outputData` / rare `events`.

### When `outputData` / `events` help

- **`nextAction.outputData`:** Only when the agent definition returns structured fields (OpenAPI example: customer attributes). Useful for machine-readable outcomes, **not** a general execution trace.
- **`events`:** Schema-less object in spec; project experiments rarely received it on session API turns. Do not rely on it for “user prompt received” evidence.

### If the AVA runs inside Architect

- Use **Flow Insights**, **Optimization**, and **replay** for flow-mediated conversations.
- Consider **`analytics/botflows/.../reportingturns`** with the **bot flow’s** `sessionId` (from flow runtime), which includes **`userInput`** — still separate from direct session API UUIDs unless Genesys documents a mapping.

---

## 5. Live probe summary (mypurecloud.com, 2026-06-04)

| Probe | Result |
|-------|--------|
| `POST .../sessions` | **201**, header `ININ-Correlation-Id` present |
| `POST .../turns` with `UserInput` text | **201**, body keys: `id`, `prompts`, `nextAction` only |
| `GET .../sessions/{id}/turns` | **405** |
| `GET .../sessions/{id}/trace`, `/logs`, `/messages` | **404** |
| `GET .../virtualagents/{id}/analytics`, `/conversations` | **404** |
| `GET /api/v2/apps/agentic/traces`, `/logs` | **404** |
| `GET analytics/botflows/.../reportingturns?sessionId=<AVA session id>` | **200**, `entities: []` |

Example correlation ids from this session (for support ticket format only): session create `a16f7332-0833-4d46-976d-f83ee82c30c8`, turn `5bf568a6-7e70-4d8d-9785-4b75029359b0` (superseded by any new traffic).

---

## 6. Not available via API (checklist)

- Server-side retrieval of user `inputEvent` / transcript for a past turn
- Full turn or session history for AVA session API
- Turn-level LLM/tool/guardrail trace export
- Lookup of backend logs by `ININ-Correlation-Id`
- Dedicated AVA runtime logging endpoints under `apps/agentic`
- Mapping documented from `ININ-Correlation-Id` → AI Studio UI trace
- Architect replay coverage for pure session-API integrations (without flow)
- Guaranteed presence of `events` or `outputData` on every turn response

---

## 7. References

- OpenAPI: `https://api.{region}/api/v2/docs/swaggerall`
- API Explorer: [apicentral.genesys.cloud](https://apicentral.genesys.cloud/api-explorer-standalone)
- Help: [About agentic virtual agents](https://help.mypurecloud.com/articles/about-agentic-virtual-agents/), [Test and troubleshoot agentic virtual agents](https://help.mypurecloud.com/articles/test-and-troubleshoot-agentic-virtual-agents/), [Preview an agentic virtual agent](https://help.mypurecloud.com/articles/preview-an-agentic-virtual-agent/)
