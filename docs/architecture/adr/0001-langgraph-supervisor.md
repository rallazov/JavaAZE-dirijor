<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# ADR-0001: LangGraph as the supervisor substrate

- **Status:** Accepted
- **Date:** 2026-04-16
- **Deciders:** Ramin Allazov (JavaAZE)
- **Related PRD clause:** *"LangGraph-based Dirijor Core supervisor with multi-agent consensus (≥95% agreement) + Verified Semantic Cache."* — [DIRIJOR-PRD.md](../../DIRIJOR-PRD.md)
- **Related stories:** Story 3.1 (supervisor hardening, done), 3.2 (consensus beyond placeholder), 3.3 (canvas ↔ core real-time).

## Context

The Dirijor Core supervisor has four overlapping responsibilities:

1. **Routing** — agent-to-agent traffic and tool calls inside a realm.
2. **Consensus** — coordinating multi-agent debates, applying a quorum,
   returning structured no-decision outcomes when the quorum fails
   (see [ADR-0002](0002-consensus-threshold-95.md)).
3. **Safety hooks** — verified semantic cache lookups, anomaly /
   quarantine triggers, human-in-the-loop gates.
4. **Observable state** — stable HTTP/WebSocket contracts for the
   canvas (Story 3.3) and OpenTelemetry (Story 6.1) to bind to, plus
   the readiness registry hardened in Story 3.1.

All four responsibilities share one property: **they're stateful graphs
of computations with branch conditions**, not linear pipelines. A
consensus round forks into N per-agent evaluations, joins, votes,
loops. A safety hook may interrupt and route to a HITL gate. A tool
call may traverse the graph repeatedly.

We needed a runtime that:

- Models workflows as **graphs of stateful nodes**, not ad-hoc async code.
- Plays well with **Python + FastAPI** (existing stack, Dockerfile
  pinned to `python:3.12-slim`).
- Survives **contract stability** requirements — the supervisor's HTTP
  surface must not drift as the graph evolves (Story 3.1 AC 4/5).
- Doesn't force us to own a custom scheduler, persistence layer, or
  execution engine.

## Decision

**Use LangGraph (`>=0.2.0`) as the supervisor's orchestration substrate,
inside a FastAPI service.**

Concretely:

- `StateGraph(AgentState)` declares supervisor workflows.
- Graph compiles at module import; a `try/except` around
  `.compile()` surfaces a bad graph definition as `/health` 503, not an
  import-time crash (Story 3.1 implementation).
- The compiled graph is invoked inside FastAPI route handlers
  (`POST /consensus`), so the HTTP surface is the supervisor's
  contract, independent of the graph's internal shape.
- LangGraph upgrades happen on dedicated stories — not opportunistically.

## Consequences

### Positive

- **Graph-shaped problems get graph-shaped code.** Consensus rounds,
  safety hooks, and retrieval fan-outs express naturally as
  `StateGraph` nodes and edges; reviewers can read the shape without
  reconstructing it from callbacks.
- **We don't own a scheduler.** LangGraph handles node invocation,
  state threading, and conditional edges. Our job shrinks to "define
  nodes, define edges, expose an HTTP contract."
- **Readiness signal is natural.** "Did the graph compile?" is a
  well-defined boolean that maps directly onto the `graph_compiled`
  dependency in the readiness registry.
- **Ecosystem alignment.** Most multi-agent tooling (LangChain,
  LlamaIndex integrations, observability hooks) speaks LangGraph
  idioms as of April 2026.

### Negative / costs we accept

- **Framework lock-in.** Replacing LangGraph is a non-trivial migration.
  We mitigate by keeping all LangGraph imports and compiled-graph usage
  contained in `supervisor.py`, with the **HTTP contract** — not the
  graph — as the stable surface every other subsystem binds to.
- **Version discipline required.** LangGraph is evolving quickly.
  Pinning to `>=0.2.0` and gating upgrades behind stories (not
  opportunistic `pip install -U`) is mandatory.
- **Cold-start surface area.** A bad graph definition will fail at
  import; Story 3.1's `try/except` pattern plus a `graph_compiled`
  readiness bit is the mitigation — the service starts and reports
  degraded rather than crashing the container.

### What this commits us to

- **The supervisor's HTTP contract is the public API**, not the graph
  shape. Callers read `GET /`, `GET /health`, `POST /consensus` (and
  later WebSocket channels); they never observe LangGraph types.
- **Schema-versioned contract.** Any breaking graph change must keep
  the HTTP response shape compatible — additive → minor, rename or
  remove → major `schema_version` bump (Story 3.1 AC 5).
- **Consensus and safety hooks live inside the graph**, not as
  external middleware. That's the architectural guarantee; bypassing
  it (e.g. calling an agent directly from a FastAPI handler) is a
  review-blocking smell.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Plain async Python + FastAPI** (no graph framework) | Works, but encodes graph semantics into callbacks; consensus rounds and safety hooks become hard to read and hard to test in isolation. We'd reinvent LangGraph poorly. |
| **LangChain `AgentExecutor` / chains** | Optimized for linear chains + tool-use; doesn't cleanly model branching consensus or interrupt-driven HITL gates. LangGraph is the `graph` upgrade path explicitly. |
| **CrewAI** | Higher-level abstraction over "crews of agents"; opinions on roles and tasks that don't map cleanly to Dirijor's routing + consensus + safety model. Would fight us on the zero-trust runtime. |
| **AutoGen** | Strong for multi-agent conversations; weaker on stateful graph execution and the readiness / contract discipline we need for the canvas binding. |
| **Temporal / Prefect / Airflow** | Workflow engines targeted at durable business workflows (retries, schedules). Overkill for agent-turn latency and conceptually the wrong shape — these orchestrate *jobs*, not *agent graphs*. |
| **Custom DAG executor** | We'd own scheduling, persistence, and the learning curve. No strategic advantage; high maintenance tax. |

## References

- PRD non-negotiable: *"LangGraph-based Dirijor Core supervisor…"* — [DIRIJOR-PRD.md](../../DIRIJOR-PRD.md)
- System diagram: [`docs/architecture.mermaid`](../../architecture.mermaid)
- Supervisor module: `backend/dirijor-core/supervisor.py`
- Story 3.1 (supervisor hardening + readiness registry): `_bmad-output/implementation-artifacts/3-1-supervisor-hardening-health-endpoints.md` (in the repo)
- Supervisor API reference: [`../../reference/supervisor-api.md`](../../reference/supervisor-api.md)
- Consensus threshold decision: [ADR-0002](0002-consensus-threshold-95.md)
