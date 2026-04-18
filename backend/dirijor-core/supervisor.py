# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Dirijor Supervisor – LangGraph Multi-Agent Consensus Brain
#
# Contract / schema discipline (Story 3.1 + Story 3.2):
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

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TypedDict

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

logger = logging.getLogger("dirijor.supervisor")

# --- Service identity (single source of truth) -------------------------------

SERVICE_NAME = "dirijor-supervisor"
SERVICE_VERSION = "0.1.0"
SCHEMA_VERSION = 2
STARTED_AT = time.monotonic()
STARTUP_GRACE_S = 1.0

# Consensus defaults — PRD line 11 ("≥95% agreement") is the source of 0.95.
# Per-request overrides come through the JSON body only (no env vars).
DEFAULT_THRESHOLD = 0.95
DEFAULT_MAX_ROUNDS = 3


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


# Story 3.2 AC 8: REGISTRY is intentionally unchanged. The debate-loop readiness
# still rides on `graph_compiled` / `consensus_engine`; a separate
# `debate_loop_ready` entry would arrive with real external agents in a future
# story and is explicitly out of scope here.
REGISTRY: list[DependencyCheck] = [
    DependencyCheck("graph_compiled", True, _probe_graph_compiled),
    DependencyCheck("consensus_engine", True, _probe_graph_compiled),
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


class RootStatus(BaseModel):
    """`GET /` response model.

    v0.1 superset rule: `service`, `version`, `status`, `consensus_engine`
    MUST remain present and compatible so docker-compose / README /
    agent-wrapper callers do not regress (AC 4).
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
