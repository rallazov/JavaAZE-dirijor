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
preserved).

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
  "schema_version": 2,
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

### `GET /health` sample response (same body on 200 and 503)

```json
{
  "status": "ok",
  "version": "0.1.0",
  "schema_version": 2,
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
