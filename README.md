# Dirijor – Private Agent Network OS
**The world's first human-first Private Agent Network Operating System**

Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

**Vision:**  
Cutting-edge platform for safety & security of LLM agents and humans.  
One-click private network configurations across unlimited virtual instances on any private cloud (DigitalOcean, Hetzner, Proxmox, etc.).  
Drag-and-drop canvas + orchestration + multi-agent consensus + verified semantic cache = zero hallucination, zero exposure.

**Quick Start**  
1. `git clone` this private repo  
2. `docker compose up` → supervisor API on http://localhost:8000 (frontend is not in Compose yet)  
3. Network Canvas UI: `cd frontend && npm install && npm run dev` → http://localhost:3000 (redirects to `/canvas`)

**Documentation**

Narrative docs live in [`docs/`](docs/) and are organized by what you're trying to do
([Diátaxis](https://diataxis.fr/) framework):

- [`docs/index.md`](docs/index.md) — elevator pitch (10s / 60s / 5min versions) + "start here" map.
- [`docs/product/why-dirijor.md`](docs/product/why-dirijor.md) — the long-form answer to *"what is the point of your application?"*.
- [`docs/product/concepts/`](docs/product/concepts/) — Realms, Consensus, Zero-trust by default.
- [`docs/guides/tutorials/01-first-realm.md`](docs/guides/tutorials/01-first-realm.md) — 10–15 min hands-on.
- [`docs/reference/supervisor-api.md`](docs/reference/supervisor-api.md) — authoritative v0.1 HTTP contract (see below).
- [`docs/architecture/overview.md`](docs/architecture/overview.md) + [`docs/architecture/adr/`](docs/architecture/adr/) — system walkthrough and the *why* behind the big engineering bets (ADR-0001 LangGraph supervisor, ADR-0002 consensus ≥95%).

Browse locally with:

```bash
pip install -r docs/requirements.txt
mkdocs serve     # http://127.0.0.1:8000
```

## Dirijor Supervisor (backend/dirijor-core) — v0.1 HTTP contract

Story 3.1 hardened the supervisor's `GET /` and `GET /health` endpoints into a
structured, Pydantic-backed contract (see `backend/dirijor-core/supervisor.py`).
Story 3.2 replaced the `POST /consensus` placeholder with a real multi-agent
debate loop and bumped `schema_version` from 1 → 2 (additive — v0.1 keys
preserved). Story 3.3 added a WebSocket channel for live canvas updates and
bumped `schema_version` from 2 → 3 (additive — all v2 keys preserved; `GET /`
gains a `realtime` block and `GET /health` gains a `realtime_channel`
dependency). Story 4.1 adds verified semantic cache HTTP surfaces and bumps
`schema_version` to **5**. Story **4.2** shipped optional anomaly policy +
quarantine HTTP surfaces (`GET /safety/quarantine/...`, gated
`POST /safety/signal`) and bumped `schema_version` to **6** (additive — all
prior keys preserved). Story **4.3** adds gated **`POST /audit/export`**
(immutable audit ZIP bundles) and bumps `schema_version` to **7**.

- `GET /` — service identity + aggregate status + per-dependency readiness.
- `GET /health` — same dependency map, `timestamp`, and HTTP **200** when every
  `required: true` dependency is ready; **HTTP 503** (same body shape) when any
  required dependency is not ready.
- `POST /consensus` — real debate loop (configurable rounds + quorum threshold,
  per-round votes, explicit `termination_reason`, safe no-decision path). See
  the section below for the request/response contract.
- The Docker image ships a `HEALTHCHECK` that calls `GET /health`, so
  docker / compose / K8s pick up degraded state automatically.

### `GET /` sample response

```json
{
  "service": "dirijor-supervisor",
  "version": "0.1.0",
  "schema_version": 7,
  "status": "operational",
  "consensus_engine": "ready",
  "uptime_s": 12.4,
  "dependencies": {
    "graph_compiled":    { "ready": true,  "required": true,  "detail": null },
    "consensus_engine":  { "ready": true,  "required": true,  "detail": null },
    "realtime_channel":  { "ready": true,  "required": true,  "detail": null },
    "realm_manager":     { "ready": true,  "required": true,  "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "not configured" },
    "anomaly_policy":    { "ready": true,  "required": false, "detail": null },
    "mesh":              { "ready": false, "required": false, "detail": "planned — see Story 5.1" }
  },
  "realtime": {
    "connections": 0,
    "heartbeat_interval_s": 15.0,
    "schema_version": 7
  }
}
```

### `GET /health` sample response (same body on 200 and 503)

```json
{
  "status": "ok",
  "version": "0.1.0",
  "schema_version": 7,
  "uptime_s": 12.4,
  "timestamp": "2026-04-16T10:12:44.117Z",
  "checks": {
    "graph_compiled":    { "ready": true,  "required": true,  "detail": null },
    "consensus_engine":  { "ready": true,  "required": true,  "detail": null },
    "realtime_channel":  { "ready": true,  "required": true,  "detail": null },
    "realm_manager":     { "ready": true,  "required": true,  "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "not configured" },
    "anomaly_policy":    { "ready": true,  "required": false, "detail": null },
    "mesh":              { "ready": false, "required": false, "detail": "planned — see Story 5.1" }
  }
}
```

### `POST /consensus` — debate loop contract (schema v2)

All request fields are optional. Defaults: `max_rounds=3`, `threshold=0.95`
(PRD: ≥95% agreement on high-stakes outputs). An empty body or a bare
`?query=foo` query-string are both valid. The response's `messages` field
mirrors the request: it is `[query]` when a query is supplied and `[]`
otherwise — both response samples below assume the request in the first
code block, so the same `"Is the staging DB patched?"` surfaces on both
the threshold-reached and no-decision paths.

Request body:

```json
{
  "query": "Is the staging DB patched?",
  "opinions": [
    { "agent_id": "grok",   "opinion": "yes", "confidence": 0.9 },
    { "agent_id": "harper", "opinion": "yes", "confidence": 0.95 },
    { "agent_id": "claude", "opinion": "yes", "confidence": 0.99 }
  ],
  "max_rounds": 3,
  "threshold": 0.95
}
```

Response — threshold reached (HTTP 200):

```json
{
  "messages": ["Is the staging DB patched?"],
  "consensus_score": 1.0,
  "verified_facts": [],
  "semantic_cache_status": "skipped",
  "semantic_cache_reason": "query_vector_missing",
  "decision": "yes",
  "votes": [
    { "agent_id": "grok",   "opinion": "yes", "confidence": 0.9,  "round": 1 },
    { "agent_id": "harper", "opinion": "yes", "confidence": 0.95, "round": 1 },
    { "agent_id": "claude", "opinion": "yes", "confidence": 0.99, "round": 1 }
  ],
  "termination_reason": "threshold_reached",
  "rounds": 1,
  "threshold": 0.95
}
```

Response — no decision after max rounds (still HTTP 200; `decision: null`
is a normal outcome, not an error — callers check `decision` / `termination_reason`,
not the HTTP code):

```json
{
  "messages": ["Is the staging DB patched?"],
  "consensus_score": 0.3333,
  "verified_facts": [],
  "semantic_cache_status": "skipped",
  "semantic_cache_reason": "query_vector_missing",
  "decision": null,
  "votes": [
    { "agent_id": "a", "opinion": "yes",   "confidence": 1.0, "round": 1 },
    { "agent_id": "b", "opinion": "no",    "confidence": 1.0, "round": 1 },
    { "agent_id": "c", "opinion": "maybe", "confidence": 1.0, "round": 1 },
    { "agent_id": "a", "opinion": "yes",   "confidence": 1.0, "round": 2 },
    { "agent_id": "b", "opinion": "no",    "confidence": 1.0, "round": 2 },
    { "agent_id": "c", "opinion": "maybe", "confidence": 1.0, "round": 2 }
  ],
  "termination_reason": "max_rounds_exhausted",
  "rounds": 2,
  "threshold": 0.95
}
```

`termination_reason` is one of: `threshold_reached`, `max_rounds_exhausted`,
`single_opinion_shortcut`, `no_opinions`. On LangGraph compile failure the
endpoint keeps returning HTTP **503** with only the v0.1 three-key body
(`messages`, `consensus_score`, `verified_facts`) so strict parsers survive
degradation — v2 additive keys appear only on the 200 path.

### `WS /ws/realm/{realm_id}` — live canvas channel (schema v3, Story 3.3)

v0.1 WebSocket channel that streams topology deltas, realm metrics, and HITL
queue events from Dirijor Core to the Private Realm canvas. Replaces the prior
client-side stub so the canvas now reflects real backend state.

- **Handshake:** `realm_id` must match `^[a-zA-Z0-9_-]{1,64}$`. Malformed ids
  are rejected with close code **4401** (`invalid_realm_id`); authorization
  failures close with **4403** (`realm_forbidden`). Well-formed connections
  receive `session.hello` with a server-assigned `connection_id`.
- **Heartbeats:** server emits a `heartbeat` frame every
  `HEARTBEAT_INTERVAL_S` (default 15 s). If a heartbeat `send` fails, the
  session is closed with **1011** (`heartbeat_send_failed`) and evicted from
  the registry — the client should treat 1011 as retryable.
- **Reconnect policy:** the frontend client uses exponential backoff with
  jitter (500 ms → capped at 30 000 ms) for up to `MAX_RECONNECT_ATTEMPTS=8`
  attempts. Close codes `4401` / `4403` are client-fault and do **not**
  retry; `1006` / `1011` and clean `1000` closes do.
- **Event types:** `session.hello`, `topology.delta`, `metrics.update`,
  `hitl.pending`, `heartbeat`, `session.bye`. Each server frame is a strict
  **six-key** JSON object: `type`, `schema_version`, `realm_id`, `ts`,
  `seq`, `payload` (`RealtimeEnvelope` — `extra="forbid"` on the model).
  `connection_id` lives **inside** `session.hello.payload`, not on the
  envelope. Additive payload fields bump documentation and may bump
  `SCHEMA_VERSION`; top-level envelope keys are fixed until a major bump.
- **Readiness:** the readiness registry exposes a `realtime_channel`
  dependency (`required: true` in v0.1). `GET /` includes a `realtime`
  summary: `{ connections, heartbeat_interval_s, schema_version }` (see
  `RealtimeSummary` in `supervisor.py`).

Frontend wiring: set `NEXT_PUBLIC_DIRIJOR_WS_URL` to the base URL (e.g.
`ws://localhost:8000/ws/realm`) before running `npm run dev`; when unset the
canvas stays in `idle` mode so the UI is still runnable without a backend.
See `frontend/.env.example` for the default local value.

### Realm provisioning (Story 2.1)

Story 2.1 adds the async realm-spin HTTP contract — the canvas "Spin realm"
button now round-trips through the supervisor instead of a client-side
`setTimeout` stub. The endpoint pair follows the same stability discipline
as `/consensus` and `/ws`: closed `SpinError.code` enum, `ConfigDict(extra="forbid")`
on every Pydantic model, additive-only response shapes. Story 2.2 bumped
`SCHEMA_VERSION` to `4` (destroy route + SpinError extensions); Story 4.1
bumped it to `5` (semantic-cache endpoints + consensus cache fields); Story
4.2 bumped it to `6` (Safety Fortress quarantine list + signal hook + optional
consensus `realm_id`) — see
[`docs/reference/supervisor-api.md`](docs/reference/supervisor-api.md).

- **`POST /realms/spin`** — enqueue a job. Accepts
  `{ realm_description, adapter_hint?, realm_id?, agent_count? }`; returns
  **202** with `{ job_id, realm_id, phase: "validating", adapter, created_at, status_url, schema_version }`.
  Structured errors: `400 validation_failed` / `400 invalid_realm_id` /
  `400 adapter_unknown` / `409 realm_id_conflict` / `503 realm_manager_unavailable`.
- **`GET /realms/{job_id}`** — poll job state. Returns `SpinJob` (`phase`
  advances `validating → provisioning → ready | failed`; `updated_at` is
  monotonic; `outputs` populated on `ready`, `error` populated on `failed`).
  Unknown ids → `404 job_not_found`.
- **Adapter abstraction.** v0.1 ships `LocalNoopAdapter` (simulates
  provisioning with `PROVISION_DELAY_S = 0.5s`, returns
  `mesh_endpoint: noop://<realm_id>` **(local-noop)**). Story 2.2 registers
  `TerraformAdapter` behind the same `RealmAdapter` `Protocol`; Story 2.3 wraps `.provision`
  with default-deny egress.

```bash
# Smoke: spin + poll (local-noop — noop:// mesh endpoint)
JOB=$(curl -s -X POST http://localhost:8000/realms/spin \
  -H 'Content-Type: application/json' \
  -d '{"realm_description":"smoke test","agent_count":3}' | jq -r .job_id)
curl -s http://localhost:8000/realms/$JOB | jq
```

### Terraform adapter (Story 2.2)

When **`DIGITALOCEAN_TOKEN`** is set to a non-empty value and a **`terraform`**
binary is on `PATH` (or **`DIRIJOR_TERRAFORM_BINARY`** points at an existing
executable), Core registers **`terraform-digitalocean`** and provisions a
DigitalOcean VPC via `terraform/modules/private-realm/`. The default Docker
image does **not** include Terraform — operators who need this path install
Terraform in a custom image layer or run the supervisor on the host.

```bash
export DIGITALOCEAN_TOKEN='<replace-with-your-DO-personal-access-token>'
export DIRIJOR_TERRAFORM_BINARY=/usr/local/bin/terraform   # optional if `terraform` is on PATH

JOB=$(curl -s -X POST http://localhost:8000/realms/spin \
  -H 'Content-Type: application/json' \
  -d '{"realm_description":"terraform smoke","adapter_hint":"terraform-digitalocean","agent_count":3}' | jq -r .job_id)
curl -s http://localhost:8000/realms/$JOB | jq

curl -s -X DELETE http://localhost:8000/realms/$JOB
# Poll GET until outputs.destroyed == true
```

Frontend wiring: set `NEXT_PUBLIC_DIRIJOR_API_URL` to the supervisor base
URL (defaults to `http://localhost:8000` when unset). The client hook
`useRealmSpin` polls `GET /realms/{job_id}` every 750 ms with a 60 s
wall-time cap; on timeout it synthesizes a `poll_timeout` error so the UI
never loops forever. See `frontend/.env.example`.

### Running the supervisor test suite

From the repository root:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/dirijor-core/requirements-dev.txt
python -m pytest backend/dirijor-core/tests
```

Tests run in-process against `fastapi.testclient.TestClient`; no network, no port binding.

Built to never let you hallucinate again.  
Ready for Phase 2 (full 12-cloud Terraform + live topology + marketplace).
