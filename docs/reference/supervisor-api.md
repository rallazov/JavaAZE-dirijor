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
| `SCHEMA_VERSION` | `1` | Contract shape version. Bumps on breaking change only. |

## Endpoints at a glance

| Method | Path | Purpose | Status codes |
|---|---|---|---|
| `GET`  | `/`           | Service identity, aggregate status, per-dependency readiness | `200` |
| `GET`  | `/health`     | Liveness + readiness with ISO-8601 timestamp                 | `200` (ready) / `503` (degraded) |
| `POST` | `/consensus`  | v0.1 placeholder consensus call (real debate loop in Story 3.2) | `200` / `503` (if graph unavailable) |

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
  "schema_version": 1,
  "status": "operational",
  "consensus_engine": "ready",
  "uptime_s": 12.4,
  "dependencies": {
    "graph_compiled":    { "ready": true,  "required": true,  "detail": null },
    "consensus_engine":  { "ready": true,  "required": true,  "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "planned — see Story 4.1" },
    "mesh":              { "ready": false, "required": false, "detail": "planned — see Story 5.1" }
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
  "schema_version": 1,
  "uptime_s": 12.4,
  "timestamp": "2026-04-16T10:12:44.117Z",
  "checks": {
    "graph_compiled":    { "ready": true,  "required": true,  "detail": null },
    "consensus_engine":  { "ready": true,  "required": true,  "detail": null },
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
  "schema_version": 1,
  "uptime_s": 342.0,
  "timestamp": "2026-04-16T10:18:02.554Z",
  "checks": {
    "graph_compiled":    { "ready": false, "required": true,  "detail": "compile failed: <reason>" },
    "consensus_engine":  { "ready": false, "required": true,  "detail": "compile failed: <reason>" },
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
- No streaming. The real debate loop may stream per-round state over
  the Story 3.3 WebSocket channel.

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

Expected: **10 passed** on Python 3.12+ with the pinned floors.
Tests cover:

- `test_root_shape`, `test_root_status_operational_when_ready`, `test_root_preserves_v01_superset`
- `test_health_ok_when_ready`, `test_health_503_when_required_dep_degraded`, `test_health_never_500s_when_probe_raises`
- `test_registry_contains_required_dependencies`
- `test_consensus_smoke`, `test_consensus_degraded_keeps_v01_key_set`
- `test_schema_version_pinned` (fails loudly if someone bumps `SCHEMA_VERSION` without updating this page)

If any test fails, **this reference is out of date** — file a docs PR
before merging the code PR that changed the contract.

## Related reading

- [Architecture — Overview](../architecture/overview.md) — where the supervisor sits in the full system.
- [ADR-0001 — LangGraph supervisor](../architecture/adr/0001-langgraph-supervisor.md) — why the supervisor looks like this.
- [ADR-0002 — Consensus threshold ≥95%](../architecture/adr/0002-consensus-threshold-95.md) — why `consensus_score` exists and what "no decision" means.
- [Tutorial — your first local Dirijor environment](../guides/tutorials/01-first-realm.md) — exercises every endpoint on this page.
- Implementation artifact: `_bmad-output/implementation-artifacts/3-1-supervisor-hardening-health-endpoints.md` (in the repo).
