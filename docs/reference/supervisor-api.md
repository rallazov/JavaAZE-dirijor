<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# Supervisor HTTP API — v0.1 contract

> **Contract hardened by Story 3.1** (done 2026-04-16). See the
> implementation artifact at `_bmad-output/implementation-artifacts/3-1-supervisor-hardening-health-endpoints.md`
> (in the repo) for the full acceptance criteria and the test matrix.

This page is **authoritative reference**. It describes exactly what the
v0.1 supervisor exposes — no opinions, no recommendations. For the
*why* behind this contract, see
[Architecture — Overview](../architecture/overview.md) and
[ADR-0001](../architecture/adr/0001-langgraph-supervisor.md).

## Stability policy

- `schema_version` is an integer. **Additive** changes bump minor
  (implicit) — new keys may appear. **Breaking** changes (removal,
  rename, type change on an existing key) require a **major bump** of
  `schema_version`.
- Keys present in v0.1 **will not** be removed or renamed without a
  major bump. This is AC 4 / AC 5 of Story 3.1 and the practical
  reading of *"keep API contracts stable when iterating"* from
  [`docs/project-context.md`](../project-context.md).
- Callers that consume `service`, `version`, `status`, `consensus_engine`
  (the v0.1 superset) will continue to work across minor bumps.

| Field | Value | Meaning |
|---|---|---|
| `SERVICE_VERSION` | `"0.1.0"` | Module constant; `FastAPI(version=...)` and every response read this. |
| `SCHEMA_VERSION` | `3` | Contract shape version. Bumps on **additive** change too so clients can detect feature availability; breaking changes require a **major** bump. Story 3.2 bumped 1→2 (debate loop), Story 3.3 bumped 2→3 (WebSocket channel + `realtime` block). |

## Endpoints at a glance

| Method | Path | Purpose | Status codes |
|---|---|---|---|
| `GET`  | `/`                           | Service identity, aggregate status, per-dependency readiness          | `200` |
| `GET`  | `/health`                     | Liveness + readiness with ISO-8601 timestamp                          | `200` (ready) / `503` (degraded) |
| `POST` | `/consensus`                  | Multi-agent debate loop (Story 3.2 — real, configurable threshold)    | `200` / `503` (if graph unavailable) |
| `WS`   | `/ws/realm/{realm_id}`        | Live topology / metrics / HITL events for the Private Realm canvas    | accept `101` / close `4401`, `4403`, `1011` |

The Docker image ships a stdlib `HEALTHCHECK` that calls `GET /health`
every 15s, so Docker / Compose / Kubernetes pick up degraded state
automatically with no extra configuration.

## Common shapes

### `DependencyCheck`

Every dependency in the readiness registry resolves to this shape:

```json
{
  "ready":    true,
  "required": true,
  "detail":   null
}
```

- `ready` (`bool`) — can this dependency serve right now?
- `required` (`bool`) — does the supervisor report `operational` / HTTP 200 without it? Planned deps are `required: false`.
- `detail` (`string | null`) — human-readable reason when not ready. For planned deps, format is `"planned — see Story X.Y"`.

Probes **never raise**. Internal exceptions are caught and surfaced as
`ready: false, detail: "probe raised: <exc>"` (Story 3.1 AC 2).

### Aggregate `status` values

Used on both `GET /` and (via the `/health` 200/503 pairing) `GET /health`:

| Value | Meaning |
|---|---|
| `operational` / `ok` | Every `required: true` dependency is `ready: true`. |
| `degraded` | At least one required dependency is not ready. `/health` returns **503** with the same body shape. |
| `starting` | Cold-start grace window (`uptime_s < 1.0s`) while readiness resolves for the first time. |

---

## `GET /`

**Purpose.** Service identity + aggregate status + dependency summary.
Intended for dashboards, debugging, and the future canvas bind.

### Response (`200`)

Pydantic model: `RootStatus`.

```json
{
  "service": "dirijor-supervisor",
  "version": "0.1.0",
  "schema_version": 3,
  "status": "operational",
  "consensus_engine": "ready",
  "uptime_s": 12.4,
  "dependencies": {
    "graph_compiled":    { "ready": true,  "required": true,  "detail": null },
    "consensus_engine":  { "ready": true,  "required": true,  "detail": null },
    "realtime_channel":  { "ready": true,  "required": false, "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "planned — see Story 4.1" },
    "mesh":              { "ready": false, "required": false, "detail": "planned — see Story 5.1" }
  },
  "realtime": {
    "transport": "websocket",
    "heartbeat_interval_s": 15.0,
    "active_connections": 0,
    "active_realms": 0
  }
}
```

### Field reference

| Field | Type | Notes |
|---|---|---|
| `service` | `string` (`"dirijor-supervisor"`) | Stable v0.1 key. |
| `version` | `string` (semver) | Reads from `SERVICE_VERSION` module constant. |
| `schema_version` | `int` | See stability policy above. |
| `status` | `"operational" \| "degraded" \| "starting"` | Computed from `required` deps. |
| `consensus_engine` | `"ready" \| "unavailable"` | v0.1 superset key — mirrors `graph_compiled.ready`. |
| `uptime_s` | `float` | Seconds since module load (`time.monotonic()`). |
| `dependencies` | `{ [name: string]: DependencyCheck }` | Same map shape as `/health.checks`. |
| `realtime` | `RealtimeSummary` | Story 3.3 additive block. Shape: `{ transport: "websocket", heartbeat_interval_s: float, active_connections: int, active_realms: int }`. Counts reflect live WebSocket sessions; they are best-effort (not persisted across restarts). |

---

## `GET /health`

**Purpose.** Liveness + readiness for Docker `HEALTHCHECK`, Kubernetes
`readinessProbe`/`livenessProbe`, uptime monitors. Body shape is
**identical on 200 and 503** so consumers don't need two codepaths.

### Response — `200 OK` (ready)

Pydantic model: `HealthStatus`.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "schema_version": 3,
  "uptime_s": 12.4,
  "timestamp": "2026-04-16T10:12:44.117Z",
  "checks": {
    "graph_compiled":    { "ready": true,  "required": true,  "detail": null },
    "consensus_engine":  { "ready": true,  "required": true,  "detail": null },
    "realtime_channel":  { "ready": true,  "required": false, "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "planned — see Story 4.1" },
    "mesh":              { "ready": false, "required": false, "detail": "planned — see Story 5.1" }
  }
}
```

### Response — `503 Service Unavailable` (degraded)

**Same body shape, different values.** The server emits via
`JSONResponse(status_code=503, content=payload.model_dump())` so the
structure is indistinguishable from the 200 shape — only the HTTP
status code and `status` field differ.

```json
{
  "status": "degraded",
  "version": "0.1.0",
  "schema_version": 3,
  "uptime_s": 342.0,
  "timestamp": "2026-04-16T10:18:02.554Z",
  "checks": {
    "graph_compiled":    { "ready": false, "required": true,  "detail": "compile failed: <reason>" },
    "consensus_engine":  { "ready": false, "required": true,  "detail": "compile failed: <reason>" },
    "realtime_channel":  { "ready": true,  "required": false, "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "planned — see Story 4.1" },
    "mesh":              { "ready": false, "required": false, "detail": "planned — see Story 5.1" }
  }
}
```

### Guarantees

- **`/health` never raises 5xx from probe exceptions.** Any exception
  inside a probe is caught and surfaced as `ready: false,
  detail: "probe raised: <exc>"` (Story 3.1 AC 2).
- **Timezone.** `timestamp` uses `datetime.now(timezone.utc).isoformat()`
  and always carries a `Z` suffix. Not the deprecated `datetime.utcnow()`.
- **200 vs 503 decision rule.** 200 iff every `required: true` dependency
  is `ready: true`; 503 otherwise.

---

## `POST /consensus`

**Purpose.** v0.1 placeholder consensus call. The real debate loop
(configurable rounds, quorum, termination reasons) lands in
**Story 3.2** — see [Concept — Consensus](../product/concepts/consensus.md)
and [ADR-0002](../architecture/adr/0002-consensus-threshold-95.md).

### Request

```
POST /consensus?query=<string>
```

(Query string param; v0.1 keeps the signature stable for the existing
callers — see AC 4 of Story 3.1.)

### Response — `200 OK`

Exactly three top-level keys:

```json
{
  "messages":         [ /* LangGraph state messages */ ],
  "consensus_score":  0.97,
  "verified_facts":   [ /* list of cache-grounded facts (placeholder) */ ]
}
```

### Response — `503 Service Unavailable`

If the LangGraph workflow failed to compile at service start
(`graph is None`), `/consensus` returns **503** with **exactly the same
top-level key set** — no extra `detail` key, no shape drift (AC 4
regression guard, enforced by `test_consensus_degraded_keeps_v01_key_set`).

```json
{
  "messages":        [],
  "consensus_score": 0.0,
  "verified_facts":  []
}
```

To diagnose *why*, poll `GET /health` and read
`checks.graph_compiled.detail`. The 503 on `/consensus` is the signal;
`/health` is the explanation.

### Current limitations (v0.1, intentional)

- `consensus_score` is a **placeholder constant** (`0.97`). Story 3.2
  replaces this with the real debate-loop score.
- `verified_facts` is populated only when the verified semantic cache
  (Story 4.1) is online. Today it's `[]`.
- No streaming on `/consensus` itself. Per-round state may be streamed
  over the `WS /ws/realm/{realm_id}` channel in a future story; the
  Story 3.3 channel only carries `topology.delta`, `metrics.update`, and
  `hitl.pending` today.

---

## `WS /ws/realm/{realm_id}`

**Purpose.** Live, server-push channel from Dirijor Core to the Private
Realm canvas, shipped by **Story 3.3** (done 2026-04-16). Replaces the
previous client-side stub that faked events from `setTimeout`.

### Handshake

```
GET /ws/realm/{realm_id}    (HTTP 101 Upgrade to WebSocket)
```

`realm_id` **must** match `^[a-zA-Z0-9_-]{1,64}$`. The route is the
single entry point for all realm traffic; different realms **do not
share frames** (broadcast is strictly scoped to `realm_id`).

| Close code | Reason                        | Retry? | When it fires |
|---|---|---|---|
| `4401`     | `invalid_realm_id`            | no     | `realm_id` fails the regex. |
| `4403`     | `realm_forbidden`             | no     | `_authorize_realm(realm_id)` returns false. v0.1 allow-all stub — real auth lands with the Supabase cutover. |
| `1011`     | `heartbeat_send_failed`       | yes    | Server could not emit a heartbeat (transport unhealthy). Session is evicted from the registry. |
| `1000`     | clean close                   | yes    | Client closed intentionally; reconnect if the canvas is still mounted. |

On a successful handshake the first frame the server sends is
`session.hello`, carrying a `connection_id` the server generated for this
session.

### Envelope

Every frame (both directions, though today the server is authoritative
and inbound frames are discarded) uses the same envelope. The model has
`ConfigDict(extra="forbid")` — unknown keys are a hard error, so
additive evolution must go through `SCHEMA_VERSION`.

```json
{
  "v": 1,
  "type": "topology.delta",
  "ts": "2026-04-16T10:12:44.117Z",
  "realm_id": "demo",
  "connection_id": "b7b7…",
  "payload": { /* type-specific */ }
}
```

| Field | Type | Notes |
|---|---|---|
| `v` | `int` (`1`) | Envelope version. Independent of `SCHEMA_VERSION`; only bumps if the envelope itself changes shape. |
| `type` | enum | `session.hello`, `topology.delta`, `metrics.update`, `hitl.pending`, `heartbeat`, `session.bye`. |
| `ts` | ISO-8601 UTC (`Z` suffix) | Server clock. |
| `realm_id` | `string` | Always echoed so the client can multiplex safely. |
| `connection_id` | `string` (UUID) | Stable for the lifetime of the TCP session. |
| `payload` | `object` | Type-specific body. See below. |

### Event types

- `session.hello` — first frame. `payload.server_version` = `SERVICE_VERSION`, `payload.schema_version` = `SCHEMA_VERSION`, `payload.heartbeat_interval_s`.
- `heartbeat` — emitted every `HEARTBEAT_INTERVAL_S` (default **15 s**). Empty payload.
- `topology.delta` — `payload.agents?: AgentPatch[]`, `payload.edges?: EdgePatch[]`. Each patch carries an `id`; `_tombstone: true` means "remove this id". All other keys are a shallow upsert.
- `metrics.update` — `payload` is a partial of the canvas `RealmMetrics` shape. Shallow-merged into the store.
- `hitl.pending` — `payload.action` is a full `CriticalAction`; dedup by `action.id`.
- `session.bye` — reserved for graceful shutdown. Not emitted today.

### Reconnect policy (client-side contract)

The canvas client (`frontend/lib/dirijor-realtime.ts`) implements:

- Exponential backoff with jitter. Base 500 ms, doubled each attempt, capped at **30 000 ms**, ±10 % jitter.
- `MAX_RECONNECT_ATTEMPTS = 8`. After that the client stays in `error`.
- Close codes `4401` / `4403` are **client-fault** and do **not** retry. Everything else (including `1006`, `1011`, and clean `1000`) retries.

### Readiness & operator visibility

- `dependencies.realtime_channel` / `checks.realtime_channel` — the
  probe is `"always ready"` today (the WS registry is in-process and
  cheap). It's `required: false` so the supervisor doesn't go
  `degraded` just because no canvas client is connected.
- `GET /` → `realtime.active_connections` / `realtime.active_realms`
  are best-effort counters against `_CONNECTIONS: dict[str, set[_WsSession]]`.

### Worked example — open a connection with `websocat`

```bash
# Replace `demo` with any id matching ^[a-zA-Z0-9_-]{1,64}$
websocat ws://localhost:8000/ws/realm/demo
```

You should immediately see a `session.hello` frame, then a `heartbeat`
every 15 s. Closing the client removes it from the server registry
(structured log line `ws.session.close`).

---

## Caller expectations (what we promise)

- The v0.1 **superset keys** (`service`, `version`, `status`,
  `consensus_engine` on `/`; `status`, `checks`, `version`,
  `schema_version`, `uptime_s`, `timestamp` on `/health`;
  `messages`, `consensus_score`, `verified_facts` on `/consensus`)
  are **present on every successful response until the major bump.**
- New dependencies may be **added** to the readiness registry at any
  time — callers must iterate the `dependencies` / `checks` map by
  key, not by a closed enum.
- The `HEALTHCHECK` contract in the Dockerfile relies only on the
  HTTP status code of `GET /health`, not the body. That baseline will
  not change.

## How to verify this page is still accurate

From the repo root:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/dirijor-core/requirements-dev.txt
python -m pytest backend/dirijor-core/tests
```

Expected: all tests pass on Python 3.12+ with the pinned floors.
Tests cover:

- `test_root_shape`, `test_root_status_operational_when_ready`, `test_root_preserves_v01_superset`, `test_root_includes_realtime_block`
- `test_health_ok_when_ready`, `test_health_503_when_required_dep_degraded`, `test_health_never_500s_when_probe_raises`, `test_health_includes_realtime_channel_dep`
- `test_registry_contains_required_dependencies`
- `test_consensus_smoke`, `test_consensus_degraded_keeps_v01_key_set`
- `test_schema_version_pinned`, `test_schema_version_is_3` (fail loudly if someone bumps `SCHEMA_VERSION` without updating this page)
- Story 3.3 WebSocket suite: `test_ws_accepts_valid_realm_id`, `test_ws_rejects_missing_realm_id`, `test_ws_rejects_malformed_realm_id`, `test_ws_rejects_forbidden_realm`, `test_ws_broadcast_reaches_only_matching_realm`, `test_ws_heartbeat_emitted_on_idle`, `test_ws_disconnect_cleans_up_registry`, `test_ws_close_1011_on_send_failure`

If any test fails, **this reference is out of date** — file a docs PR
before merging the code PR that changed the contract.

## Related reading

- [Architecture — Overview](../architecture/overview.md) — where the supervisor sits in the full system.
- [ADR-0001 — LangGraph supervisor](../architecture/adr/0001-langgraph-supervisor.md) — why the supervisor looks like this.
- [ADR-0002 — Consensus threshold ≥95%](../architecture/adr/0002-consensus-threshold-95.md) — why `consensus_score` exists and what "no decision" means.
- [Tutorial — your first local Dirijor environment](../guides/tutorials/01-first-realm.md) — exercises every endpoint on this page.
- Implementation artifact: `_bmad-output/implementation-artifacts/3-1-supervisor-hardening-health-endpoints.md` (in the repo).
