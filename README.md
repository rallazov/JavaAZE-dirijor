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

- `GET /` — service identity + aggregate status + per-dependency readiness.
- `GET /health` — same dependency map, `timestamp`, and HTTP **200** when every
  `required: true` dependency is ready; **HTTP 503** (same body shape) when any
  required dependency is not ready.
- `POST /consensus` — unchanged v0.1 placeholder (real debate loop lands in Story 3.2).
- The Docker image ships a `HEALTHCHECK` that calls `GET /health`, so
  docker / compose / K8s pick up degraded state automatically.

### `GET /` sample response

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

### `GET /health` sample response (same body on 200 and 503)

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
