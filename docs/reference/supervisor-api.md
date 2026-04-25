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
| `SCHEMA_VERSION` | `10` | Contract shape version. **Story 9.1** bumped 9→10: additive `outputs.agent_droplet_ids` / `outputs.agent_private_ipv4s` (list[str]) on terraform-digitalocean ready jobs. **Story 7.2** bumped 8→9: `POST /marketplace/templates/import-draft` returns `{ schema_version, draft }` on success or `{ schema_version, code, detail }` on `422` (`PARSE` / `SCHEMA` / `SIGNATURE` / `PINS` / `draft_agent_count_exceeded` — **not** a `SpinError` envelope). Story 5.1 bumped 7→8: gated mesh bootstrap after `phase == ready` (`DIRIJOR_MESH_BOOTSTRAP_ENABLED` truthy like `DIRIJOR_AUDIT_EXPORT_ENABLED` / `DIRIJOR_SAFETY_SIGNALS_ENABLED`: `1` / `true` / `yes`); additive `outputs.mesh`, `outputs.headscale_control_url`; `POST /realms/{job_id}/mesh/preauth-key` (one-shot secret, not echoed on `GET` poll); `POST /realms/{job_id}/mesh/retry`; WebSocket `realm.mesh.state`; `SpinError` codes `mesh_bootstrap_disabled`, `mesh_preauth_consumed`, `mesh_preauth_not_eligible`, `mesh_headscale_api_error`, `mesh_retry_conflict`. Story 4.3 bumped 6→7: gated `POST /audit/export` (ZIP audit bundle); realm-scoped in-memory audit ring; new `SpinError` codes `audit_export_disabled`, `audit_export_too_large`, `audit_export_invalid_window`. Story 4.2 bumped 5→6: optional `realm_id` / `anomaly_subject_agent_id` on `POST /consensus`; `GET /safety/quarantine/{realm_id}`; gated `POST /safety/signal`; optional `anomaly_policy` readiness entry; WebSocket payloads remain existing `topology.delta` / `hitl.pending` types (additive agent fields such as `status: "quarantined"`). Story 4.1 bumped 4→5: semantic-cache HTTP + consensus cache fields + `semantic_cache` probe. Story 2.2 bumped 3→4 (`DELETE /realms/{job_id}` + destroy-related `outputs` keys + nine new `SpinError.code` values). Story 3.2 bumped 1→2 (debate loop), Story 3.3 bumped 2→3 (WebSocket channel + `realtime` block). Story 2.1 added the `realm_manager` readiness-registry dep without bumping — precedent for "dep-only additive" extensions. Story 2.3 added **`egress_policy_denied`** and Terraform egress controls **without** bumping `SCHEMA_VERSION` (env- and module-driven only). |

### Marketplace / template manifest (Story 7.1 library + Story 7.2 HTTP)

Swarm template manifests (`dirijor.template_manifest.v1`) are validated in-process by `verify_template_manifest` in `backend/dirijor-core/template_manifest.py`. **Story 7.2** adds **`POST /marketplace/templates/import-draft`** (body = raw UTF-8 JSON bytes of one manifest object) which calls that verifier and maps a successful document to operator-editable spin draft fields (`agent_count`, `realm_description`, optional `adapter_hint`, read-only `policy_refs`). Provisioning still uses **`POST /realms/spin`** only.

Authoritative detail, canonical JSON signing, error codes (`PARSE` / `SCHEMA` / `SIGNATURE` / `PINS`), and derived JSON Schema: [`template-manifest.md`](template-manifest.md).

## Endpoints at a glance

| Method | Path | Purpose | Status codes |
|---|---|---|---|
| `GET`  | `/`                           | Service identity, aggregate status, per-dependency readiness          | `200` |
| `GET`  | `/health`                     | Liveness + readiness with ISO-8601 timestamp                          | `200` (ready) / `503` (degraded) |
| `POST` | `/consensus`                  | Multi-agent debate loop (Story 3.2 — real, configurable threshold) + optional semantic cache (Story 4.1) | `200` / `503` (if graph unavailable) |
| `POST` | `/semantic-cache/ingest`      | Ingest a verified fact with caller-provided embedding (Story 4.1, Qdrant) | `200` / `400` / `503` |
| `POST` | `/semantic-cache/query`       | Similarity query within a `scope_id` (Story 4.1)                        | `200` / `400` / `503` |
| `POST` | `/marketplace/templates/import-draft` | Verify manifest + return realm spin draft (Story 7.2 — not `SpinError`) | `200` / `422` |
| `POST` | `/realms/spin`                | Enqueue a realm provisioning job (Story 2.1 — adapter-backed, async)  | `202` / `400` / `409` / `503` |
| `GET`  | `/realms/{job_id}`            | Poll spin job state (Story 2.1 — `validating → provisioning → ready \| failed`) | `200` / `404` |
| `POST` | `/realms/{job_id}/mesh/preauth-key` | Mint one Headscale preauth key per job (Story 5.1 — secret not stored on poll body) | `200` / `404` / `409` / `410` / `502` |
| `POST` | `/realms/{job_id}/mesh/retry` | Re-run mesh bootstrap after transient Headscale errors (Story 5.1) | `200` / `403` / `404` / `409` |
| `DELETE` | `/realms/{job_id}`          | Request realm destroy (Story 2.2 — adapter-scoped; poll `GET` for completion) | `202` / `204` / `404` / `409` / `500` |
| `GET`  | `/safety/quarantine/{realm_id}` | List quarantined agents for a realm (Story 4.2, shipped — in-process registry) | `200` / `400` (`SpinError`) |
| `POST` | `/safety/signal`              | Inject synthetic anomaly signal for tests/demos (Story 4.2, shipped — **off** unless `DIRIJOR_SAFETY_SIGNALS_ENABLED` is truthy) | `204` / `400` / `403` |
| `POST` | `/audit/export`               | Download ZIP audit bundle for a realm + UTC half-open window (Story 4.3 — **off** unless `DIRIJOR_AUDIT_EXPORT_ENABLED` is truthy) | `200` (`application/zip`) / `400` / `403` / `413` (`SpinError`) |
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
  "schema_version": 10,
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
    "mesh":              { "ready": true, "required": false, "detail": "mesh bootstrap disabled (set DIRIJOR_MESH_BOOTSTRAP_ENABLED=1 to opt in)" }
  },
  "realtime": {
    "connections": 0,
    "heartbeat_interval_s": 15.0,
    "schema_version": 10
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
| `realtime` | `RealtimeSummary` | Story 3.3 additive block. Canonical shape: `{ connections: int, heartbeat_interval_s: float, schema_version: int }` — see `RealtimeSummary` in `backend/dirijor-core/supervisor.py`. `connections` is the sum of open sessions across all realms (in-process only; best-effort across restarts). |

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
  "schema_version": 10,
  "uptime_s": 12.4,
  "timestamp": "2026-04-16T10:12:44.117Z",
  "checks": {
    "graph_compiled":    { "ready": true,  "required": true,  "detail": null },
    "consensus_engine":  { "ready": true,  "required": true,  "detail": null },
    "realtime_channel":  { "ready": true,  "required": true,  "detail": null },
    "realm_manager":     { "ready": true,  "required": true,  "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "not configured" },
    "anomaly_policy":    { "ready": true,  "required": false, "detail": null },
    "mesh":              { "ready": true, "required": false, "detail": "mesh bootstrap disabled (set DIRIJOR_MESH_BOOTSTRAP_ENABLED=1 to opt in)" }
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
  "schema_version": 10,
  "uptime_s": 342.0,
  "timestamp": "2026-04-16T10:18:02.554Z",
  "checks": {
    "graph_compiled":    { "ready": false, "required": true,  "detail": "compile failed: <reason>" },
    "consensus_engine":  { "ready": false, "required": true,  "detail": "compile failed: <reason>" },
    "realtime_channel":  { "ready": true,  "required": true,  "detail": null },
    "realm_manager":     { "ready": true,  "required": true,  "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "not configured" },
    "anomaly_policy":    { "ready": true,  "required": false, "detail": null },
    "mesh":              { "ready": true, "required": false, "detail": "mesh bootstrap disabled (set DIRIJOR_MESH_BOOTSTRAP_ENABLED=1 to opt in)" }
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

**Purpose.** Multi-agent debate loop (Story 3.2): configurable rounds,
quorum threshold, per-round votes, and explicit `termination_reason`, with
optional verified-fact augmentation when the semantic cache is configured
(Story 4.1). See [Concept — Consensus](../product/concepts/consensus.md)
and [ADR-0002](../architecture/adr/0002-consensus-threshold-95.md).

### Request

```
POST /consensus?query=<string>
```

(Query string param; v0.1 keeps the signature stable for the existing
callers — see AC 4 of Story 3.1.)

### Response — `200 OK`

SCHEMA **v2** superset on **200**: v0.1 keys (`messages`, `consensus_score`,
`verified_facts`) plus debate-loop fields (`decision`, `votes`,
`termination_reason`, `rounds`, `threshold`) and Story 4.1 semantic-cache
outcome fields (`semantic_cache_status`, `semantic_cache_reason`). Example
skeleton:

```json
{
  "messages":         [ /* LangGraph state messages */ ],
  "consensus_score":  0.97,
  "verified_facts":   [ /* VerifiedFact objects when cache hits */ ],
  "semantic_cache_status": "skipped",
  "semantic_cache_reason": "query_vector_missing",
  "decision": null,
  "votes": [],
  "termination_reason": "threshold_reached",
  "rounds": 1,
  "threshold": 0.95
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

### Story 4.1 — optional semantic cache fields

Optional JSON fields on `POST /consensus`:

| Field | Type | Default | Notes |
|---|---|---|---|
| `query_vector` | `list[float] \| null` | `null` | Caller-provided embedding; when absent, `verified_facts` stays `[]` and a `semantic_cache.miss` log line is emitted (`query_vector_missing`). |
| `semantic_scope_id` | `string` | `""` | **Required** (non-blank) whenever `query_vector` is present — realm / tenant isolation boundary; there is no default shared scope. |
| `semantic_cache_limit` | `int` | `5` | `1`–`20` hits max. |
| `semantic_cache_threshold` | `float \| null` | `null` | `0.0`–`1.0`; when `null`, the server uses `QDRANT_SCORE_THRESHOLD` (default `0.78`). |
| `realm_id` | `string \| null` | `null` | When set (same grammar as WebSocket `realm_id`), the supervisor evaluates the loaded anomaly policy after a successful 200 and may emit `topology.delta` / `hitl.pending` on quarantine (Story 4.2). |
| `anomaly_subject_agent_id` | `string \| null` | `null` | Canvas agent node id to tag when a consensus rule fires; when omitted, the first opinion’s `agent_id` is used, or `"consensus"` when there are no opinions. |

**HTTP 200 — semantic cache outcome (Story 4.1, additive on SCHEMA v2 body).**

| Field | Type | Meaning |
|---|---|---|
| `semantic_cache_status` | `"hit" \| "miss" \| "skipped" \| "unavailable" \| "disabled"` | Result of the **pre-consensus** cache lookup. |
| `semantic_cache_reason` | `string \| null` | Closed-set detail when not a hit (e.g. `query_vector_missing`, `no_hits`, `below_threshold`, `qdrant_timeout`, `qdrant_connection`, `qdrant_auth`, `qdrant_unavailable`); `null` on `hit`. |

### Current limitations (v0.1, intentional)

- `consensus_score` uses the **real** debate-loop score (Story 3.2); it is not a placeholder.
- `verified_facts` is populated from the verified semantic cache when
  `QDRANT_URL` is configured, vectors match `QDRANT_VECTOR_SIZE`, and
  hits meet the effective score threshold; otherwise `[]`. **`semantic_cache_*`
  fields** still report whether the lookup was skipped, missed, or failed.
- Structured `semantic_cache.miss` logs remain (`reason` in a closed set — Story 4.1 AC 4).
- No streaming on `/consensus` itself. Per-round state may be streamed
  over the `WS /ws/realm/{realm_id}` channel in a future story; the
  Story 3.3 channel only carries `topology.delta`, `metrics.update`, and
  `hitl.pending` today.
- **Realm-scoped auditing (Story 4.3):** `consensus.completed` audit rows are
  appended only when `realm_id` is present on the request and `POST /consensus`
  returns **200**. Consensus calls **without** `realm_id` do not appear in
  per-realm export bundles — auditors must not assume global consensus coverage
  from `POST /audit/export` alone.

---

## `POST /semantic-cache/ingest`

**Purpose.** Store one verified fact with a **caller-provided** dense vector
(no embedding model in Core — Story 4.1). Payload fields persisted in
Qdrant include `fact_id`, `scope_id`, `provenance_id`, `source_uri`,
`verified_by`, `text`, `metadata`, `ingested_at`. The Qdrant **vector point id**
is a deterministic UUID derived from `(scope_id, fact_id)` so two realms
cannot overwrite each other’s points when reusing the same logical `fact_id`.

**Configuration.** `QDRANT_URL` must be set; otherwise HTTP **503** with
`{"error":"semantic_cache_unavailable","message":"..."}`. Optional:
`QDRANT_API_KEY`, `QDRANT_COLLECTION` (default `dirijor_verified_facts`),
`QDRANT_VECTOR_SIZE` (default `384`), `QDRANT_SCORE_THRESHOLD` (default
`0.78`).

## `POST /semantic-cache/query`

**Purpose.** Nearest-neighbor retrieval within a single `scope_id`, sorted
by score descending. Response `hits` are `VerifiedFact` objects
(`fact_id`, `provenance_id`, `source_uri`, `snippet`, `score`,
`metadata`). Validation failures return **400**; transport errors
return **503** and emit `semantic_cache.miss` with `reason:
qdrant_unavailable` where applicable.

---

## Story 4.2 — anomaly policy & quarantine *(shipped)*

**Configuration.**

- `DIRIJOR_ANOMALY_POLICY_PATH` — optional path to a **JSON** policy document
  (`AnomalyPolicyDocument`: `{ "rules": [ ... ] }`). Empty / unset → in-process
  **empty ruleset** (local dev needs no file). When the path is set but the
  file is missing, invalid JSON, or fails Pydantic validation, the
  `anomaly_policy` readiness probe reports `ready: false` with a short
  `detail` string; **required remains false** so the rest of the supervisor
  stays operational.
- `DIRIJOR_SAFETY_SIGNALS_ENABLED` — when truthy (`1`, `true`, `yes`),
  enables `POST /safety/signal`. Default is **off** so hardened deployments
  do not expose synthetic inject by mistake.

**Rule matchers (v0).** Each rule has `id`, optional `description`, `action:
"quarantine"`, and `when` (discriminated by `type`):

- `consensus_score_below` — `{ "type": "consensus_score_below", "threshold": <float> }`
- `consensus_termination_in` — `{ "type": "consensus_termination_in", "reasons": ["...", ...] }`
- `signal_type_eq` — `{ "type": "signal_type_eq", "signal_type": "..." }` (for `/safety/signal`)
- `tool_name_regex` — `{ "type": "tool_name_regex", "pattern": "..." }` (Python `re.search`; evaluated against `tool_name` from the signal)

**`GET /safety/quarantine/{realm_id}`** — `200` body
`{ "items": [ { "realm_id", "agent_id", "rule_id", "quarantined_at", "evidence" } ... ], "schema_version": <int> }`.
Malformed `realm_id` → **400** with `SpinError` (`invalid_realm_id`), same grammar as the WebSocket realm id.

**`POST /safety/signal`** — JSON body
`{ "realm_id", "agent_id", "signal_type", "tool_name"?: string, "evidence"?: object }`.
**204** on success when enabled; **403** when signals are disabled.

**WebSocket (additive).** Quarantine uses existing event types only:
when policy isolates an agent, `topology.delta` carries `agents[]` entries with `status: "quarantined"`
plus `label` / `signaturePreview` / `safetyScore` hints; `hitl.pending` carries
a `CriticalAction`-compatible `action` object (stable `id`, `title`, `detail`,
`requestedAt`, `safetyScore`).

**Dedup.** Repeated triggers for the same `(realm_id, agent_id, rule_id)` within
~30s merge evidence in the registry but **skip** additional WS fan-out
(idempotent operator UX).

**Registry caveat.** Quarantine state is in-memory per process (same as
`_SPIN_JOBS`); multi-worker deployments see partitioned state until a shared
store lands.

---

## Story 4.3 — immutable audit export package *(shipped)*

**Purpose (NFR3).** Operators download a single **ZIP** file (no extra tooling
beyond unzip) that auditors can integrity-check offline. v0 is **HTTP-only**
(no WebSocket progress).

**Access control (v0).** There is **no** API key or mTLS in this story. Export
is **disabled by default**: set **`DIRIJOR_AUDIT_EXPORT_ENABLED`** to a truthy
value using the **same** convention as **`DIRIJOR_SAFETY_SIGNALS_ENABLED`**
(`1`, `true`, `yes`). When disabled, **`POST /audit/export`** returns **403**
with `SpinError` `code: "audit_export_disabled"` and a `message` naming the
env var. **Assume a private bind / network posture** until a future story adds
authentication.

**Half-open UTC window.** Request JSON:

```json
{
  "realm_id": "demo-realm",
  "window_start": "2026-04-19T00:00:00Z",
  "window_end": "2026-04-20T00:00:00Z"
}
```

Both instants **must** be ISO-8601 **UTC** with a **`Z`** suffix (same rule in
OpenAPI validation and tests). Events are included iff **`window_start <= t <
window_end`** (end is **exclusive**). `manifest.json` carries
`"window_semantics": "half_open_utc"` so bundles are self-describing.

**Response — `200`:** `Content-Type: application/zip` and
`Content-Disposition: attachment; filename="dirijor-audit-<realm>-<export_id>.zip"`.

**Archive layout (minimum):**

| Member | Role |
|---|---|
| `manifest.json` | `export_id` (UUID), `realm_id`, window bounds, `created_at`, `supervisor_version`, `schema_version`, `manifest_schema` (`dirijor.audit_export.v1`), `files[]` with `path`, `sha256`, `bytes` for every other member, `tamper_evidence` (explicit stub: `algorithm: "none"` + human `note` — digests are integrity-only, not authenticity). |
| `events.jsonl` | Zero or more lines; each line is one JSON audit row (`type` is `consensus.completed` or `safety.quarantine`). Sorted by `ts` ascending then `event_id`. |
| `quarantine_snapshot.json` | `{ "items": [ ... ] }` using the same row shape as `GET /safety/quarantine/{realm_id}` (`realm_id`, `agent_id`, `rule_id`, `quarantined_at`, `evidence`) — **current** registry at export time (may be `[]`). |

**Ring buffer.** Events are stored in a **per-realm in-memory** ring (default
cap **`DIRIJOR_AUDIT_RING_MAX=5000`**). Overflow **drops the oldest** event and
emits a structured log (`event="audit.ring_evicted"`). **State is lost on
restart** — exports are best-effort compliance aids, not a durable SOX system
until a shared store exists (same multi-worker caveat as quarantine / spin
jobs).

**Event types (v0).**

- `consensus.completed` — non-secret summary: `decision`, `consensus_score`,
  `termination_reason`, `rounds`, `threshold`, vote/message **counts** only
  (no full `messages` / vote bodies).
- `safety.quarantine` — **at most one** row per logical key
  `(realm_id, agent_id, rule_id)`; idempotent registry updates do **not**
  append duplicate rows.

**Limits & errors.**

- **`DIRIJOR_AUDIT_EXPORT_MAX_WINDOW_HOURS`** (default **168**) — max span of
  `[window_start, window_end)`; wider windows → **400**
  `audit_export_invalid_window`.
- **`DIRIJOR_AUDIT_EXPORT_MAX_UNCOMPRESSED_BYTES`** (default **20971520**) —
  estimated uncompressed payload (member JSON before ZIP) over the limit →
  **413** `audit_export_too_large`.
- Malformed `realm_id` / bad timestamps / inverted window → **400**
  `audit_export_invalid_window` (`SpinError`).

**Example download:**

```bash
export DIRIJOR_AUDIT_EXPORT_ENABLED=1
curl -sS -X POST http://127.0.0.1:8000/audit/export \
  -H 'Content-Type: application/json' \
  -d '{"realm_id":"demo-a","window_start":"2026-04-19T00:00:00Z","window_end":"2026-04-20T00:00:00Z"}' \
  -o audit-bundle.zip
unzip -l audit-bundle.zip
# Recompute e.g. sha256 of events.jsonl and compare to manifest.json → files[]
```

**Manifest fragment (`files` + `tamper_evidence`):**

```json
"files": [
  {
    "path": "events.jsonl",
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "bytes": 0
  },
  {
    "path": "quarantine_snapshot.json",
    "sha256": "8f4343466480886c1130e4b4ef32e3f8f4d0e8c8b8c8b8c8b8c8b8c8b8c8b8c8",
    "bytes": 14
  }
],
"tamper_evidence": {
  "algorithm": "none",
  "note": "No cryptographic signature is attached to this bundle. SHA-256 entries in `files` are content digests for integrity checking only, not authenticity. Use network posture (private bind) until a future story adds signing."
}
```

---

## `POST /marketplace/templates/import-draft`

**Purpose.** Upload a single `dirijor.template_manifest.v1` document as **raw UTF-8 JSON** (same bytes as `verify_template_manifest` in Core — duplicate object keys are rejected). On success, returns a **realm draft** for the operator to edit before calling `POST /realms/spin`. Shipped by **Story 7.2** (2026-04-20).

**Environment (optional pin binding).** If manifests set `pins.adapter_hint`, verification requires `DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT` to match (see Story 7.1 pins). HMAC verification uses `DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY` when signatures are not `algorithm: "none"`.

### Request

- **Content-Type:** `application/json`
- **Body:** one JSON object (the manifest file contents — not double-wrapped).

### Response `200 OK`

```json
{
  "schema_version": 10,
  "draft": {
    "agent_count": 3,
    "realm_description": "Imported template: my-tpl @ 1.0.0",
    "adapter_hint": "terraform-digitalocean",
    "policy_refs": [
      {
        "kind": "egress_policy",
        "uri": "https://registry.example.invalid/policies/egress/default-deny-v1",
        "version": "1.0.0"
      }
    ]
  }
}
```

`policy_refs` are **read-only** visibility for operators; Story 7.2 does not apply them to Terraform.

### Response `422 Unprocessable Entity`

Same envelope for verification failures and draft rules:

```json
{
  "schema_version": 10,
  "code": "SCHEMA",
  "detail": "…"
}
```

- `code` ∈ `PARSE` \| `SCHEMA` \| `SIGNATURE` \| `PINS` (from `verify_template_manifest`), or **`draft_agent_count_exceeded`** when the manifest lists more than **50** agents (after verification succeeds).

### Example (`curl`)

```bash
curl -sS -X POST http://127.0.0.1:8000/marketplace/templates/import-draft \
  -H 'Content-Type: application/json' \
  --data-binary @manifest.json
```

---

## `POST /realms/spin`

**Purpose.** Enqueue a realm provisioning job. Shipped by **Story 2.1**
(done 2026-04-18). v0.1 ships one adapter (`local-noop`) that simulates
provisioning in-process; Story 2.2 registers `TerraformAdapter`, Story
2.3 wraps `.provision` with default-deny egress; Story 5.1 (optional) runs
Headscale enrollment **after** `phase == "ready"` when
`DIRIJOR_MESH_BOOTSTRAP_ENABLED` is truthy, adding `outputs.mesh` and
`outputs.headscale_control_url` while **preserving** legacy `mesh_endpoint`
(`tf://…` / `noop://…`). The HTTP contract is
designed to stay stable across those future stories — consumers bind to
this page, not to adapter implementations.

### Request

```
POST /realms/spin
Content-Type: application/json
```

```json
{
  "realm_description": "finance-swarm prod",
  "adapter_hint":      "local-noop",
  "realm_id":          "demo-a",
  "agent_count":       3
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `realm_description` | `string` (1–2000 chars) | yes | Free-form operator intent. |
| `adapter_hint`      | `string \| null`        | no  | Name of a registered adapter. Defaults to `"local-noop"`. Unknown names → `400 adapter_unknown`. |
| `realm_id`          | `string \| null`        | no  | Matches `^[a-zA-Z0-9_-]{1,64}$`. Server-minted as `"realm-<short-uuid>"` when absent. |
| `agent_count`       | `int` (1–50)            | no  | Defaults to `3`. |

The `SpinRequest` Pydantic model uses `ConfigDict(extra="forbid")` —
unknown keys → `400 validation_failed`.

### Response — `202 Accepted`

Pydantic model: `SpinResponse`.

```json
{
  "job_id":          "5f1c0b2e-3d4a-4f5b-8c7d-9e0a1b2c3d4e",
  "realm_id":        "realm-5f1c0b2e",
  "phase":           "validating",
  "adapter":         "local-noop",
  "created_at":      "2026-04-18T10:12:44.117Z",
  "status_url":      "/realms/5f1c0b2e-3d4a-4f5b-8c7d-9e0a1b2c3d4e",
  "schema_version":  4
}
```

The initial `phase` on a 202 is **always** `"validating"`. Subsequent
state (`provisioning`, `ready`, `failed`) is observed by polling
`GET /realms/{job_id}`.

### Error envelope — `SpinError`

Every non-2xx response on `/realms/*` uses this shape. The server emits
via `JSONResponse(status_code=..., content=SpinError(...).model_dump())`
— NOT `HTTPException`, which would wrap the body in `{"detail": ...}`.

```json
{
  "code":    "<stable_snake_case_enum>",
  "message": "<human-readable>",
  "details": { /* code-specific */ }
}
```

The `code` field is a **closed** v0.1 enum. Adding a new code is an
additive change and requires updating this page in the same PR.

| Code | HTTP | When |
|---|---|---|
| `validation_failed`          | `400` | Missing required field, empty `realm_description`, oversized (>2000 chars), `agent_count` out of `[1, 50]`. |
| `invalid_realm_id`           | `400` | `realm_id` supplied but fails `^[a-zA-Z0-9_-]{1,64}$`. |
| `adapter_unknown`            | `400` | `adapter_hint` not registered. `details.supported_adapters` lists the registered names. |
| `realm_id_conflict`          | `409` | `realm_id` has an active (non-terminal) spin job. `details.existing_job_id` identifies it. |
| `realm_manager_unavailable`  | `503` | Readiness registry reports `realm_manager.ready == false`. |
| `job_not_found`              | `404` | `GET /realms/{job_id}` with an unknown id. |
| `adapter_error`              | _on job surface_ | Adapter raised; surfaces as terminal `phase: "failed"` + populated `error` on `GET /realms/{job_id}`. `details.exc_type` names the exception class; `details.traceback_preview` carries the last 500 chars of the traceback. |
| `internal`                   | _on job surface_ | Defensive catch-all at the top of `_run_spin_job`. Same surface as `adapter_error`. |
| `terraform_init_failed`      | _on job surface_ | `terraform init` non-zero; `details.step`, `details.exit_code`, `details.stderr_preview` (scrubbed). |
| `terraform_validate_failed`  | _on job surface_ | `terraform validate` non-zero. |
| `terraform_plan_failed`      | _on job surface_ | `terraform plan` non-zero. |
| `terraform_apply_failed`     | _on job surface_ | `terraform apply` non-zero or malformed `terraform output -json` after apply; may include `details.partial_apply`. `details.reason` is `terraform_output_malformed` (bad JSON / missing `realm_vpc_id` / missing or unusable `agent_droplet_ids` / `agent_private_ipv4s` — see `details.missing_field`) or `terraform_output_failed` (non-zero `terraform output` exit after successful apply). |
| `terraform_destroy_failed`   | _on job surface_ / nested in `outputs.destroy_error` | `terraform destroy` non-zero on the DELETE path. |
| `terraform_command_timeout`  | _on job surface_ | Subprocess exceeded `DIRIJOR_TERRAFORM_CMD_TIMEOUT_S`. |
| `adapter_credentials_missing`| _on job surface_ | `DIGITALOCEAN_TOKEN` or **`DIRIJOR_DO_SSH_PUBLIC_KEY`** missing / empty at `terraform-digitalocean` `validate` time (`SpinError.message` names which). |
| `egress_policy_denied`       | _on job surface_ | Pre-provision egress policy hook denied the spin (`validate` / `provision` only — not `destroy`). `details.reason` (e.g. `policy_hook`), `details.policy_id` (e.g. `egress-default-v0`), `details.adapter`. **`DIRIJOR_EGRESS_POLICY_DENY`** is recognized only when the value trims to exactly **`1`** (unlike **`DIRIJOR_ALLOW_PUBLIC_EGRESS`**, which treats `1` / `true` / `yes` / `on` as truthy). |
| `destroy_invalid_state`      | `409` | `DELETE` when `phase != "ready"`. `details.current_phase`. |
| `destroy_already_requested`  | `409` | Second `DELETE` while destroy is in flight. `details.destroy_requested_at`. |
| `audit_export_disabled`      | `403` | `POST /audit/export` when `DIRIJOR_AUDIT_EXPORT_ENABLED` is not truthy. `details.env` names the variable. |
| `audit_export_too_large`     | `413` | Estimated uncompressed export exceeds `DIRIJOR_AUDIT_EXPORT_MAX_UNCOMPRESSED_BYTES`. `details.limit_bytes`, `details.estimated_bytes`. |
| `audit_export_invalid_window`| `400` | Bad UTC `Z` timestamps, inverted window, span over `DIRIJOR_AUDIT_EXPORT_MAX_WINDOW_HOURS`, or Pydantic validation on the export body. |
| `mesh_bootstrap_disabled`    | `403` | `POST /realms/{job_id}/mesh/retry` when `DIRIJOR_MESH_BOOTSTRAP_ENABLED` is not truthy. |
| `mesh_preauth_consumed`     | `410` | Second `POST /realms/{job_id}/mesh/preauth-key` for the same job (secret is one-shot; poll never echoes the key). |
| `mesh_preauth_not_eligible`  | `409` | Preauth when `phase != "ready"`, `outputs.mesh.status != "ready"`, or Headscale user metadata is missing. |
| `mesh_headscale_api_error`   | `502` | Upstream Headscale HTTP failure on preauth mint (or credentials missing on supervisor for that route). |
| `mesh_retry_conflict`        | `409` | `POST .../mesh/retry` when `phase != "ready"` or destroy is active. |

**`outputs.mesh` job-attached codes (not HTTP `SpinError` bodies):** when
`DIRIJOR_MESH_BOOTSTRAP_ENABLED` is truthy, `GET /realms/{job_id}` may include
`outputs.mesh.code` for failures while `phase` remains `ready`:

| Code | Meaning |
|------|---------|
| `mesh_headscale_config_missing` | Gate on without both `DIRIJOR_HEADSCALE_API_URL` and `DIRIJOR_HEADSCALE_API_KEY`. |
| `mesh_headscale_api_error` | Headscale HTTP/API failure during bootstrap (may include `http_status`). |
| `mesh_bootstrap_internal` | Unexpected supervisor-side exception during bootstrap (see server logs). |

Successful bootstrap uses `outputs.mesh.status: "ready"` without a failure `code`.

### Adapter: `terraform-digitalocean`

When registered at process start (requires non-empty **`DIGITALOCEAN_TOKEN`**
and a terraform binary on **`PATH`** or at **`DIRIJOR_TERRAFORM_BINARY`**),
`adapter_hint: "terraform-digitalocean"` runs `terraform init → validate →
plan → apply` in a per-realm workspace under **`DIRIJOR_TERRAFORM_WORKSPACE_ROOT`**
(default: `<temp>/dirijor/terraform-workspaces/<realm_id>/`). **Story 9.1**
also requires **`DIRIJOR_DO_SSH_PUBLIC_KEY`** (operator OpenSSH public key) at
`validate` / `provision`; it is written to `terraform.tfvars.json` as
`ssh_public_key` (**not** via `TF_VAR_*`). The adapter is wrapped by
**`EgressPolicyRealmAdapter`** (Story 2.3) so a composable policy hook runs
before `validate` / `provision`. Ready `outputs` include `realm_vpc_id`,
`realm_vpc_ip_range`, `mesh_endpoint` (`tf://<vpc_id>` **placeholder preserved**
for backward compatibility; Story 5.1 adds `headscale_control_url` + `mesh`
when bootstrap is enabled), **`agent_droplet_ids`**, **`agent_private_ipv4s`**
(Story 9.1 — DO droplet ids and private VPC IPv4s, length `agent_count`),
`tf_workspace`, `tf_plan_digest`.

| SpinJob `outputs` key (terraform-digitalocean) | Type | Notes |
|---|---|---|
| `agent_droplet_ids` | `list[str]` | DigitalOcean droplet resource ids, `count.index` order. Absent for `local-noop`. |
| `agent_private_ipv4s` | `list[str]` | Private IPv4s on the realm VPC. Absent for `local-noop`. |

**Egress posture (Story 2.3):** the copied `terraform/modules/private-realm`
module applies a DigitalOcean Cloud Firewall with **default-deny outbound to
the public Internet** unless **`DIRIJOR_ALLOW_PUBLIC_EGRESS`** is set to a truthy
value (`1`, `true`, `yes`, `on`) on the supervisor process — passed as
`allow_public_egress` in `terraform.tfvars.json`. Rules apply to resources that
carry the `dirijor-realm-<realm_id>` tag (see ADR-0004). Reserved
**`DIRIJOR_EGRESS_POLICY_DENY=1`** (exact `1` after trim — not a general truthy
check) forces a terminal `failed` with `code: egress_policy_denied` (tests / drills).

See [ADR-0004](../architecture/adr/0004-default-deny-egress-terraform.md).

Worked examples:

```json
// 400 validation_failed
{ "code": "validation_failed", "message": "realm_description must be between 1 and 2000 chars", "details": { "field": "realm_description" } }

// 400 adapter_unknown
{ "code": "adapter_unknown", "message": "adapter 'aws' is not registered", "details": { "supported_adapters": ["local-noop"] } }

// 409 realm_id_conflict
{ "code": "realm_id_conflict", "message": "realm_id 'demo-a' already has an active spin job", "details": { "existing_job_id": "c7d8e9f0-..." } }

// 503 realm_manager_unavailable
{ "code": "realm_manager_unavailable", "message": "realm manager has no adapters registered", "details": {} }
```

### Lifecycle — phase semantics

| Phase | Terminal? | Description |
|---|---|---|
| `validating`   | no  | Initial phase on 202. Adapter `validate()` runs; on `SpinValidationError` transitions to `failed`. |
| `provisioning` | no  | Adapter `provision()` running. On any exception transitions to `failed`. |
| `ready`        | yes | Adapter returned successfully. `outputs` is populated; `error` is `null`. |
| `failed`       | yes | Validation failure, adapter exception, or internal crash. `outputs` is `{}`; `error` is populated. |

Terminal phases are **immutable** — `_update_job` asserts the current
phase is non-terminal before mutating, so a late poll never flips a
`ready` job back to `provisioning`.

---

## `GET /realms/{job_id}`

**Purpose.** Fetch full job state for a spin job enqueued by
`POST /realms/spin`. Safe to call at any cadence; the canvas client
(`frontend/hooks/useRealmSpin.ts`) polls every 750 ms with a 60 s
wall-time cap.

### Response — `200 OK`

Pydantic model: `SpinJob`.

```json
{
  "job_id":            "5f1c0b2e-...",
  "realm_id":          "realm-5f1c0b2e",
  "phase":             "ready",
  "adapter":           "local-noop",
  "created_at":        "2026-04-18T10:12:44.117Z",
  "updated_at":        "2026-04-18T10:12:44.627Z",
  "realm_description": "finance-swarm prod",
  "agent_count":       3,
  "outputs": {
    "mesh_endpoint": "noop://realm-5f1c0b2e",
    "adapter":       "local-noop",
    "agent_count":   3
  },
  "error":          null,
  "schema_version": 10
}
```

Field semantics:

- `updated_at` advances **monotonically** on every phase transition.
- `outputs` is populated **only** when `phase == "ready"`; it is `{}`
  for non-terminal phases.
- `error` is `null` on any non-`failed` phase; populated on `failed`
  (same `SpinError` shape as the error envelope above).

### Response — `404 Not Found`

Unknown `job_id`:

```json
{
  "code":    "job_not_found",
  "message": "no spin job with id 'xxx' is registered",
  "details": { "job_id": "xxx" }
}
```

### Readiness & operator visibility

- `dependencies.realm_manager` / `checks.realm_manager` — probe is
  `ready: true` iff at least one adapter is registered in the
  `_ADAPTERS` dict. `required: true` — the supervisor goes `degraded`
  (HTTP 503 on `/health`) if no adapters are registered.
- `_SPIN_JOBS: dict[str, SpinJob]` is **in-process**. Multi-replica
  deployment requires a shared backend (Redis / Postgres); documented
  follow-up, same caveat as `_CONNECTIONS` in the realtime block.
- Two structured log lines per job: `realm.spin.accept` on POST,
  `realm.spin.done` on terminal phase (includes `phase`, `duration_s`,
  `error_code`).

### Worked example — spin + poll with `curl`

```bash
# 1. Enqueue the job
JOB=$(curl -s -X POST http://localhost:8000/realms/spin \
  -H 'Content-Type: application/json' \
  -d '{"realm_description":"smoke test","agent_count":3}' | jq -r .job_id)

# 2. Poll until terminal (tight loop — production clients use 750 ms)
for i in $(seq 1 20); do
  curl -s http://localhost:8000/realms/$JOB | jq '{phase, updated_at, outputs, error}'
  sleep 0.2
done
```

---

## `POST /realms/{job_id}/mesh/preauth-key`

**Purpose.** Mint a **single-use** Headscale pre-authentication key for nodes
joining the realm tailnet. The full key string is returned **only** in this
response — `GET /realms/{job_id}` never echoes it (avoids log leakage on poll).

**Environment (server-side only):** `DIRIJOR_HEADSCALE_API_URL` (must include
`/api/v1` path prefix), `DIRIJOR_HEADSCALE_API_KEY` (Bearer token). Optional
`DIRIJOR_HEADSCALE_PUBLIC_URL` — HTTPS origin shown to operators as
`outputs.headscale_control_url` (defaults to API URL with `/api/v1` stripped).

| Code | When |
|---|---|
| `200` | JSON `preauth_key`, `expires_at`, `schema_version`. |
| `404` | Unknown `job_id`. |
| `409` | Mesh not ready, wrong phase, or destroy in progress. |
| `410` | Key already issued for this job. |
| `502` | Headscale API error or missing credentials on supervisor. |

**Minimum Headscale version exercised in development:** **0.23.x** API shapes
(REST `/api/v1/user`, `/api/v1/preauthkey`). Pin your server to match.

---

## `POST /realms/{job_id}/mesh/retry`

**Purpose.** Re-run bootstrap after transient Headscale failures. Idempotent
user creation (`GET /user?name=` then `POST /user` as needed). Requires the
same **`DIRIJOR_MESH_BOOTSTRAP_ENABLED`** gate as automatic bootstrap.

| Code | When |
|---|---|
| `200` | `{ "status": "accepted", "schema_version": 10 }` — poll `GET` for updated `outputs.mesh`. |
| `403` | Mesh feature gate off. |
| `404` | Unknown job. |
| `409` | Not `phase == ready` or destroy active. |

**Destroy ordering:** if `DELETE /realms/{job_id}` sets `destroy_requested_at`
while bootstrap runs, in-flight automation stops applying Headscale writes;
destroy semantics win (see `_run_mesh_bootstrap_after_ready`).

---

## `DELETE /realms/{job_id}`

**Purpose.** Request asynchronous teardown of a **ready** realm job (Story
2.2). Destroy lifecycle state lives in `SpinJob.outputs` (`destroy_requested_at`,
`destroyed`, `destroyed_at`, `destroy_error`) — `phase` stays `ready` until
future stories change the contract.

### Responses

| Code | Body |
|---|---|
| `202` | Current `SpinJob` with `outputs.destroy_requested_at` set. |
| `204` | Empty — job already destroyed (idempotent retry). |
| `404` | `job_not_found` |
| `409` | `destroy_invalid_state` or `destroy_already_requested` |
| `500` | `internal` — defensive: stored `job.adapter` not present in the in-process registry (should not occur in normal operation). |

```bash
curl -s -X DELETE http://localhost:8000/realms/$JOB
```

Poll `GET /realms/{job_id}` until `outputs.destroyed == true` or
`outputs.destroy_error` is populated.

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
| `4403`     | `realm_forbidden`             | no     | `_authorize_realm(realm_id)` returns false. v0.1 allow-all stub — real auth lands with Story 5.1 (mesh / scoped token). |
| `1011`     | `heartbeat_send_failed`       | yes    | Server could not emit a heartbeat (transport unhealthy). Session is evicted from the registry. |
| `1000`     | clean close                   | yes    | Client closed intentionally; reconnect if the canvas is still mounted. |

On a successful handshake the first frame the server sends is
`session.hello`, carrying a `connection_id` the server generated for this
session.

### Envelope

Every **server → client** frame uses the same six top-level keys (see
`RealtimeEnvelope` in `supervisor.py`). The Pydantic model uses
`ConfigDict(extra="forbid")` — a seventh top-level key is a contract
violation. Payload evolution is **per `type`** inside `payload` and is
governed by `SCHEMA_VERSION` + docs on this page.

Inbound client frames are read as text and discarded in v0.1 (canvas →
Core remains HTTP POST).

```json
{
  "type": "topology.delta",
  "schema_version": 10,
  "realm_id": "demo",
  "ts": "2026-04-16T10:12:44.117Z",
  "seq": 3,
  "payload": { }
}
```

| Field | Type | Notes |
|---|---|---|
| `type` | `string` | One of `session.hello`, `topology.delta`, `metrics.update`, `hitl.pending`, `realm.mesh.state`, `heartbeat`, `session.bye`. |
| `schema_version` | `int` | Must equal HTTP `SCHEMA_VERSION` at send time. |
| `realm_id` | `string` | Echo of the path-param realm. |
| `ts` | ISO-8601 UTC (`Z` suffix) | Server clock. |
| `seq` | `int` | Monotonic per WebSocket session, starting at `0` on `session.hello`. Increments only after a successful `send_json`. |
| `payload` | `object` | Type-specific body. See below. |

### Event types

- `session.hello` — first frame (`seq == 0`). Payload includes `service_version`, `schema_version`, `supported_event_types`, `heartbeat_interval_s`, and `connection_id` (UUID for this TCP session).
- `heartbeat` — emitted every `HEARTBEAT_INTERVAL_S` (default **15 s**). Empty payload.
- `topology.delta` — `payload.agents?: AgentPatch[]`, `payload.edges?: EdgePatch[]`. Each patch carries an `id`; `_tombstone: true` means "remove this id". All other keys are a shallow upsert. Story 4.2 sets agent `status` to `"quarantined"` (and related hints) when policy isolates an agent.
- `metrics.update` — `payload` is a partial of the canvas `RealmMetrics` shape. Shallow-merged into the store.
- `hitl.pending` — `payload.action` is a full `CriticalAction`; dedup by `action.id`.
- `realm.mesh.state` — `payload.job_id`, `payload.status`, `payload.correlation_id`, optional `code` / `message` on failure (Story 5.1). Authoritative enrollment fields remain on `GET /realms/{job_id}.outputs.mesh`.
- `session.bye` — reserved for a future **server-initiated** graceful shutdown (operator drain, deploy, etc.). v0.1 does not emit it; sessions end with client close or server `1011` / process teardown.

### Reconnect policy (client-side contract)

The canvas client (`frontend/lib/dirijor-realtime.ts`) implements:

- Exponential backoff with jitter. Base 500 ms, doubled each attempt, capped at **30 000 ms**, ±10 % jitter.
- `MAX_RECONNECT_ATTEMPTS = 8`. After that the client stays in `error`.
- Close codes `4401` / `4403` are **client-fault** and do **not** retry. Everything else (including `1006`, `1011`, and clean `1000`) retries.

### Readiness & operator visibility

- `dependencies.realtime_channel` / `checks.realtime_channel` — required
  (`required: true`); probe reflects that the WebSocket route is
  registered (v0.1 does not fail readiness when zero clients are
  connected).
- `GET /` → `realtime.connections` counts open sessions via
  `_CONNECTIONS: dict[str, set[_WsSession]]` (in-process; not replicated
  across workers).

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
- `test_schema_version_pinned`, `test_schema_version_is_10` (fail loudly if someone bumps `SCHEMA_VERSION` without updating this page)
- Story 5.1 mesh: `test_mesh_bootstrap.py` (gate off/on, Headscale `MockTransport`, preauth one-shot, retry, WS broadcast)
- Story 4.2 safety suite: `test_safety_quarantine.py` (policy load, consensus + signal hooks, HTTP list, realm isolation, `broadcast_event` unknown-type regression)
- Story 4.3 audit export: `test_audit_export.py` (export gate, half-open filtering, 413 oversize, manifest digests, quarantine audit idempotency, ring eviction log)
- Story 3.3 WebSocket suite: `test_ws_accepts_valid_realm_id`, `test_ws_rejects_missing_realm_id`, `test_ws_rejects_malformed_realm_id`, `test_ws_rejects_forbidden_realm`, `test_ws_broadcast_reaches_only_matching_realm`, `test_ws_heartbeat_emitted_on_idle`, `test_ws_disconnect_cleans_up_registry`, `test_ws_close_1011_on_send_failure`
- Story 2.1 realm-spin suite: `test_spin_accepts_valid_request_returns_202`, `test_spin_echoes_caller_provided_realm_id`, `test_spin_generates_realm_id_when_absent`, `test_spin_rejects_empty_description`, `test_spin_rejects_oversized_description`, `test_spin_rejects_invalid_realm_id`, `test_spin_rejects_unknown_adapter`, `test_spin_rejects_conflict_on_active_realm`, `test_spin_job_progresses_through_lifecycle`, `test_spin_failure_surfaces_structured_error`, `test_get_realm_job_404_on_unknown_id`, `test_health_includes_realm_manager_dep`
- Story 2.2 terraform + destroy suite (20 cases): `test_terraform_adapter_registered_when_token_and_binary_present`, `test_terraform_adapter_skipped_when_token_absent`, `test_terraform_adapter_skipped_when_binary_missing`, `test_spin_terraform_adapter_accepts_and_returns_202`, `test_spin_terraform_lifecycle_progresses_to_ready`, `test_spin_terraform_invokes_commands_in_order`, `test_spin_terraform_init_failure_surfaces_terraform_init_failed`, `test_spin_terraform_validate_failure_surfaces_terraform_validate_failed`, `test_spin_terraform_plan_failure_surfaces_terraform_plan_failed`, `test_spin_terraform_apply_failure_surfaces_terraform_apply_failed`, `test_spin_terraform_apply_failure_scrubs_do_pat_tokens`, `test_spin_terraform_command_timeout_surfaces_terraform_command_timeout`, `test_spin_terraform_credentials_missing_at_validate_time_surfaces_adapter_credentials_missing`, `test_destroy_on_ready_job_returns_202_and_runs_terraform_destroy`, `test_destroy_on_non_ready_job_returns_409_destroy_invalid_state`, `test_destroy_idempotent_on_already_destroyed_returns_204`, `test_delete_realm_job_404_on_unknown_id`, `test_schema_version_is_4`, `test_scrub_secrets_masks_all_documented_patterns`, `test_local_noop_destroy_is_idempotent_noop`
- Story 2.3 default-deny egress: `test_terraform_write_tfvars_allow_public_egress_default_false`, `test_terraform_write_tfvars_allow_public_egress_from_env`, `test_spin_validation_error_accepts_egress_policy_denied`, `test_spin_egress_policy_denied_when_env_set`, `test_egress_policy_deny_env_does_not_affect_local_noop`, `test_private_realm_main_tf_firewall_realm_egress_default_deny_structure`, `test_private_realm_variables_allow_public_egress_defaults_false`

If any test fails, **this reference is out of date** — file a docs PR
before merging the code PR that changed the contract.

## Related reading

- [Architecture — Overview](../architecture/overview.md) — where the supervisor sits in the full system.
- [ADR-0001 — LangGraph supervisor](../architecture/adr/0001-langgraph-supervisor.md) — why the supervisor looks like this.
- [ADR-0002 — Consensus threshold ≥95%](../architecture/adr/0002-consensus-threshold-95.md) — why `consensus_score` exists and what "no decision" means.
- [Tutorial — your first local Dirijor environment](../guides/tutorials/01-first-realm.md) — exercises every endpoint on this page.
- Implementation artifact: `_bmad-output/implementation-artifacts/3-1-supervisor-hardening-health-endpoints.md` (in the repo).
