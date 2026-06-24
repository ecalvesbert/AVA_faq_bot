# AVA session API vs Architect flow deployment

**Research date:** 2026-06-03  
**Environment:** `mypurecloud.com` (profile `default` in `~/.gc/config.toml`)  
**Agent under test:** Simple front door — `1f7dd771-c326-44bf-a12e-eff153fd2da1`

## Executive answer

| Question | Answer |
|----------|--------|
| Does `POST /api/v2/apps/agentic/virtualagents/{id}/sessions` **require** the AVA to be deployed to an Architect flow? | **No — not per OpenAPI, and not in practice for this org.** Flow deployment is a separate channel for routing live interactions; the session API is a direct programmatic entry point. |
| Confidence | **High** for “not documented / not enforced”; **medium** that no hidden gate exists in all org configs (only this tenant was exercised). |
| Is Simple front door deployed to an Architect flow? | **No** — Architect dependency tracking reports **zero** consuming resources for the agent and for versions `2.0` / `4.0`, and no flow in the org’s flow list embeds this agent UUID. |

---

## 1. OpenAPI (`swaggerall`)

**Source:** `GET https://api.mypurecloud.com/api/v2/docs/swaggerall` → `publicapi-v2-latest-internal.json` (fetched 2026-06-03).

### Session create operation

- **Path:** `POST /api/v2/apps/agentic/virtualagents/{agentId}/sessions`
- **Operation ID:** `postAppsAgenticVirtualagentSessions`
- **Summary:** “Create a virtual agent session.”
- **Description:** *(empty)*
- **Tags:** `AI Studio`, `Virtual Agents`
- **Visibility:** `x-genesys-visibility: internal`
- **OAuth scope:** `agentic-virtualagents-internal`
- **Permission:** `agentic:virtualAgentSession:add` (ALL)

**No mention** of Architect, flow, deploy, integration, or channel deployment in the operation text, parameters, or error catalog for this path.

### Request body (`CreateVirtualAgentSession`)

| Field | Required (schema) | Notes |
|-------|-------------------|--------|
| `version` | Yes | Version string (e.g. `"2.0"`) |
| `channel` | Yes | `VirtualAgentSessionChannel` — `name`: `Messaging` \| `Call`; optional modes / `userAgent` |
| `language` | No in schema | Often required in practice if omitted with other fields |
| `inputData` | No | Arbitrary map |

Again, **no** flow ID, Architect reference, or deployment identifier.

### Other `virtualagents` paths in spec (10 total)

There are **no** `/deployments`, `/integrations`, `/architect`, or `/flows` sub-resources under `virtualagents`. Publishing is modeled via version **jobs** (`POST .../versions/{versionId}/jobs`), which updates version status (`TestReady` / `ProductionReady`) — not Architect deployment.

### Related platform concepts (same spec, different surfaces)

- `Flow` / `FlowVersion` include `agenticVirtualAgent` and `agenticVirtualAgentEnabled` booleans — these describe **flows upgraded for the agentic VA runtime**, not prerequisites on the session API.
- Turn `nextAction.outputData` is documented as data “returned from the Agentic Virtual Agent” (useful when a flow consumes AVA output), but that does not state sessions require a flow.

---

## 2. Live API — Simple front door agent and versions

### Agent (`GET .../virtualagents/{id}`)

| Field | Value (2026-06-03) |
|-------|---------------------|
| `name` | Simple front door |
| `status` | `Published` |
| `latestProductionReadyVersion` | `5.0` |
| `latestSavedVersion` | `5.0` |

No deployment, flow, Architect, bot, or channel fields on the `VirtualAgent` resource (matches OpenAPI `VirtualAgent` definition).

### Versions `2.0` and `4.0` (`GET .../versions/{version}`)

Both return:

- `status`: `ProductionReady`
- `definition`: role, instructions, guardrails, tools, events, configuration — **no** flow/architect/deployment linkage

---

## 3. Probed paths (not in OpenAPI)

| Path | HTTP |
|------|------|
| `GET .../virtualagents/{id}/deployments` | **404** |
| `GET .../integrations`, `/channels`, `/architect`, `/flows` | **404** (same pattern) |

---

## 4. Architect dependency tracking

AVA object type in dependency API: `AGENTICVIRTUALAGENT` (and `AGENTICVIRTUALAGENTVERSION` for versioned consumers).

### `GET /api/v2/architect/dependencytracking/consumingresources`

“What Architect resources **consume** this AVA?”

| Query | `total` |
|-------|---------|
| `id={agentId}&objectType=AGENTICVIRTUALAGENT` | **0** |
| `id={agentId}&objectType=AGENTICVIRTUALAGENTVERSION&version=2.0` | **0** |

### `GET /api/v2/architect/dependencytracking/object`

Returns the AVA as a tracked object (`name`: “Simple front door”, `type`: `AGENTICVIRTUALAGENT`) — confirms the agent exists in Architect’s dependency graph, but **nothing consumes it**.

### Flow list scan

- Paginated `GET /api/v2/flows` (**228** flows): **no** entity JSON contained agent UUID `1f7dd771-c326-44bf-a12e-eff153fd2da1`.
- Org has other agentic-enabled **BOT** / **DIGITALBOT** flows (`agenticVirtualAgentEnabled: true`), e.g. “Zach (ABC Co)”, “Edward” — separate from Simple front door.
- Inbound flow “ABC Co - Agentic Virtual Agent” exists but its published configuration does **not** reference Simple front door’s UUID (inspected published configuration).

---

## 5. Empirical session create (without flow deployment)

`POST .../virtualagents/1f7dd771-c326-44bf-a12e-eff153fd2da1/sessions` with `version: "2.0"`, `language: en-US`, `channel.name: Messaging`:

- **HTTP 201**
- Session `id` returned (example run: `f9b11773-b87b-42d7-95af-87d964d0ddb1`)

Prior project artifacts (`simple-front-door-ava-trace-refs.json`, `simple-front-door-ava-report.json`) also show successful session/turn traffic on versions `1.0` / `2.0` while debugging comfort-statement behavior.

This demonstrates the session API works when dependency tracking shows **no** Architect consumer.

---

## 6. Public web / help documentation

- **Genesys Cloud Developer Center** pages for this internal operation are SPA shells without crawlable prerequisites (JavaScript required).
- **No** dedicated public help article was retrieved for “agentic virtual agent session API” linking sessions to mandatory Architect deployment.
- **API Central / internal explorer** aligns with OpenAPI: create session + turns only; no deployment prerequisite text.

**Conclusion from web pass:** **Unknown** for a formal product doc sentence; **consistent with optional** flow deployment given API design and tenant behavior.

---

## What *is* required (documented or observed)

1. Valid **virtual agent ID** and **version** string.
2. **OAuth** with scope `agentic-virtualagents-internal` and permission `agentic:virtualAgentSession:add`.
3. **Request body** satisfying validation (`channel`, `version`; `language` commonly required in practice).
4. Reasonable inference (not explicit in session op description): version should exist and be runnable — here `ProductionReady` on tested versions; parent agent `Published`.

**Architect flow deployment is not listed** and was **not enforced** for Simple front door in this org.

---

## When flow deployment still matters (product context)

Deploying an AVA into an Architect flow (or enabling agentic VA on a bot/digital flow) is the path for **orchestrated contact-center routing** (voice, messaging widgets tied to flows, transfers, etc.). That is **orthogonal** to calling the **internal session + turns API** for simulators, custom apps, or direct integrations—as evidenced by successful sessions with zero consuming Architect resources.

---

## References

- OpenAPI: `publicapi-v2-latest-internal.json` via `/api/v2/docs/swaggerall`
- Existing project notes: `ava-session-api-doc.md`
- Live probes: `mypurecloud.com`, profile `default`, 2026-06-03
