# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Dirijor Supervisor – LangGraph Multi-Agent Consensus Brain
#
# Contract / schema discipline (Story 3.1 + Story 3.2 + Story 3.3):
#   - SERVICE_VERSION and SCHEMA_VERSION are the single source of truth; both
#     `/` and `/health` read them.
#   - SCHEMA_VERSION bump rules: MINOR-style bump (e.g. 1 -> 2) ONLY on
#     additive, backward-compatible changes to the response shape; a MAJOR
#     bump (documented in the changelog) is required to remove or rename any
#     field that has already shipped. Keys present in v0.1 (`service`,
#     `version`, `status`, `consensus_engine`) MUST NOT be removed or
#     renamed without a major bump — see docs/project-context.md
#     "keep API contracts stable while iterating".
#   - Adding a dependency is a single-line registration in REGISTRY; do not
#     branch the endpoint bodies.
#
# Schema changelog:
#   v1 (Story 3.1, 2026-04-16) — Structured `/` + `/health` via Pydantic
#     response_model. `/consensus` kept its v0.1 three-key body
#     (`messages`, `consensus_score`, `verified_facts`) unchanged.
#   v2 (Story 3.2, 2026-04-17) — Additive on `POST /consensus` 200 path only.
#     New top-level keys on the 200 response: `decision`, `votes`,
#     `termination_reason`, `rounds`, `threshold`. The v0.1 three keys are
#     preserved with the same semantic meaning (`consensus_score` now carries
#     the final round's real quorum score instead of the 0.97 stub).
#     The `graph is None` 503 branch is INTENTIONALLY NOT extended — it still
#     returns exactly the v0.1 three-key body so strict parsers survive a
#     compile-failure degradation (Story 3.1 code-review lesson; regression
#     guarded by `test_consensus_degraded_keeps_v01_key_set`).
#   v3 (Story 3.3, 2026-04-17) — Additive on `GET /` + `GET /health` +
#     introduces the WebSocket surface. New: `realtime_channel` dependency
#     entry in `checks` / `dependencies`; new `realtime` block on `RootStatus`
#     (`connections`, `heartbeat_interval_s`, `schema_version`); new
#     `/ws/realm/{realm_id}` WebSocket endpoint with the canonical 6-key
#     envelope (`type`, `schema_version`, `realm_id`, `ts`, `seq`, `payload`).
#     No 3.1 / 3.2 HTTP keys removed or renamed. Envelope keys are STRICT
#     (6 exactly); payload shapes inside each `type` are additive-only. WS
#     close-code contract: 4401 invalid_realm_id, 4403 realm_forbidden,
#     1011 internal/heartbeat-send-failed.

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TypedDict

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("dirijor.supervisor")

# --- Service identity (single source of truth) -------------------------------

SERVICE_NAME = "dirijor-supervisor"
SERVICE_VERSION = "0.1.0"
SCHEMA_VERSION = 3
STARTED_AT = time.monotonic()
STARTUP_GRACE_S = 1.0

# Consensus defaults — PRD line 11 ("≥95% agreement") is the source of 0.95.
# Per-request overrides come through the JSON body only (no env vars).
DEFAULT_THRESHOLD = 0.95
DEFAULT_MAX_ROUNDS = 3

# --- Realtime (Story 3.3) constants ------------------------------------------
#
# HEARTBEAT_INTERVAL_S is the server-controlled tick. The client reads it off
# the `session.hello` payload and uses `2 * HEARTBEAT_INTERVAL_S` as its
# inactivity reconnect trigger — keep this a module-level constant so tests
# can monkeypatch it down to sub-second values for deterministic coverage.
HEARTBEAT_INTERVAL_S = 15.0

# Realm-id grammar — locked on the URL shape. Singular `realm`, path-param
# only. Mirror this regex in any future auth or admin tooling — do not relax.
_REALM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Canonical enum of event types. Extending this enum requires a SCHEMA_VERSION
# bump + extending `supported_event_types` on the session.hello payload so
# clients can gate new types behind feature detection.
_SUPPORTED_EVENT_TYPES: tuple[str, ...] = (
    "session.hello",
    "topology.delta",
    "metrics.update",
    "hitl.pending",
    "heartbeat",
    "session.bye",
)


# --- Pydantic models: consensus request/response ----------------------------


class AgentOpinion(BaseModel):
    """One agent's vote in a single round.

    `agent_id` is optional: when omitted or passed as an empty string, the
    request handler fills it with a deterministic index-based id
    (`agent-0`, `agent-1`, …) via `_assign_default_agent_ids`, so bare
    opinions (`{"opinion": "yes"}`) are valid input and never 422.
    """

    agent_id: str = ""
    opinion: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ConsensusVote(AgentOpinion):
    """An `AgentOpinion` annotated with the round it was cast in.

    Emitted in `ConsensusResult.votes` — one entry per agent per round, in
    deterministic order (AC 7 → `test_consensus_votes_are_ordered_and_numbered`).
    """

    round: int = Field(ge=1)


class ConsensusRequest(BaseModel):
    """`POST /consensus` request body — all fields optional.

    An empty body (`{}`) → no-opinions fallback (`termination_reason`
    `"no_opinions"`). `query` (body or query-string) with no `opinions`
    synthesizes a 3-agent opinion set that all echo the query text, so the
    legacy `?query=...` smoke path still exercises the real loop.
    """

    query: str | None = None
    opinions: list[AgentOpinion] = Field(default_factory=list)
    max_rounds: int = Field(default=DEFAULT_MAX_ROUNDS, ge=1, le=10)
    threshold: float = Field(default=DEFAULT_THRESHOLD, ge=0.0, le=1.0)


class ConsensusResult(BaseModel):
    """`POST /consensus` 200 response — SCHEMA v2 superset of v0.1.

    v0.1 keys (preserved — AC 6 invariant):
      - `messages` — list containing the query echoed (empty list when no query).
      - `consensus_score` — **real** final-round quorum score in `[0.0, 1.0]`.
        `1.0` for a single opinion, `0.0` for zero opinions.
      - `verified_facts` — reserved for Qdrant wiring in Story 4.1; currently `[]`.

    v2 additive keys (AC 5):
      - `decision` — the agreed opinion text, or `null` when threshold was not
        reached / no opinions were supplied.
      - `votes` — every opinion from every round, in submission order.
      - `termination_reason` — one of `threshold_reached`, `max_rounds_exhausted`,
        `single_opinion_shortcut`, `no_opinions`.
      - `rounds` — how many rounds actually ran (≥ 1).
      - `threshold` — echo of the effective threshold for this request.
    """

    messages: list[str]
    consensus_score: float
    verified_facts: list
    decision: str | None
    votes: list[ConsensusVote]
    termination_reason: str
    rounds: int = Field(ge=1)
    threshold: float = Field(ge=0.0, le=1.0)


# --- LangGraph consensus workflow -------------------------------------------


class AgentState(TypedDict):
    # v0.1 keys — preserved (Story 3.1 AC 4 invariant).
    messages: list
    consensus_score: float
    verified_facts: list
    # Story 3.2 additive state (never surfaces on the 503 body).
    opinions: list[AgentOpinion]
    votes: list[ConsensusVote]
    round: int
    max_rounds: int
    threshold: float
    decision: str | None
    termination_reason: str | None


def score_round(opinions: list[AgentOpinion]) -> tuple[float, str | None]:
    """Deterministic v0.1 quorum scorer.

    Algorithm (intentionally simple — swap-target for Story 4.1 embeddings):
      1. Normalize each opinion by `strip().lower()` and group by normalized text.
      2. `score = size_of_largest_group / total_opinions`.
      3. `majority_opinion` = the ORIGINAL (non-normalized) text of the
         first opinion in the largest group (stable first-seen tie-break).

    Returns `(0.0, None)` for an empty list and `(1.0, that_opinion)` for a
    single-opinion list. Score is rounded to 4 decimals so response bodies
    are diff-stable across platforms.
    """
    if not opinions:
        return 0.0, None
    if len(opinions) == 1:
        return 1.0, opinions[0].opinion

    groups: dict[str, list[AgentOpinion]] = {}
    for op in opinions:
        key = op.opinion.strip().lower()
        groups.setdefault(key, []).append(op)
    best_group = max(groups.values(), key=len)
    score = len(best_group) / len(opinions)
    return round(score, 4), best_group[0].opinion


def decide_router(state: AgentState) -> str:
    """LangGraph conditional-edge router after `score_node`.

    Order of checks matters (AC 3 + AC 4):
      - `halt_short_circuit` — 0 or 1 opinion: no debate possible.
      - `halt_threshold` — current round already crossed the quorum bar.
      - `halt_max_rounds` — we exhausted the configurable round cap.
      - `continue` — run another `propose → score` cycle.
    """
    if len(state["opinions"]) <= 1:
        return "halt_short_circuit"
    if state["consensus_score"] >= state["threshold"]:
        return "halt_threshold"
    if state["round"] >= state["max_rounds"]:
        return "halt_max_rounds"
    return "continue"


def propose_node(state: AgentState) -> AgentState:
    """Round 1: pass opinions through. Round ≥2: deterministic dissenter update.

    The round-≥2 rule is a **v0.1 stub** for real multi-agent
    re-deliberation (which arrives with live LLM-backed agents in
    Story 3.3 / 4.x). Rule: for each opinion NOT in the current majority
    group, if `len(majority_group) - len(its_group) >= 2`, copy the
    majority opinion text into that opinion — simulating the dissenter
    being "convinced" by a clearly larger group. Ties and near-ties leave
    the opinion unchanged, so a genuinely split room never collapses.
    """
    state["round"] = state.get("round", 0) + 1

    if state["round"] == 1 or not state["opinions"]:
        return state

    groups: dict[str, list[AgentOpinion]] = {}
    for op in state["opinions"]:
        key = op.opinion.strip().lower()
        groups.setdefault(key, []).append(op)
    if not groups:
        return state
    majority_key = max(groups, key=lambda k: len(groups[k]))
    majority_text = groups[majority_key][0].opinion
    majority_size = len(groups[majority_key])

    updated: list[AgentOpinion] = []
    for op in state["opinions"]:
        key = op.opinion.strip().lower()
        group_size = len(groups[key])
        if key != majority_key and (majority_size - group_size) >= 2:
            updated.append(
                AgentOpinion(
                    agent_id=op.agent_id,
                    opinion=majority_text,
                    confidence=op.confidence,
                )
            )
        else:
            updated.append(op)
    state["opinions"] = updated
    return state


def score_node(state: AgentState) -> AgentState:
    """Compute the round's quorum score and append its votes to the trail."""
    score, majority = score_round(state["opinions"])
    state["consensus_score"] = score
    round_idx = state["round"]
    for op in state["opinions"]:
        state["votes"].append(
            ConsensusVote(
                agent_id=op.agent_id,
                opinion=op.opinion,
                confidence=op.confidence,
                round=round_idx,
            )
        )
    # Provisional decision — finalized by the endpoint based on the
    # terminal router branch so we don't approve below-threshold results.
    state["decision"] = majority
    return state


_graph_compile_error: str | None = None
try:
    _workflow = StateGraph(AgentState)
    _workflow.add_node("propose", propose_node)
    _workflow.add_node("score", score_node)
    _workflow.set_entry_point("propose")
    _workflow.add_edge("propose", "score")
    _workflow.add_conditional_edges(
        "score",
        decide_router,
        {
            "halt_threshold": END,
            "halt_max_rounds": END,
            "halt_short_circuit": END,
            "continue": "propose",
        },
    )
    graph = _workflow.compile()
    _graph_compiled_ok = True
except Exception as exc:  # pragma: no cover - defensive, should not trigger in v0.1
    graph = None  # type: ignore[assignment]
    _graph_compiled_ok = False
    _graph_compile_error = f"{type(exc).__name__}: {exc}"
    logger.exception("LangGraph workflow failed to compile; /health will report degraded")


# --- Readiness registry -------------------------------------------------------


@dataclass(frozen=True)
class DependencyCheck:
    """One dependency the supervisor reports in `/` and `/health`.

    `probe` returns `(ready, detail)`. `detail` is either a short human
    string (for planned / not-yet-ready deps) or `None` when ready.
    `probe` must never raise — wrap risky work internally; `resolve_readiness`
    also defends against raising probes to keep AC-2's "never 500" promise.
    """

    name: str
    required: bool
    probe: Callable[[], tuple[bool, str | None]]


def _probe_graph_compiled() -> tuple[bool, str | None]:
    if _graph_compiled_ok:
        return True, None
    return False, _graph_compile_error or "LangGraph workflow failed to compile"


def _probe_semantic_cache() -> tuple[bool, str | None]:
    # Qdrant integration lands in Story 4.1; flagged as not-required so absence
    # does not flip the supervisor into `degraded` in v0.1.
    return False, "planned — see Story 4.1"


def _probe_mesh() -> tuple[bool, str | None]:
    # Headscale/Tailscale bootstrap lands in Story 5.1.
    return False, "planned — see Story 5.1"


def _probe_realtime_channel() -> tuple[bool, str | None]:
    # Story 3.3 v0.1 probe: the WebSocket route is registered at import time,
    # so if this module imported cleanly the channel is structurally ready.
    # Story 6.1 (OTel) will expand this into an active-connection health read.
    return True, None


# Story 3.2 AC 8: REGISTRY consensus wiring is intentionally unchanged — the
# debate-loop readiness still rides on `graph_compiled` / `consensus_engine`.
# Story 3.3 AC 7: `realtime_channel` added between `consensus_engine` and
# `semantic_cache` so operators see Canvas wiring before future-state deps.
REGISTRY: list[DependencyCheck] = [
    DependencyCheck("graph_compiled", True, _probe_graph_compiled),
    DependencyCheck("consensus_engine", True, _probe_graph_compiled),
    DependencyCheck("realtime_channel", True, _probe_realtime_channel),
    DependencyCheck("semantic_cache", False, _probe_semantic_cache),
    DependencyCheck("mesh", False, _probe_mesh),
]


def resolve_readiness() -> dict[str, dict]:
    """Return the canonical `checks` / `dependencies` payload.

    Defends against a misbehaving probe so `/health` can answer with 503 +
    a shaped body instead of bubbling a 500 (AC 2).
    """
    out: dict[str, dict] = {}
    for dep in REGISTRY:
        try:
            ready, detail = dep.probe()
        except Exception as exc:  # pragma: no cover - probes are simple in v0.1
            ready, detail = False, f"probe raised: {type(exc).__name__}: {exc}"
            logger.warning("readiness probe '%s' raised: %s", dep.name, exc)
        out[dep.name] = {
            "ready": bool(ready),
            "required": dep.required,
            "detail": detail,
        }
    return out


def _aggregate_status(checks: dict[str, dict], uptime_s: float) -> str:
    """Derive the top-level `status` string from the resolved checks."""
    required_ready = all(
        entry["ready"] for entry in checks.values() if entry["required"]
    )
    if required_ready:
        return "operational"
    if uptime_s < STARTUP_GRACE_S:
        return "starting"
    return "degraded"


def _uptime_seconds() -> float:
    return round(time.monotonic() - STARTED_AT, 3)


# --- Pydantic response models (health / root contract surface) ---------------


class DependencyStatus(BaseModel):
    """One entry in the `dependencies` / `checks` map.

    Schema rules (mirrors SCHEMA_VERSION comment at top of module):
      - `ready`, `required`, `detail` keys MUST remain present.
      - `detail` is `null` when ready with no extra context.
      - Added keys REQUIRE bumping SCHEMA_VERSION.
    """

    ready: bool
    required: bool
    detail: str | None = None


class RealtimeSummary(BaseModel):
    """Realtime (WebSocket) surface summary on `GET /` (Story 3.3, schema v3).

    Additive to `RootStatus` — `service`, `version`, `status`, `consensus_engine`
    from v0.1 remain present. Introduced so operators can see at-a-glance how
    many canvas sessions are live without opening a dashboard.
    """

    connections: int = Field(
        ge=0,
        description="Sum of open sessions across all realms (in-process only).",
    )
    heartbeat_interval_s: float = Field(
        gt=0.0,
        description="Server-controlled heartbeat cadence (seconds).",
    )
    schema_version: int = Field(
        description="Echo of SCHEMA_VERSION so clients can cross-check envelopes."
    )


class RootStatus(BaseModel):
    """`GET /` response model.

    v0.1 superset rule: `service`, `version`, `status`, `consensus_engine`
    MUST remain present and compatible so docker-compose / README /
    agent-wrapper callers do not regress (AC 4). Story 3.3 adds the
    `realtime` block under SCHEMA_VERSION=3 as a pure additive field.
    """

    service: str
    version: str
    schema_version: int
    status: str = Field(
        description="'operational' | 'degraded' | 'starting' — aggregate of required deps."
    )
    consensus_engine: str = Field(
        description="'ready' | 'unavailable' — v0.1 alias for graph_compiled readiness."
    )
    uptime_s: float
    dependencies: dict[str, DependencyStatus]
    realtime: RealtimeSummary = Field(
        description="Story 3.3 additive — WebSocket channel summary.",
    )


class HealthStatus(BaseModel):
    """`GET /health` response model.

    Same shape is returned on 200 and 503 so polling clients (docker HEALTHCHECK,
    canvas HUD in Story 6.3) can parse unconditionally (AC 2).
    Schema-version bump rules: see module-level contract comment.
    """

    status: str = Field(
        description="'ok' | 'degraded' | 'starting' — aggregate of required deps."
    )
    version: str
    schema_version: int
    uptime_s: float
    timestamp: str
    checks: dict[str, DependencyStatus]


# --- FastAPI Server ----------------------------------------------------------

app = FastAPI(title="Dirijor Supervisor", version=SERVICE_VERSION)


def _consensus_engine_label() -> str:
    return "ready" if _graph_compiled_ok else "unavailable"


@app.get("/", response_model=RootStatus)
def root() -> RootStatus:
    checks = resolve_readiness()
    uptime = _uptime_seconds()
    status = _aggregate_status(checks, uptime)
    return RootStatus(
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        schema_version=SCHEMA_VERSION,
        status=status,
        consensus_engine=_consensus_engine_label(),
        uptime_s=uptime,
        dependencies={name: DependencyStatus(**entry) for name, entry in checks.items()},
        realtime=RealtimeSummary(
            connections=sum(len(bucket) for bucket in _CONNECTIONS.values()),
            heartbeat_interval_s=HEARTBEAT_INTERVAL_S,
            schema_version=SCHEMA_VERSION,
        ),
    )


@app.get(
    "/health",
    response_model=HealthStatus,
    responses={503: {"model": HealthStatus, "description": "Degraded — a required dependency is not ready."}},
)
def health():
    checks = resolve_readiness()
    uptime = _uptime_seconds()
    aggregate = _aggregate_status(checks, uptime)
    # /health uses "ok" (not "operational") for the healthy state to preserve
    # the v0.1 `{"status": "ok"}` contract for existing poll clients.
    status = "ok" if aggregate == "operational" else aggregate
    payload = HealthStatus(
        status=status,
        version=SERVICE_VERSION,
        schema_version=SCHEMA_VERSION,
        uptime_s=uptime,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        checks={name: DependencyStatus(**entry) for name, entry in checks.items()},
    )
    required_ok = all(
        entry["ready"] for entry in checks.values() if entry["required"]
    )
    if required_ok:
        return payload
    return JSONResponse(status_code=503, content=payload.model_dump())


# --- `/consensus` ------------------------------------------------------------


def _merge_request(
    body: ConsensusRequest | None, query: str | None
) -> ConsensusRequest:
    """Merge the JSON body and the legacy `?query=` param into one request.

    Body wins on any field it supplies; the query-string `query` is used
    only when the body omits `query` (or body is absent). Preserves
    Story 3.1's `POST /consensus?query=foo` smoke path.
    """
    if body is None:
        return ConsensusRequest(query=query)
    if body.query is None and query is not None:
        return body.model_copy(update={"query": query})
    return body


def _synthesize_opinions_from_query(query: str) -> list[AgentOpinion]:
    """Backward-compat shim: turn a bare `?query=foo` call into a real loop.

    3 simulated agents all echoing the query text → the loop sees a
    unanimous opinion set, hits the threshold in round 1, and the legacy
    caller still gets the v0.1 keys (plus the v2 superset) in one pass.
    """
    return [
        AgentOpinion(agent_id=f"agent-{i}", opinion=query, confidence=1.0)
        for i in range(3)
    ]


def _assign_default_agent_ids(opinions: list[AgentOpinion]) -> list[AgentOpinion]:
    """Fill `agent-N` for opinions the caller left with an empty agent_id."""
    out: list[AgentOpinion] = []
    for idx, op in enumerate(opinions):
        if not op.agent_id:
            out.append(
                AgentOpinion(
                    agent_id=f"agent-{idx}", opinion=op.opinion, confidence=op.confidence
                )
            )
        else:
            out.append(op)
    return out


@app.post(
    "/consensus",
    response_model=ConsensusResult,
    responses={
        503: {
            "description": "Degraded — LangGraph failed to compile at import. "
            "Body keeps the exact v0.1 three-key shape for strict parsers."
        }
    },
)
def run_consensus(
    query: str | None = None,
    body: ConsensusRequest | None = Body(default=None),
):
    """Run the multi-agent debate loop and return the SCHEMA v2 result.

    Accepts **either** a JSON body (`ConsensusRequest`) **or** the legacy
    `?query=` query-string param. When both are present, the body wins for
    any field it supplies; `?query=` fills in only when the body omits it.
    Empty body **and** no `query` → no-opinions fallback.

    Degraded path (AC 4 invariant from Story 3.1): when `graph is None`
    we short-circuit to HTTP 503 with EXACTLY the v0.1 three-key body —
    no additive v2 fields — so strict parsers don't break on compile
    failure. Operators read the failure reason from `GET /health`.
    """
    req = _merge_request(body, query)

    if graph is None:
        return JSONResponse(
            status_code=503,
            content={
                "messages": [req.query] if req.query else [],
                "consensus_score": 0.0,
                "verified_facts": [],
            },
        )

    opinions = list(req.opinions)
    if not opinions and req.query is not None:
        opinions = _synthesize_opinions_from_query(req.query)
    opinions = _assign_default_agent_ids(opinions)

    initial_state: AgentState = {
        "messages": [req.query] if req.query else [],
        "consensus_score": 0.0,
        "verified_facts": [],
        "opinions": opinions,
        "votes": [],
        "round": 0,
        "max_rounds": req.max_rounds,
        "threshold": req.threshold,
        "decision": None,
        "termination_reason": None,
    }

    if not opinions:
        # Skip graph.invoke for the empty case — no propose/score work to do,
        # and we want a crisp `rounds=1, termination_reason=no_opinions`
        # without relying on the router's short-circuit branch (which also
        # runs for the single-opinion path but carries different semantics).
        result_state: AgentState = {
            **initial_state,
            "round": 1,
            "consensus_score": 0.0,
            "decision": None,
            "termination_reason": "no_opinions",
        }
        branch = "halt_short_circuit"
    else:
        result_state = graph.invoke(initial_state)
        branch = decide_router(result_state)

    if not opinions:
        termination_reason = "no_opinions"
        decision: str | None = None
    elif branch == "halt_threshold":
        termination_reason = "threshold_reached"
        decision = result_state.get("decision")
    elif branch == "halt_max_rounds":
        termination_reason = "max_rounds_exhausted"
        decision = None  # AC 2: below-threshold is a normal no-decision outcome.
    elif branch == "halt_short_circuit":
        termination_reason = "single_opinion_shortcut"
        decision = result_state.get("decision")
    else:
        # Defensive — router should always terminate on END at loop exit.
        termination_reason = "max_rounds_exhausted"
        decision = None

    rounds = max(1, int(result_state.get("round", 1)))

    payload = ConsensusResult(
        messages=result_state.get("messages", []),
        consensus_score=float(result_state.get("consensus_score", 0.0)),
        verified_facts=result_state.get("verified_facts", []),
        decision=decision,
        votes=result_state.get("votes", []),
        termination_reason=termination_reason,
        rounds=rounds,
        threshold=req.threshold,
    )

    # One INFO line per request at the endpoint boundary — no per-round spam.
    # Keeps stdlib logging; OTel instrumentation is Story 6.1's job.
    logger.info(
        "consensus.done",
        extra={
            "event": "consensus.done",
            "rounds": payload.rounds,
            "score": payload.consensus_score,
            "termination_reason": payload.termination_reason,
            "decision_present": payload.decision is not None,
        },
    )

    return payload


# --- Realtime WebSocket channel (Story 3.3) ----------------------------------
#
# Canvas ↔ Core real-time transport. v0.1 is ONE-WAY Core → Canvas; client →
# Core commands remain HTTP POST (Story 2.1 spin, Story 4.x HITL approvals).
# The envelope is strict-6-keys; payloads are additive per-type. Event types
# live in `_SUPPORTED_EVENT_TYPES` (module top) — adding a new type requires
# a SCHEMA_VERSION bump in a future story and an additive entry in the
# `session.hello` payload so clients can gate on feature detection.
#
# `broadcast_event` is the SOLE public emit API. Do not touch `_CONNECTIONS`
# directly from future stories (4.x anomaly, 5.x runtime, 6.x observability)
# — all outbound frames MUST go through the shared envelope / error path so
# logging, eviction, and `seq` monotonicity stay consistent.
#
# TODO(refactor): split realtime section into realtime.py when supervisor.py
# grows past ~700 lines (Story 4.2 will likely push us there).


class RealtimeEnvelope(BaseModel):
    """Canonical WebSocket frame — 6 strict keys, additive payloads.

    All outbound WS frames are shaped through `_send_envelope`, which fills
    these keys and then emits as JSON via `WebSocket.send_json`. The enum of
    `type` values is `_SUPPORTED_EVENT_TYPES` — extending requires a major
    SCHEMA_VERSION coordination with the frontend `DirijorRealtimeEvent`
    discriminated union.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    schema_version: int
    realm_id: str
    ts: str
    seq: int = Field(ge=0)
    payload: dict[str, Any]


@dataclass(eq=False)
class _WsSession:
    """One live WebSocket session bound to a realm.

    `eq=False` keeps the default identity-based `__hash__`, so instances are
    set-member-safe even though we mutate `seq` and `heartbeat_task`.
    """

    realm_id: str
    connection_id: str
    ws: WebSocket
    seq: int = 0
    heartbeat_task: asyncio.Task | None = field(default=None)


# In-process connection registry. `_CONNECTIONS` is intentionally module-level
# so `root()` and `broadcast_event` share the same view. Multi-worker scale-out
# (K8s replicas, cloud deployment) will require Redis Pub/Sub or NATS — flagged
# as a documented follow-up, NOT a pre-introduced dependency.
_CONNECTIONS: dict[str, set[_WsSession]] = {}


def _authorize_realm(realm_id: str) -> tuple[bool, str | None]:
    """Realm authorization hook — v0.1 no-op, Story 5.1 extension point.

    Returns `(ok, reason)`. `ok == False` → handshake is rejected with WS
    close code 4403. Story 5.1 (mesh identity) will replace the body with a
    real auth check (Headscale/Tailscale or a scoped WS token from spin).
    Keeping this stub as a named function keeps the route body stable.
    """

    return True, None


def _ws_timestamp() -> str:
    """ISO-8601 UTC timestamp with trailing `Z` (matches `/health.timestamp`)."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _send_envelope(
    session: _WsSession, type_: str, payload: dict[str, Any]
) -> None:
    """Emit a single canonical envelope to a session and advance its `seq`.

    `seq` is monotonic per-session starting at 0 (session.hello). `seq`
    increment happens AFTER a successful `send_json` so a failed send does
    not leak a gap into the numbering visible to other sessions. The
    caller is responsible for catching and handling send failures — this
    function intentionally does not swallow exceptions so `broadcast_event`
    can evict dead sessions and `_heartbeat_loop` can switch to 1011 close.
    """

    envelope = {
        "type": type_,
        "schema_version": SCHEMA_VERSION,
        "realm_id": session.realm_id,
        "ts": _ws_timestamp(),
        "seq": session.seq,
        "payload": payload,
    }
    await session.ws.send_json(envelope)
    session.seq += 1


async def broadcast_event(
    realm_id: str, event_type: str, payload: dict[str, Any]
) -> int:
    """Fan out a single event to every session bound to `realm_id`.

    Returns the count of successful deliveries. Per-session exceptions are
    logged at WARNING and the dead session is evicted inline — no separate
    sweeper task. Sessions on *other* realms never see the frame (tenant
    isolation invariant — regression-guarded by
    `test_ws_broadcast_reaches_only_matching_realm`).

    This is the ONLY public emit surface Story 3.3 ships. Downstream stories
    (4.2 anomaly / 4.3 audit / 6.3 canvas HUD) plug into it — they MUST NOT
    touch `_CONNECTIONS` directly.

    Story 3.3 code-review patch (AC 2 hardening): fail fast on unknown
    `event_type`. `RealtimeEnvelope` has `ConfigDict(extra="forbid")` on
    keys but not on the `type` value, so without this guard a typo like
    ``"topolgy.delta"`` (missing 'o') would silently emit a non-contract
    frame to every subscriber. Raising `ValueError` at the call site is the
    cheapest, loudest signal — the caller (typically a future Story 4.x /
    6.x emitter) crashes its own code path instead of poisoning the WS
    contract for canvas clients. Adding a new event type is a two-step,
    schema-bumping change: extend `_SUPPORTED_EVENT_TYPES`, then bump
    `SCHEMA_VERSION` + document the new payload in
    `docs/reference/supervisor-api.md`.
    """

    if event_type not in _SUPPORTED_EVENT_TYPES:
        raise ValueError(
            f"broadcast_event: unsupported event_type={event_type!r}; "
            f"must be one of {_SUPPORTED_EVENT_TYPES}"
        )

    # TODO(6.1): wrap this function in an OTel span once Story 6.1 lands.
    delivered = 0
    dead: list[_WsSession] = []
    for session in list(_CONNECTIONS.get(realm_id, set())):
        try:
            await _send_envelope(session, event_type, payload)
            delivered += 1
        except Exception as exc:  # pragma: no cover — exercised by test_ws_close_1011
            logger.warning(
                "ws.broadcast.drop realm=%s conn=%s err=%s",
                realm_id,
                session.connection_id,
                exc,
            )
            dead.append(session)
    for session in dead:
        bucket = _CONNECTIONS.get(realm_id)
        if bucket is not None:
            bucket.discard(session)
            if not bucket:
                _CONNECTIONS.pop(realm_id, None)
        try:
            await session.ws.close(code=1011, reason="broadcast_send_failed")
        except Exception:  # pragma: no cover
            pass
    return delivered


async def _heartbeat_loop(session: _WsSession) -> None:
    """Per-session heartbeat scheduler.

    Sleeps `HEARTBEAT_INTERVAL_S` seconds, emits an empty `heartbeat`
    envelope, repeat. Cancelling this task is how the route's `finally`
    block shuts the heartbeat down cleanly (no leaked task). If the send
    fails (half-open socket, client gone), the session is closed with
    WS code 1011 so clients can distinguish server-side cleanup (1011)
    from client-initiated unload (1001) — see AC 3.
    """

    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            await _send_envelope(session, "heartbeat", {})
    except asyncio.CancelledError:
        # Normal cleanup path — re-raise so the task is marked cancelled.
        raise
    except Exception as exc:  # pragma: no cover — exercised by test_ws_close_1011
        logger.warning(
            "ws.heartbeat.failed conn=%s err=%s", session.connection_id, exc
        )
        try:
            await session.ws.close(code=1011, reason="heartbeat_send_failed")
        except Exception:
            pass


@app.websocket("/ws/realm/{realm_id}")
async def realm_ws(websocket: WebSocket, realm_id: str) -> None:
    """Canvas ↔ Core real-time channel (Story 3.3, schema v3).

    URL: `/ws/realm/{realm_id}` — singular `realm`, path-param, NO query
    string. Reject codes (close BEFORE accept):
      - 4401 `invalid_realm_id` — regex fail (`^[a-zA-Z0-9_-]{1,64}$`).
      - 4403 `realm_forbidden`  — `_authorize_realm` returned `(False, …)`.
    Post-accept lifecycle:
      1. Register session in `_CONNECTIONS[realm_id]`.
      2. Emit `session.hello` (seq=0) with handshake payload.
      3. Spawn heartbeat task (15s cadence).
      4. Loop `receive_text` (discard — v0.1 is one-way).
      5. On disconnect/exception: cancel heartbeat, evict, prune bucket,
         log `ws.session.close`.
    """

    if not _REALM_ID_RE.match(realm_id or ""):
        await websocket.close(code=4401, reason="invalid_realm_id")
        return

    ok, _reason = _authorize_realm(realm_id)
    if not ok:
        await websocket.close(code=4403, reason="realm_forbidden")
        return

    await websocket.accept()
    session = _WsSession(
        realm_id=realm_id,
        connection_id=str(uuid.uuid4()),
        ws=websocket,
    )
    _CONNECTIONS.setdefault(realm_id, set()).add(session)
    logger.info(
        "ws.session.open",
        extra={
            "event": "ws.session.open",
            "realm_id": realm_id,
            "connection_id": session.connection_id,
            "conn_count": len(_CONNECTIONS[realm_id]),
        },
    )

    started = time.monotonic()
    close_code: int | None = None
    try:
        await _send_envelope(
            session,
            "session.hello",
            {
                "service_version": SERVICE_VERSION,
                "schema_version": SCHEMA_VERSION,
                "supported_event_types": list(_SUPPORTED_EVENT_TYPES),
                "heartbeat_interval_s": HEARTBEAT_INTERVAL_S,
                "connection_id": session.connection_id,
            },
        )
        session.heartbeat_task = asyncio.create_task(_heartbeat_loop(session))
        while True:
            # v0.1 is Core → Canvas only. Canvas → Core commands remain HTTP
            # POST (Story 2.1 spin, Story 4.x HITL). We receive_text to keep
            # the connection draining but intentionally discard the payload.
            await websocket.receive_text()
    except WebSocketDisconnect as disc:
        close_code = disc.code
    except Exception:  # pragma: no cover - defensive against unexpected failures
        logger.exception(
            "ws.session.crashed conn=%s", session.connection_id
        )
    finally:
        if session.heartbeat_task and not session.heartbeat_task.done():
            session.heartbeat_task.cancel()
            try:
                await session.heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
        bucket = _CONNECTIONS.get(realm_id)
        if bucket is not None:
            bucket.discard(session)
            if not bucket:
                _CONNECTIONS.pop(realm_id, None)
        logger.info(
            "ws.session.close",
            extra={
                "event": "ws.session.close",
                "realm_id": realm_id,
                "connection_id": session.connection_id,
                "close_code": close_code,
                "seq_last": session.seq,
                "duration_s": round(time.monotonic() - started, 3),
            },
        )
