<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# Tutorial — Your first local Dirijor environment

> **Last verified:** 2026-04-16, against the supervisor contract hardened
> in Story 3.1 (v0.1.0, schema_version 1). If this page is stale, treat
> it as untrusted until a maintainer re-runs it.

**Time:** 10–15 minutes.
**Prerequisites:** Docker Desktop (or Docker Engine + Compose v2),
Node 18+, Python 3.12+, and git.

---

## Why this tutorial matters

Dirijor's end-state is a one-click private realm on the cloud of your
choice. **v0.1 is not there yet** — the mesh and cache subsystems are
still being built (Stories 4.1 and 5.1). What *is* there is the full
control plane locally: the **supervisor** with its hardened HTTP
contract, and the **Network Canvas** UI. Running both together is the
fastest way to:

- Understand the pieces that will later compose a real realm.
- Verify your environment can build and run Dirijor before you touch infra.
- See the `operational` / `degraded` health contract in action — the
  same contract K8s and Docker Compose will use in production.

## What you'll have at the end

- The supervisor running on `http://localhost:8000`, serving
  `GET /`, `GET /health`, and `POST /consensus`.
- The canvas UI running on `http://localhost:3000`, redirecting to
  `/canvas`.
- A terminal window where you can `curl` the supervisor and watch the
  readiness registry report which subsystems are ready and which are
  still planned.
- Confidence that when real-realm provisioning lands (Epic 2), you
  already know the moving parts.

---

## Step 1 — Clone and inspect

**Why.** You want to know the repo layout before you run anything. The
PRD, architecture diagram, and the supervisor source are all things
you'll reference during this tutorial and afterwards.

```bash
git clone https://github.com/JavaAZE/JavaAZE-dirijor.git
cd JavaAZE-dirijor
ls
```

You should see top-level `backend/`, `frontend/`, `docs/`,
`docker-compose.yml`, and `_bmad/` (the planning system — read-only for
this tutorial).

**Verify:** `cat docs/architecture.mermaid` prints the system diagram.
That file is the canonical source of truth for what Dirijor is made of.

**What this unlocks:** you now know where to go when you want to
understand a behavior — `backend/dirijor-core/` for the supervisor,
`frontend/` for the canvas, `docs/` for narrative, `_bmad-output/` for
the sprint state.

---

## Step 2 — Start the supervisor in Docker

**Why.** The supervisor is the "control plane" node in the architecture
diagram. Running it first means every other piece you start has a live
contract to bind to — the same contract production will use.

```bash
docker compose up --build dirijor-supervisor
```

Leave this terminal running. You should see uvicorn serving on port 8000.

**Verify:**

```bash
# In a second terminal
curl -s http://localhost:8000/ | python -m json.tool
```

You should see a response whose shape matches this (values will differ):

```json
{
  "service": "dirijor-supervisor",
  "version": "0.1.0",
  "schema_version": 1,
  "status": "operational",
  "consensus_engine": "ready",
  "uptime_s": 4.8,
  "dependencies": {
    "graph_compiled":    { "ready": true,  "required": true,  "detail": null },
    "consensus_engine":  { "ready": true,  "required": true,  "detail": null },
    "semantic_cache":    { "ready": false, "required": false, "detail": "planned — see Story 4.1" },
    "mesh":              { "ready": false, "required": false, "detail": "planned — see Story 5.1" }
  }
}
```

!!! tip "What to notice"
    `semantic_cache` and `mesh` are explicitly **not required** and
    explicitly **not ready** — because they're planned work. This is
    intentional honesty from the supervisor's readiness contract. When
    they become real, these flags flip and the contract doesn't change
    shape. See [Supervisor API reference](../../reference/supervisor-api.md).

**What this unlocks:** every subsequent integration you build against
the supervisor can distinguish *ready* from *planned* without parsing
free-form strings.

---

## Step 3 — Health-check the supervisor

**Why.** The `/health` endpoint is what Docker's `HEALTHCHECK`,
Kubernetes, and monitoring pipelines will read. Understanding its 200
vs 503 behavior now means you won't be surprised in production.

```bash
curl -i http://localhost:8000/health
```

You should see **`HTTP/1.1 200 OK`** and a body containing `"status": "ok"`,
a UTC `timestamp` ending in `Z`, and the same `checks` map as above.

**Verify the degraded path:** the cleanest way to see a 503 locally is
via the supervisor test suite (next step) — it uses the readiness
registry to simulate a required dependency failure and proves the 503
body shape is identical to the 200 body shape.

**What this unlocks:** you now know that if any required dependency
goes unready, the supervisor returns 503 with the *same keys*, so
dashboards and the canvas don't need two codepaths.

---

## Step 4 — Run the supervisor test suite

**Why.** The test suite is the fastest way to see the full contract
exercised — the 200 happy path, the 503 degraded path, the consensus
endpoint smoke test, and the pinned schema version. It's also the
fastest way to verify your local Python environment matches what the
Docker image runs.

From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/dirijor-core/requirements-dev.txt
python -m pytest backend/dirijor-core/tests
```

**Verify:** you should see `10 passed` in under a second.
(Story 3.1 shipped 10 cases covering AC 1–7 including the post-review
regression guard.)

**What this unlocks:** when you contribute code, you'll use this same
suite to prove you didn't break the contract. The tests are
`TestClient`-based — no network, no port binding — so they run
identically in CI.

---

## Step 5 — Start the Network Canvas

**Why.** The canvas is the operator's primary workspace. In v0.1 it
runs standalone (the Core ↔ Canvas WebSocket channel lands in Story
3.3), but you can already see the command-center UI, inspector, and
HITL gate UX that every future realm will use.

In a new terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000` — you'll be redirected to `/canvas`.

**Verify:** the canvas loads with a dark command-center theme, a
toolbar, inspector region, and status region. You can pan, zoom, and
drag nodes (positions persist for the session).

**What this unlocks:** the UI concepts from
[Realms](../../product/concepts/realms.md) and
[Zero-trust](../../product/concepts/zero-trust.md) — agent cards, HITL
gates, audit preview — are now tangible.

---

## Step 6 — Stop everything cleanly

**Why.** Cleanup is part of the realm lifecycle. Even at v0.1 you want
to form the habit: compose → operate → tear down.

```bash
# Stop the canvas dev server: Ctrl-C in its terminal
# Stop the supervisor stack:
docker compose down
```

**Verify:** `docker compose ps` returns no running services.

**What this unlocks:** you've walked the local equivalent of the full
realm lifecycle described in
[Concept — Realms](../../product/concepts/realms.md). Real realm spin
(Epic 2, Stories 2.1–2.3) will wrap this same shape — compose / spin /
operate / tear down — over real IaC adapters.

---

## Troubleshooting

??? failure "`docker compose up` fails on `dirijor-supervisor` build"

    Re-run with `docker compose build --no-cache dirijor-supervisor`.
    If the failure is in `pip install`, verify Docker can reach PyPI
    (`docker run --rm python:3.12-slim pip --version`). Corporate
    proxies sometimes block this and need `HTTP_PROXY` / `HTTPS_PROXY`
    env vars forwarded into the build.

??? failure "`curl http://localhost:8000/` returns connection refused"

    The supervisor is still starting. Give it a few seconds — on cold
    start the aggregate `status` can report `"starting"` during the
    first 1 second (the grace window defined in `supervisor.py`).
    After that, `/health` is the authoritative readiness signal.

??? failure "`pytest` reports module-not-found errors"

    Make sure you activated the venv (`source .venv/bin/activate`) and
    installed from **`requirements-dev.txt`**, not `requirements.txt` —
    the dev file pulls `pytest` and `httpx` on top of the runtime deps.

??? failure "The canvas UI shows a blank screen or 500"

    Check `frontend/` for a previous build: `rm -rf frontend/.next` and
    re-run `npm install && npm run dev`. The canvas is still
    pre-wiring to Core (`useDirijorRealtime({ url: undefined })` per
    Story 1.4 notes), so a supervisor that isn't running will **not**
    break the canvas — they're independent processes in v0.1.

---

## Where to go next

- **Understand the contract you just exercised:** [Supervisor API reference](../../reference/supervisor-api.md).
- **Understand the concepts you just saw:** [Realms](../../product/concepts/realms.md), [Consensus](../../product/concepts/consensus.md), [Zero-trust by default](../../product/concepts/zero-trust.md).
- **Understand the bigger picture:** [Architecture overview](../../architecture/overview.md) + [why the supervisor is built on LangGraph (ADR-0001)](../../architecture/adr/0001-langgraph-supervisor.md).
- **Plan forward:** the epics + stories planning artifact at `_bmad-output/planning-artifacts/epics.md` (in the repo) shows what lights up next — Story 3.2 consensus beyond placeholder, Story 3.3 canvas↔core channel, Epic 2 realm provisioning.
