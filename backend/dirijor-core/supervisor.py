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
#   v3 (Story 2.1, 2026-04-18 — dep-only additive) — Adds `realm_manager`
#     entry to the readiness registry `checks` / `dependencies` map and
#     introduces the `POST /realms/spin` + `GET /realms/{job_id}` HTTP
#     surface with a closed `SpinError.code` envelope. SCHEMA_VERSION was
#     intentionally not bumped for 2.1 alone — see Story 2.2 changelog below.
#   v4 (Story 2.2, 2026-04-18) — DELETE /realms/{job_id}; SpinJob.outputs
#     destroy-lifecycle keys; nine new SpinError codes (terraform + destroy
#     HTTP). See SCHEMA_VERSION comment below the literal.

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
import os
import re
import shutil
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence, TypedDict, get_args

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger("dirijor.supervisor")

# --- Service identity (single source of truth) -------------------------------

SERVICE_NAME = "dirijor-supervisor"
SERVICE_VERSION = "0.1.0"
# SCHEMA_VERSION bumped 3 -> 4 by Story 2.2. Rationale: additive
# expansion of three surfaces:
#   (a) DELETE /realms/{job_id} route — new endpoint.
#   (b) SpinJob.outputs gains `destroy_requested_at`, `destroyed`,
#       `destroyed_at`, `destroy_error` fields on terraform-backed
#       jobs (outputs is a `dict[str, Any]` so this is a key-addition
#       inside a free-form map — technically non-breaking, but we
#       bump anyway so clients can feature-gate the destroy UI).
#   (c) Nine new SpinError.code enum values (7 terraform-scoped
#       adapter errors + 2 destroy-HTTP errors).
# Contrast with Story 2.1 which did NOT bump: that story added a
# readiness-registry dep only, which the stability policy
# explicitly exempts. This bump follows the Story 3.3 precedent
# (new top-level surface -> bump).
SCHEMA_VERSION = 4
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


def _probe_realm_manager() -> tuple[bool, str | None]:
    # Story 2.1 probe: structural check that at least one realm adapter has
    # been registered. `_ADAPTERS` is defined later in the Story 2.1 block;
    # the probe is only invoked at request time (FastAPI handler or `/health`
    # poll), well after module import, so the forward reference is safe.
    #
    # Story 2.2: terraform-digitalocean is an **optional** adapter in v0.2 —
    # the realm plane stays operational with only `local-noop` registered;
    # degrading the supervisor on a missing DO token would make loopback-only
    # dev environments perpetually unhealthy. Story 5.1 may promote
    # `terraform-digitalocean` to `required: true` once mesh bootstrap lands.
    # The probe remains toothless beyond the non-empty `_ADAPTERS` check — a
    # richer dry-run probe is deferred (see deferred-work.md).
    if not _ADAPTERS:
        return False, "no adapters registered"
    return True, None


# Story 3.2 AC 8: REGISTRY consensus wiring is intentionally unchanged — the
# debate-loop readiness still rides on `graph_compiled` / `consensus_engine`.
# Story 3.3 AC 7: `realtime_channel` added between `consensus_engine` and
# `semantic_cache` so operators see Canvas wiring before future-state deps.
# Story 2.1 AC 6: `realm_manager` added between `realtime_channel` and
# `semantic_cache`. SCHEMA_VERSION intentionally NOT bumped — see the block
# comment above `SCHEMA_VERSION = 3` for the full rationale.
REGISTRY: list[DependencyCheck] = [
    DependencyCheck("graph_compiled", True, _probe_graph_compiled),
    DependencyCheck("consensus_engine", True, _probe_graph_compiled),
    DependencyCheck("realtime_channel", True, _probe_realtime_channel),
    DependencyCheck("realm_manager", True, _probe_realm_manager),
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


def _iso_now() -> str:
    """ISO-8601 UTC timestamp with a trailing `Z`.

    Shared helper used by the `/health` payload, the Story 3.3 realtime
    envelope (`_send_envelope`), and the Story 2.1 spin job state machine
    so every outbound timestamp uses the same format.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        timestamp=_iso_now(),
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


# --- Realm spin (Story 2.1) --------------------------------------------------
#
# Canvas + agent-wrapper HTTP surface for Private Realm provisioning (Epic 2).
# Ships:
#   - closed `SpinError.code` envelope shape for every non-2xx path;
#   - `SpinRequest` / `SpinResponse` / `SpinJob` Pydantic v2 models with
#     `ConfigDict(extra="forbid")` so unknown keys 400 early;
#   - `SpinPhase = validating -> provisioning -> ready | failed` state
#     machine with terminal-phase immutability guarded by `_update_job`;
#   - `RealmAdapter` Protocol seam + `LocalNoopAdapter` v0.1 adapter; Story
#     2.2 drops `TerraformAdapter` into `_ADAPTERS`, Story 2.3 wraps the
#     `provision` call with default-deny egress policy application;
#   - `_SPIN_JOBS` / `_JOB_BY_REALM` in-process registries (same multi-worker
#     caveat as `_CONNECTIONS` — Redis / Postgres is a documented follow-up);
#   - `POST /realms/spin` + `GET /realms/{job_id}` routes. Structured errors
#     are emitted via `JSONResponse(..., content=SpinError(...).model_dump())`
#     so the envelope shape is invariant across every 4xx / 5xx branch
#     (`HTTPException` wraps content in `{"detail": ...}` and is NOT used).
#
# Out of scope for 2.1 (explicit follow-ups tracked in the story file):
#   - `DELETE /realms/{job_id}` cancellation (adapter-level cleanup — 2.2).
#   - WS streaming of `realm.spin.phase` via `broadcast_event` (requires a
#     SCHEMA_VERSION bump; deferred until canvas UX needs push progress).
#   - Multi-worker / persistent job storage (Redis / Postgres).
#   - Authentication on `/realms/*` (loopback-only in v0.1).


SpinPhase = Literal["validating", "provisioning", "ready", "failed"]

# v0.1 closed enum of `SpinError.code` values. Adding a new code is an
# additive change and MUST be documented in docs/reference/supervisor-api.md
# in the same PR. Frontend-only codes (`network_error`, `bad_response`,
# `poll_timeout`) live in `frontend/lib/dirijor-api.ts` and are NOT part of
# this backend enum — see the JSDoc at the top of that module.
#
# The closed enum is enforced at runtime three ways:
#   1. `SpinError.code` is typed `SpinErrorCode` (Pydantic rejects anything
#      outside the `Literal`).
#   2. `SpinValidationError.__init__` asserts `code in _SPIN_ERROR_CODES`.
#   3. `_SPIN_ERROR_CODES` is derived from `SpinErrorCode` via `get_args`
#      so the tuple and the Literal cannot drift.
SpinErrorCode = Literal[
    "validation_failed",
    "invalid_realm_id",
    "adapter_unknown",
    "realm_id_conflict",
    "realm_manager_unavailable",
    "job_not_found",
    "adapter_error",
    "internal",
    "terraform_init_failed",
    "terraform_validate_failed",
    "terraform_plan_failed",
    "terraform_apply_failed",
    "terraform_destroy_failed",
    "terraform_command_timeout",
    "adapter_credentials_missing",
    "destroy_invalid_state",
    "destroy_already_requested",
]
_SPIN_ERROR_CODES: tuple[str, ...] = get_args(SpinErrorCode)

# Module constant — monkeypatched to `0.01` in the lifecycle test so the
# bounded poll loop resolves in < 0.3s. In production, 0.5s gives the canvas
# visible `validating -> provisioning -> ready` transitions under the noop
# adapter without a real IaC backend.
PROVISION_DELAY_S = 0.5

_TERMINAL_PHASES: tuple[SpinPhase, ...] = ("ready", "failed")

# Serialize DELETE /realms/{job_id} accept paths per job_id so two concurrent
# requests cannot both pass the destroy_requested_at guard before either stamps it.
_destroy_route_registry_lock = asyncio.Lock()
_destroy_route_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def _destroy_route_gate(job_id: str):
    async with _destroy_route_registry_lock:
        if job_id not in _destroy_route_locks:
            _destroy_route_locks[job_id] = asyncio.Lock()
        lock = _destroy_route_locks[job_id]
    async with lock:
        yield


class SpinError(BaseModel):
    """Canonical non-2xx envelope on every spin HTTP path.

    `code` is drawn from the closed `SpinErrorCode` `Literal` (Pydantic
    rejects any other value at validation time — the closed enum is
    enforced, not just documented). `message` is human-readable. `details`
    is an open map (e.g. `supported_adapters` on `adapter_unknown`,
    `existing_job_id` on `realm_id_conflict`, `exc_type` +
    `traceback_preview` on `adapter_error`) and is coerced through
    `jsonable_encoder` so adapter-supplied non-JSON-primitive values
    (datetime, set, bytes, custom objects) do not 500 the response
    serializer and break the closed envelope contract.
    """

    model_config = ConfigDict(extra="forbid")

    code: SpinErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("details", mode="before")
    @classmethod
    def _coerce_details(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError(
                f"SpinError.details must be a dict, got {type(value).__name__}"
            )
        return jsonable_encoder(value)


class SpinRequest(BaseModel):
    """`POST /realms/spin` request body.

    `realm_description` is required. `adapter_hint` defaults to the
    `local-noop` adapter when omitted (see `_resolve_adapter`). `realm_id`
    is server-minted with a `realm-<uuid12>` prefix when omitted;
    otherwise it must match `^[a-zA-Z0-9_-]{1,64}$` (same grammar as the
    WS `_REALM_ID_RE` from Story 3.3). `agent_count` is bounded to
    `[1, 50]` so obvious misuse fails validation before the adapter runs.
    """

    model_config = ConfigDict(extra="forbid")

    realm_description: str = Field(min_length=1, max_length=2000)
    adapter_hint: str | None = None
    realm_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    agent_count: int = Field(default=3, ge=1, le=50)

    @field_validator("realm_description")
    @classmethod
    def _description_not_whitespace_only(cls, value: str) -> str:
        # Pydantic's `min_length=1` counts raw characters, so `"   "` or
        # `"\n"` pass and produce a meaningless job description. Strip-test
        # here so the caller sees a structured `validation_failed` envelope
        # (via the RequestValidationError handler below) instead of a
        # blank-description job landing in the registry.
        if not value.strip():
            raise ValueError(
                "realm_description must contain at least one non-whitespace character"
            )
        return value


class SpinResponse(BaseModel):
    """`POST /realms/spin` 202 response body.

    Strict shape (AC 1): `job_id`, `realm_id`, `phase`, `adapter`,
    `created_at`, `status_url`, `schema_version`. The initial `phase` is
    ALWAYS `"validating"` — phase progression requires a subsequent poll
    of `GET /realms/{job_id}`.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    realm_id: str
    phase: SpinPhase
    adapter: str
    created_at: str
    status_url: str
    schema_version: int


class SpinJob(BaseModel):
    """Full lifecycle state of a spin job, returned by `GET /realms/{job_id}`.

    `outputs` is `{}` on every non-terminal poll and populated only when
    `phase == "ready"`. `error` is `null` on every non-`failed` poll and
    populated on terminal `failed`. `updated_at` advances monotonically on
    every phase transition (guarded by `_update_job`).
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    realm_id: str
    phase: SpinPhase
    adapter: str
    created_at: str
    updated_at: str
    realm_description: str
    agent_count: int
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: SpinError | None = None
    schema_version: int


# --- Realm adapter seam ------------------------------------------------------


class SpinValidationError(Exception):
    """Raised by an adapter's `validate` method when the request is rejected
    for adapter-specific reasons. The runner converts this into a terminal
    `failed` phase with a `SpinError(code=<exc.code>, ...)` attached.

    `code` is asserted against the closed `_SPIN_ERROR_CODES` enum at
    construction time so an adapter that invents a new code (e.g.
    "quota_exceeded") fails loudly in tests instead of silently
    propagating onto the wire and breaking the documented contract.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in _SPIN_ERROR_CODES:
            raise ValueError(
                f"SpinValidationError.code {code!r} not in closed enum "
                f"{_SPIN_ERROR_CODES}"
            )
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class RealmAdapter(Protocol):
    """Typed structural seam for realm-provisioning adapters.

    Story 2.2 will register `TerraformAdapter`; Story 2.3 wraps the
    `provision` call with default-deny egress policy application. The
    registry (`_ADAPTERS`) is closed in v0.1 — future stories extend it
    via a module-level `register_adapter(name, instance)` call at import
    time (explicitly NOT a runtime env-var / plugin-loader mechanism).
    """

    name: str

    async def validate(self, req: SpinRequest) -> None: ...

    async def provision(
        self, req: SpinRequest, job: SpinJob
    ) -> dict[str, Any]: ...

    async def destroy(self, job: SpinJob) -> None: ...


class LocalNoopAdapter:
    """v0.1 no-op adapter — validates `agent_count`, sleeps
    `PROVISION_DELAY_S`, returns a synthetic `noop://` mesh endpoint.
    Intentionally trivial so Story 2.1 can ship the contract without a
    real IaC backend; Story 2.2 replaces it with `TerraformAdapter`.
    """

    name = "local-noop"

    async def validate(self, req: SpinRequest) -> None:
        if not (1 <= req.agent_count <= 50):
            raise SpinValidationError(
                code="validation_failed",
                message="agent_count must be in [1, 50]",
                details={"field": "agent_count", "given": req.agent_count},
            )

    async def provision(
        self, req: SpinRequest, job: SpinJob
    ) -> dict[str, Any]:
        await asyncio.sleep(PROVISION_DELAY_S)
        return {
            "mesh_endpoint": f"noop://{job.realm_id}",
            "adapter": self.name,
            "agent_count": req.agent_count,
        }

    async def destroy(self, job: SpinJob) -> None:
        """LocalNoop has no real resources to destroy; returns silently so
        the DELETE path is uniform across adapters."""
        return


# --- Terraform adapter (Story 2.2) -------------------------------------------
#
# The real subprocess runner is NEVER instantiated under pytest — every Story
# 2.2 test builds a `TerraformAdapter` with a stub runner. This keeps the
# test suite hermetic (no terraform binary on CI, no DO token, no network)
# and deterministic. See `test_spin_terraform_lifecycle_progresses_to_ready`
# for the canonical stub shape.
#
# TODO(6.1): OTel spans around provision/destroy subprocess calls.


@dataclass(frozen=True)
class CompletedRun:
    """Result of one terraform subprocess invocation."""

    exit_code: int
    stdout: str
    stderr: str
    duration_s: float


class TerraformRunner(Protocol):
    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> CompletedRun: ...


class _AsyncSubprocessTerraformRunner:
    """Default `TerraformRunner` — wraps `asyncio.create_subprocess_exec`."""

    def __init__(self, binary: str) -> None:
        self._binary = binary

    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> CompletedRun:
        proc = await asyncio.create_subprocess_exec(
            self._binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        t0 = time.monotonic()
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            raise
        duration_s = time.monotonic() - t0
        out = (
            stdout_b.decode(errors="replace")
            if stdout_b
            else ""
        )
        err = (
            stderr_b.decode(errors="replace")
            if stderr_b
            else ""
        )
        code = proc.returncode if proc.returncode is not None else -1
        return CompletedRun(
            exit_code=code, stdout=out, stderr=err, duration_s=duration_s
        )


def _default_env_provider() -> Mapping[str, str]:
    """Shallow env slice for terraform — re-read DO token every call (never cache)."""
    token = os.environ.get("DIGITALOCEAN_TOKEN", "").strip()
    out: dict[str, str] = {
        "TF_IN_AUTOMATION": "1",
        "TF_INPUT": "0",
    }
    if token:
        out["DIGITALOCEAN_TOKEN"] = token
        out["TF_VAR_do_token"] = token
    if "HOME" in os.environ:
        out["HOME"] = os.environ["HOME"]
    if "PATH" in os.environ:
        out["PATH"] = os.environ["PATH"]
    return out


_DO_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"do_pat_[A-Za-z0-9]{64}"), "do_pat_<REDACTED>"),
    (re.compile(r"do_v1_[A-Za-z0-9]{64}"), "do_v1_<REDACTED>"),
    (re.compile(r"DIGITALOCEAN_TOKEN=\S+"), "DIGITALOCEAN_TOKEN=<REDACTED>"),
    (re.compile(r'"token"\s*:\s*"[^"]+"'), '"token": "<REDACTED>"'),
)


def _scrub_secrets(text: str) -> str:
    out = text
    for pat, repl in _DO_SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def _terraform_workspace_root() -> Path:
    raw = os.environ.get("DIRIJOR_TERRAFORM_WORKSPACE_ROOT", "").strip()
    if raw:
        return Path(raw)
    return Path(tempfile.gettempdir()) / "dirijor" / "terraform-workspaces"


def _resolve_terraform_binary() -> str:
    return os.environ.get("DIRIJOR_TERRAFORM_BINARY", "terraform").strip() or "terraform"


class TerraformAdapter:
    """Concrete DigitalOcean VPC provisioning via terraform CLI."""

    name = "terraform-digitalocean"

    def __init__(
        self,
        *,
        workspace_root: Path,
        binary: str = "terraform",
        cmd_timeout_s: float = 300.0,
        module_source: Path | None = None,
        subprocess_runner: TerraformRunner | None = None,
        env_provider: Callable[[], Mapping[str, str]] = _default_env_provider,
    ) -> None:
        self._workspace_root = workspace_root
        self._binary = binary
        raw_timeout = os.environ.get("DIRIJOR_TERRAFORM_CMD_TIMEOUT_S", "").strip()
        if raw_timeout:
            try:
                self._cmd_timeout_s = float(raw_timeout)
            except ValueError:
                self._cmd_timeout_s = float(cmd_timeout_s)
        else:
            self._cmd_timeout_s = float(cmd_timeout_s)
        repo_root = Path(__file__).resolve().parent.parent.parent
        self._module_source = module_source or (
            repo_root / "terraform" / "modules" / "private-realm"
        )
        self._runner = subprocess_runner or _AsyncSubprocessTerraformRunner(binary)
        self._env_provider = env_provider

    def _ws_for(self, realm_id: str) -> Path:
        ws = self._workspace_root / realm_id
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    def _copy_module(self, ws: Path) -> None:
        if not self._module_source.is_dir():
            raise SpinValidationError(
                code="internal",
                message=f"terraform module missing at {self._module_source}",
                details={"path": str(self._module_source)},
            )
        # Flat copy — not a symlink — so destroy does not touch the repo tree.
        for child in ws.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                shutil.rmtree(child)
        shutil.copytree(
            self._module_source, ws, dirs_exist_ok=True, symlinks=False
        )

    def _write_tfvars(self, ws: Path, req: SpinRequest, realm_id: str) -> None:
        payload = {
            "realm_name": realm_id,
            "agent_count": req.agent_count,
            "cloud_provider": "digitalocean",
        }
        tfvars_path = ws / "terraform.tfvars.json"
        tfvars_path.write_text(
            json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _merge_env(self) -> dict[str, str]:
        base = dict(self._env_provider())
        return {**dict(os.environ), **base}

    async def _run_step(
        self,
        *,
        job: SpinJob,
        step: str,
        args: list[str],
        cwd: Path,
        env: dict[str, str],
    ) -> CompletedRun:
        logger.info(
            "realm.terraform.%s.start" % step,
            extra={
                "event": f"realm.terraform.{step}.start",
                "job_id": job.job_id,
                "realm_id": job.realm_id,
                "step": step,
            },
        )
        t0 = time.monotonic()
        try:
            run = await self._runner.run(
                args,
                cwd=cwd,
                env=env,
                timeout_s=self._cmd_timeout_s,
            )
        except asyncio.TimeoutError:
            dur = time.monotonic() - t0
            logger.info(
                "realm.terraform.%s.done" % step,
                extra={
                    "event": f"realm.terraform.{step}.done",
                    "job_id": job.job_id,
                    "realm_id": job.realm_id,
                    "step": step,
                    "duration_s": round(dur, 3),
                    "exit_code": -1,
                },
            )
            raise SpinValidationError(
                code="terraform_command_timeout",
                message=f"terraform {step} exceeded {self._cmd_timeout_s}s timeout",
                details={
                    "step": step,
                    "timeout_s": self._cmd_timeout_s,
                },
            ) from None

        dur = time.monotonic() - t0
        preview = _scrub_secrets(run.stderr[:500])
        log_extra = {
            "event": f"realm.terraform.{step}.done",
            "job_id": job.job_id,
            "realm_id": job.realm_id,
            "step": step,
            "duration_s": round(dur, 3),
            "exit_code": run.exit_code,
        }
        if run.exit_code != 0:
            log_extra["stderr_preview"] = preview
        logger.info("realm.terraform.%s.done" % step, extra=log_extra)
        return run

    async def validate(self, req: SpinRequest) -> None:
        token = os.environ.get("DIGITALOCEAN_TOKEN", "").strip()
        if not token:
            raise SpinValidationError(
                code="adapter_credentials_missing",
                message="DIGITALOCEAN_TOKEN is not set or empty",
                details={},
            )

    async def provision(self, req: SpinRequest, job: SpinJob) -> dict[str, Any]:
        await self.validate(req)
        ws = self._ws_for(job.realm_id)
        self._copy_module(ws)
        self._write_tfvars(ws, req, job.realm_id)
        env = self._merge_env()

        r_init = await self._run_step(
            job=job,
            step="init",
            args=["init", "-input=false", "-no-color"],
            cwd=ws,
            env=env,
        )
        if r_init.exit_code != 0:
            prev = _scrub_secrets(r_init.stderr[:500])
            raise SpinValidationError(
                code="terraform_init_failed",
                message=f"terraform init exited {r_init.exit_code} at step 'init'",
                details={
                    "step": "init",
                    "exit_code": r_init.exit_code,
                    "stderr_preview": prev,
                },
            )

        r_val = await self._run_step(
            job=job,
            step="validate",
            args=["validate", "-no-color"],
            cwd=ws,
            env=env,
        )
        if r_val.exit_code != 0:
            prev = _scrub_secrets(r_val.stderr[:500])
            raise SpinValidationError(
                code="terraform_validate_failed",
                message=f"terraform validate exited {r_val.exit_code} at step 'validate'",
                details={
                    "step": "validate",
                    "exit_code": r_val.exit_code,
                    "stderr_preview": prev,
                },
            )

        r_plan = await self._run_step(
            job=job,
            step="plan",
            args=[
                "plan",
                "-input=false",
                "-no-color",
                "-var-file=terraform.tfvars.json",
                "-out=tfplan.binary",
            ],
            cwd=ws,
            env=env,
        )
        if r_plan.exit_code != 0:
            prev = _scrub_secrets(r_plan.stderr[:500])
            raise SpinValidationError(
                code="terraform_plan_failed",
                message=f"terraform plan exited {r_plan.exit_code} at step 'plan'",
                details={
                    "step": "plan",
                    "exit_code": r_plan.exit_code,
                    "stderr_preview": prev,
                },
            )

        r_apply = await self._run_step(
            job=job,
            step="apply",
            args=[
                "apply",
                "-input=false",
                "-auto-approve",
                "-no-color",
                "tfplan.binary",
            ],
            cwd=ws,
            env=env,
        )
        if r_apply.exit_code != 0:
            prev = _scrub_secrets(r_apply.stderr[:500])
            raise SpinValidationError(
                code="terraform_apply_failed",
                message=(
                    "partial apply — call DELETE /realms/"
                    f"{job.job_id} to clean up"
                ),
                details={
                    "step": "apply",
                    "exit_code": r_apply.exit_code,
                    "stderr_preview": prev,
                    "partial_apply": True,
                },
            )

        r_out = await self._run_step(
            job=job,
            step="output",
            args=["output", "-json", "-no-color"],
            cwd=ws,
            env=env,
        )
        if r_out.exit_code != 0:
            prev = _scrub_secrets(r_out.stderr[:500])
            raise SpinValidationError(
                code="terraform_apply_failed",
                message=(
                    "partial apply — call DELETE /realms/"
                    f"{job.job_id} to clean up"
                ),
                details={
                    "step": "apply",
                    "exit_code": r_out.exit_code,
                    "stderr_preview": prev,
                    "partial_apply": True,
                    "reason": "terraform_output_failed",
                },
            )

        try:
            raw_outputs: dict[str, Any] = json.loads(r_out.stdout)
        except json.JSONDecodeError as exc:
            raise SpinValidationError(
                code="terraform_apply_failed",
                message=f"terraform output JSON parse failed: {exc}",
                details={
                    "step": "apply",
                    "reason": "terraform_output_malformed",
                    "stderr_preview": _scrub_secrets(r_out.stderr[:500]),
                },
            ) from exc

        vpc_block = raw_outputs.get("realm_vpc_id")
        if not isinstance(vpc_block, dict) or "value" not in vpc_block:
            raise SpinValidationError(
                code="terraform_apply_failed",
                message="terraform output missing realm_vpc_id.value",
                details={
                    "step": "apply",
                    "reason": "terraform_output_malformed",
                },
            )

        vpc_id = vpc_block["value"]
        if not isinstance(vpc_id, str) or not vpc_id:
            raise SpinValidationError(
                code="terraform_apply_failed",
                message="terraform output realm_vpc_id is unusable",
                details={
                    "step": "apply",
                    "reason": "terraform_output_malformed",
                },
            )

        ip_block = raw_outputs.get("realm_vpc_ip_range")
        ip_val = None
        if isinstance(ip_block, dict) and "value" in ip_block:
            ip_val = ip_block["value"]

        plan_path = ws / "tfplan.binary"
        digest = ""
        if plan_path.is_file():
            h = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            digest = f"sha256:{h}"

        return {
            "adapter": self.name,
            "agent_count": req.agent_count,
            "realm_vpc_id": vpc_id,
            "realm_vpc_ip_range": ip_val,
            "mesh_endpoint": f"tf://{vpc_id}",
            "tf_workspace": str(ws),
            "tf_plan_digest": digest,
        }

    async def destroy(self, job: SpinJob) -> None:
        ws_raw = job.outputs.get("tf_workspace")
        if not ws_raw:
            raise SpinValidationError(
                code="terraform_destroy_failed",
                message="job.outputs.tf_workspace missing — cannot destroy",
                details={"step": "destroy"},
            )
        ws = Path(str(ws_raw)).resolve()
        root = self._workspace_root.resolve()
        if not ws.is_dir():
            raise SpinValidationError(
                code="terraform_destroy_failed",
                message=f"workspace directory missing: {ws}",
                details={"step": "destroy"},
            )
        if not ws.is_relative_to(root):
            raise SpinValidationError(
                code="terraform_destroy_failed",
                message="job.outputs.tf_workspace escapes workspace root",
                details={"step": "destroy", "workspace_root": str(root)},
            )
        env = self._merge_env()
        run = await self._run_step(
            job=job,
            step="destroy",
            args=["destroy", "-auto-approve", "-input=false", "-no-color"],
            cwd=ws,
            env=env,
        )
        if run.exit_code != 0:
            prev = _scrub_secrets(run.stderr[:500])
            raise SpinValidationError(
                code="terraform_destroy_failed",
                message=f"terraform destroy exited {run.exit_code}",
                details={
                    "step": "destroy",
                    "exit_code": run.exit_code,
                    "stderr_preview": prev,
                },
            )
        keep = os.environ.get("DIRIJOR_TERRAFORM_KEEP_WORKSPACE_ON_DESTROY", "").strip()
        if keep != "1":
            try:
                shutil.rmtree(ws)
            except OSError as exc:
                logger.warning(
                    "realm.terraform.workspace_rmtree_failed",
                    extra={
                        "event": "realm.terraform.workspace_rmtree_failed",
                        "path": str(ws),
                        "exc_type": type(exc).__name__,
                    },
                )


def _build_terraform_adapter() -> TerraformAdapter | None:
    token = os.environ.get("DIGITALOCEAN_TOKEN", "").strip()
    binary = _resolve_terraform_binary()
    bin_path = Path(binary)
    has_bin = shutil.which(binary) is not None or bin_path.is_file()
    if not token:
        logger.info(
            "realm.terraform.adapter.skipped",
            extra={"reason": "DIGITALOCEAN_TOKEN unset or empty"},
        )
        return None
    if not has_bin:
        logger.info(
            "realm.terraform.adapter.skipped",
            extra={"reason": f"terraform binary not found: {binary!r}"},
        )
        return None
    adapter = TerraformAdapter(
        workspace_root=_terraform_workspace_root(),
        binary=binary,
    )
    logger.info(
        "realm.terraform.adapter.registered",
        extra={"adapter": adapter.name},
    )
    return adapter


# Story 2.3 will wrap `.provision` with a default-deny egress policy decorator.
_ADAPTERS: dict[str, RealmAdapter] = {
    LocalNoopAdapter.name: LocalNoopAdapter(),
}

_maybe_tf = _build_terraform_adapter()
if _maybe_tf is not None:
    _ADAPTERS[_maybe_tf.name] = _maybe_tf


# --- Job registry + state machine -------------------------------------------


# In-process only. Multi-replica deployment requires Redis / Postgres —
# flagged as a documented follow-up (same posture as `_CONNECTIONS`); do NOT
# pre-introduce a persistence layer without a dedicated story.
_SPIN_JOBS: dict[str, SpinJob] = {}

# Map `realm_id -> job_id` for ACTIVE (non-terminal) jobs only. Used by the
# 409 conflict check. Entries are removed when the job reaches `ready` or
# `failed` (guarded `.pop(..., None)` in the `finally:` block of
# `_run_spin_job`).
_JOB_BY_REALM: dict[str, str] = {}

# Strong references to running `_run_spin_job` tasks. `asyncio.create_task`
# returns a task that the event loop only holds a WEAK reference to (see
# the `asyncio.create_task` "Important" note — gotcha since Python 3.11),
# so the task can be garbage-collected mid-execution if the returned
# handle is dropped. Storing every live task here keeps them alive; the
# done-callback removes the entry so the set does not grow unboundedly.
_RUNNING_SPIN_TASKS: set[asyncio.Task] = set()

_RUNNING_DESTROY_TASKS: set[asyncio.Task] = set()


def _mint_realm_id() -> str:
    """Generate a server-side `realm_id` that matches `_REALM_ID_RE`."""
    return f"realm-{uuid.uuid4().hex[:12]}"


def _resolve_adapter(hint: str | None) -> RealmAdapter:
    """Resolve a registered adapter by hint; fall back to `local-noop`.

    Raises `KeyError(name)` if a non-None hint is supplied but not
    registered — the HTTP handler translates that into an `adapter_unknown`
    `SpinError`. Fail-fast on an unknown hint (not a silent default
    fallback) so misconfiguration surfaces immediately — mirrors the
    `broadcast_event` fail-fast pattern from Story 3.3's code-review patch.

    Note: `None` (omitted hint) defaults to `local-noop`, but an empty
    string `""` is treated as a user-supplied unknown hint and raises
    `KeyError("")` so a buggy client cannot silently coerce to the noop
    adapter via Python's truthiness on `hint or default`.
    """
    name = LocalNoopAdapter.name if hint is None else hint
    adapter = _ADAPTERS.get(name)
    if adapter is None:
        raise KeyError(name)
    return adapter


def _update_job(
    job: SpinJob,
    *,
    phase: SpinPhase,
    error: SpinError | None = None,
    outputs: dict[str, Any] | None = None,
) -> SpinJob:
    """Pure helper: advance a job's phase + `updated_at`, optionally attach
    `error` / `outputs`. Terminal phases (`ready`, `failed`) are immutable
    by contract — mutating one raises `RuntimeError` so regressions surface
    loudly in tests (AC 4).
    """
    if job.phase in _TERMINAL_PHASES:
        raise RuntimeError(
            f"_update_job: refusing to mutate terminal job "
            f"{job.job_id} (phase={job.phase})"
        )
    job.phase = phase
    job.updated_at = _iso_now()
    if error is not None:
        job.error = error
    if outputs is not None:
        job.outputs = outputs
    return job


def _mutate_outputs(
    job: SpinJob,
    *,
    _remove_keys: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    """Merge keys into `job.outputs` for `phase == ready` jobs only.

    Story 2.1 `_update_job` refuses terminal-phase mutation; destroy lifecycle
    patches outputs without touching `phase`.
    """
    if job.phase != "ready":
        raise RuntimeError(
            f"_mutate_outputs: job {job.job_id} phase is {job.phase!r}, expected 'ready'"
        )
    merged: dict[str, Any] = {**job.outputs, **kwargs}
    if _remove_keys:
        for k in _remove_keys:
            merged.pop(k, None)
    job.outputs = merged
    job.updated_at = _iso_now()


def _log_job_done(
    job: SpinJob, started_monotonic: float, error_code: str | None
) -> None:
    """Emit one `realm.spin.done` INFO line on any terminal transition."""
    logger.info(
        "realm.spin.done",
        extra={
            "event": "realm.spin.done",
            "job_id": job.job_id,
            "phase": job.phase,
            "duration_s": round(time.monotonic() - started_monotonic, 3),
            "error_code": error_code,
        },
    )


# TODO(6.1): wrap `_run_spin_job` in an OTel span once Story 6.1 lands.
async def _run_spin_job(
    job: SpinJob, req: SpinRequest, adapter: RealmAdapter
) -> None:
    """Deterministic phase machine: `validating -> provisioning -> ready|failed`.

    Exception routing:
      - `asyncio.CancelledError` is re-raised so cooperative cancellation
        (event-loop shutdown, TestClient teardown, uvicorn reload) works.
      - `SpinValidationError` from the adapter terminates the job with
        the adapter-reported `code`.
      - Any other exception raised inside an adapter call (`validate` or
        `provision`) surfaces as `code="adapter_error"`.
      - Any other exception raised OUTSIDE an adapter call (e.g. a future
        `_update_job` regression, logger misconfiguration) surfaces as
        `code="internal"`.
      - Registry cleanup (`_JOB_BY_REALM.pop`) and `_log_job_done` run in
        a `finally:` block so a realm_id is never permanently 409-locked
        on a recovery-path regression.

    The bounded (500-char) `traceback_preview` in `SpinError.details`
    caps response body size so operators can diagnose from
    `GET /realms/{job_id}` alone. It is NOT a secret-scrubber — if a
    secret appears in the exception message or final frames it will
    surface; callers relying on secret-safety must add scrubbing at the
    adapter boundary.
    """
    started = time.monotonic()
    terminal_code: str | None = None
    # `error_source` tracks the call that raised. Only an adapter call
    # produces `adapter_error`; everything else is `internal`. See the
    # docstring above for the full routing table.
    error_source: str = "pre-adapter"
    try:
        try:
            error_source = "adapter.validate"
            await adapter.validate(req)
        except SpinValidationError as exc:
            _update_job(
                job,
                phase="failed",
                error=SpinError(
                    code=exc.code,
                    message=exc.message,
                    details=exc.details,
                ),
            )
            terminal_code = exc.code
            return

        error_source = "post-validate"
        _update_job(job, phase="provisioning")

        error_source = "adapter.provision"
        try:
            outputs = await adapter.provision(req, job)
        except SpinValidationError as exc:
            _update_job(
                job,
                phase="failed",
                error=SpinError(
                    code=exc.code,
                    message=exc.message,
                    details=exc.details,
                ),
            )
            terminal_code = exc.code
            return
        if not isinstance(outputs, dict):
            # Keep `error_source == "adapter.provision"` so the outer
            # `except` attributes this to the adapter (adapter_error),
            # not to the post-provision code path (internal).
            raise RuntimeError(
                f"adapter {adapter.name!r}.provision returned "
                f"{type(outputs).__name__}, expected dict"
            )

        error_source = "post-provision"
        _update_job(job, phase="ready", outputs=outputs)
    except asyncio.CancelledError:
        # Cooperative cancellation: re-raise so the event loop can reap
        # the task. The `finally:` block still releases the realm_id so
        # a subsequent spin of the same realm_id is not 409-blocked.
        raise
    except Exception as exc:
        logger.exception(
            "realm.spin.crash",
            extra={
                "event": "realm.spin.crash",
                "job_id": job.job_id,
                "realm_id": job.realm_id,
                "adapter": adapter.name,
                "error_source": error_source,
            },
        )
        # Cap the preview to keep the response body small — NOT a
        # secret-scrubber; see the function docstring.
        tb_preview = traceback.format_exc()[-500:]
        code: SpinErrorCode = (
            "adapter_error" if error_source.startswith("adapter.") else "internal"
        )
        if job.phase not in _TERMINAL_PHASES:
            _update_job(
                job,
                phase="failed",
                error=SpinError(
                    code=code,
                    message=str(exc),
                    details={
                        "exc_type": type(exc).__name__,
                        "traceback_preview": tb_preview,
                    },
                ),
            )
            terminal_code = code
        # Deliberately do NOT re-raise for non-cancel exceptions —
        # propagating from a background task would orphan the job in a
        # non-terminal phase. The failure is now encoded in job state.
    finally:
        # Unconditional cleanup: even if `_update_job` / `logger.exception`
        # itself raised above, the realm_id must be released so the next
        # spin with the same realm_id is not permanently 409-locked.
        _JOB_BY_REALM.pop(job.realm_id, None)
        _log_job_done(job, started, terminal_code)


# TODO(6.1): wrap `_run_destroy_job` in an OTel span once Story 6.1 lands.
async def _run_destroy_job(job: SpinJob, adapter: RealmAdapter) -> None:
    """Background destroy runner — keeps `phase == ready`; mutates outputs only."""
    started = time.monotonic()
    try:
        await adapter.destroy(job)
    except asyncio.CancelledError:
        # Allow a subsequent DELETE to retry if the task was cancelled
        # mid-flight (tests / cooperative shutdown).
        _mutate_outputs(
            job,
            _remove_keys=frozenset({"destroy_requested_at"}),
        )
        raise
    except SpinValidationError as exc:
        _mutate_outputs(
            job,
            destroyed=False,
            destroy_error={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )
        logger.warning(
            "realm.spin.destroy_failed",
            extra={
                "event": "realm.spin.destroy_failed",
                "job_id": job.job_id,
                "realm_id": job.realm_id,
                "duration_s": round(time.monotonic() - started, 3),
                "code": exc.code,
            },
        )
        return
    except Exception as exc:
        _mutate_outputs(
            job,
            destroyed=False,
            destroy_error={
                "code": "terraform_destroy_failed",
                "message": str(exc),
                "details": {"exc_type": type(exc).__name__},
            },
        )
        logger.warning(
            "realm.spin.destroy_failed",
            extra={
                "event": "realm.spin.destroy_failed",
                "job_id": job.job_id,
                "realm_id": job.realm_id,
                "duration_s": round(time.monotonic() - started, 3),
            },
        )
        return

    destroyed_at = _iso_now()
    _mutate_outputs(job, destroyed=True, destroyed_at=destroyed_at)
    logger.info(
        "realm.spin.destroyed",
        extra={
            "event": "realm.spin.destroyed",
            "job_id": job.job_id,
            "realm_id": job.realm_id,
            "duration_s": round(time.monotonic() - started, 3),
        },
    )


# --- HTTP routes -------------------------------------------------------------


def _spin_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Emit a `SpinError` `JSONResponse`.

    `HTTPException` is NOT used here because its default body shape is
    `{"detail": ...}`, which would violate the closed-envelope contract
    (AC 2). Every 4xx / 5xx path MUST route through this helper.
    """
    payload = SpinError(
        code=code, message=message, details=details or {}
    ).model_dump()
    return JSONResponse(status_code=status_code, content=payload)


@app.post(
    "/realms/spin",
    response_model=SpinResponse,
    status_code=202,
    responses={
        400: {
            "model": SpinError,
            "description": "Validation or adapter lookup failure.",
        },
        409: {
            "model": SpinError,
            "description": "A non-terminal job already holds this realm_id.",
        },
        503: {
            "model": SpinError,
            "description": "Realm manager readiness probe reports not-ready.",
        },
    },
)
async def spin_realm(req: SpinRequest) -> Any:
    """Accept a realm spin intent, enqueue a background job, return 202.

    Validation order (actual runtime order; AC 2 codes map as described):
      1. FastAPI runs Pydantic validation on `SpinRequest` BEFORE the
         handler body. The `RequestValidationError` handler installed at
         module scope translates those 422s into 400 + `SpinError` with
         `code="invalid_realm_id"` for `realm_id` pattern/length
         violations and `code="validation_failed"` for everything else
         (description length, whitespace-only, `agent_count` bounds,
         unknown keys via `extra="forbid"`).
      2. `realm_manager` readiness probe → 503 on degraded.
      3. Adapter resolution → 400 `adapter_unknown` on unregistered hint
         (including the empty-string case — see `_resolve_adapter`).
      4. Conflict check → 409 on an active job for the same `realm_id`.
      5. Mint job, register, fire background task, return 202.

    The handler no longer re-checks `realm_id` against `_REALM_ID_RE`
    because Pydantic + the validation-error handler cover that path
    completely; a separate guard would be dead code.
    """
    ready, detail = _probe_realm_manager()
    if not ready:
        return _spin_error_response(
            503,
            "realm_manager_unavailable",
            detail or "realm_manager is not ready",
        )

    try:
        adapter = _resolve_adapter(req.adapter_hint)
    except KeyError:
        return _spin_error_response(
            400,
            "adapter_unknown",
            f"adapter {req.adapter_hint!r} is not registered",
            {"supported_adapters": sorted(_ADAPTERS.keys())},
        )

    realm_id = req.realm_id or _mint_realm_id()

    existing_job_id = _JOB_BY_REALM.get(realm_id)
    if existing_job_id is not None:
        return _spin_error_response(
            409,
            "realm_id_conflict",
            f"realm_id {realm_id!r} already has an active spin job",
            {"existing_job_id": existing_job_id},
        )

    job_id = str(uuid.uuid4())
    now = _iso_now()
    job = SpinJob(
        job_id=job_id,
        realm_id=realm_id,
        phase="validating",
        adapter=adapter.name,
        created_at=now,
        updated_at=now,
        realm_description=req.realm_description,
        agent_count=req.agent_count,
        outputs={},
        error=None,
        schema_version=SCHEMA_VERSION,
    )
    _SPIN_JOBS[job_id] = job
    _JOB_BY_REALM[realm_id] = job_id

    logger.info(
        "realm.spin.accept",
        extra={
            "event": "realm.spin.accept",
            "job_id": job_id,
            "realm_id": realm_id,
            "adapter": adapter.name,
        },
    )

    # Store a strong reference so the event loop cannot GC the task
    # mid-execution. `discard` is used as the done-callback so the set
    # cannot leak entries across the process lifetime.
    task = asyncio.create_task(_run_spin_job(job, req, adapter))
    _RUNNING_SPIN_TASKS.add(task)
    task.add_done_callback(_RUNNING_SPIN_TASKS.discard)

    return SpinResponse(
        job_id=job_id,
        realm_id=realm_id,
        phase="validating",
        adapter=adapter.name,
        created_at=now,
        status_url=f"/realms/{job_id}",
        schema_version=SCHEMA_VERSION,
    )


@app.get(
    "/realms/{job_id}",
    response_model=SpinJob,
    responses={404: {"model": SpinError}},
)
async def get_realm_job(job_id: str) -> Any:
    """Return the current lifecycle state of a spin job, or 404."""
    job = _SPIN_JOBS.get(job_id)
    if job is None:
        return _spin_error_response(
            404,
            "job_not_found",
            f"no spin job with id {job_id!r} is registered",
            {"job_id": job_id},
        )
    return job


@app.delete(
    "/realms/{job_id}",
    responses={
        202: {
            "model": SpinJob,
            "description": "Destroy accepted; poll GET /realms/{job_id} for completion.",
        },
        204: {"description": "Already destroyed (idempotent no-op)."},
        404: {"model": SpinError},
        409: {"model": SpinError},
    },
)
async def delete_realm_job_route(job_id: str) -> Any:
    """Request asynchronous realm teardown; observe completion via GET poll."""
    async with _destroy_route_gate(job_id):
        job = _SPIN_JOBS.get(job_id)
        if job is None:
            return _spin_error_response(
                404,
                "job_not_found",
                f"no spin job with id {job_id!r} is registered",
                {"job_id": job_id},
            )

        if job.outputs.get("destroyed") is True:
            return Response(status_code=204)

        if job.phase != "ready":
            return _spin_error_response(
                409,
                "destroy_invalid_state",
                (
                    f"job {job_id} phase {job.phase!r} is not destroyable "
                    "(v0.2 requires phase='ready')"
                ),
                {"current_phase": job.phase},
            )

        if job.outputs.get("destroy_requested_at") and not job.outputs.get(
            "destroyed"
        ):
            return _spin_error_response(
                409,
                "destroy_already_requested",
                f"job {job_id} already has an active destroy task",
                {"destroy_requested_at": job.outputs["destroy_requested_at"]},
            )

        adapter = _ADAPTERS.get(job.adapter)
        if adapter is None:
            return _spin_error_response(
                500,
                "internal",
                f"adapter {job.adapter!r} is not registered (job registry drift)",
                {"job_id": job_id, "adapter": job.adapter},
            )

        _mutate_outputs(
            job,
            destroy_requested_at=_iso_now(),
            destroyed=False,
        )

        logger.info(
            "realm.spin.destroy.accept",
            extra={
                "event": "realm.spin.destroy.accept",
                "job_id": job.job_id,
                "realm_id": job.realm_id,
                "adapter": job.adapter,
            },
        )

        task = asyncio.create_task(_run_destroy_job(job, adapter))
        _RUNNING_DESTROY_TASKS.add(task)
        task.add_done_callback(_RUNNING_DESTROY_TASKS.discard)

        return JSONResponse(
            status_code=202,
            content=jsonable_encoder(job),
        )


# String-prefix match on request.url.path; scoped to the Story 2.1
# endpoints so the Story 3.2 /consensus surface keeps its default
# Pydantic 422 body (tests in that block rely on it).
_SPIN_PATH_PREFIX = "/realms/"

# Pydantic v2 error `type` values that map to the closed
# `invalid_realm_id` code when they fire on the `realm_id` field.
_REALM_ID_ERROR_TYPES = frozenset(
    {
        "string_pattern_mismatch",
        "string_too_long",
        "string_too_short",
        "string_type",
    }
)


def _classify_validation_error(
    errors: list[dict[str, Any]],
) -> SpinErrorCode:
    """Map a Pydantic v2 validation-error batch to the closed SpinError
    enum. If any error targets `realm_id` with a string-shape failure,
    the whole batch is classified as `invalid_realm_id`; otherwise
    `validation_failed` covers everything else (length, whitespace,
    agent_count bounds, unknown keys via `extra="forbid"`)."""
    for err in errors:
        loc = err.get("loc") or ()
        if not loc:
            continue
        # For POST body validation, `loc` is `("body", <field>, ...)`.
        # The field name is the first non-"body" element.
        field_loc = tuple(part for part in loc if part != "body")
        if field_loc and field_loc[0] == "realm_id":
            err_type = str(err.get("type", ""))
            if err_type in _REALM_ID_ERROR_TYPES:
                return "invalid_realm_id"
    return "validation_failed"


@app.exception_handler(RequestValidationError)
async def _spin_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Translate Pydantic's default 422 into 400 + `SpinError` envelope
    on the Story 2.1 `/realms/*` surface (AC 2).

    Non-spin endpoints keep FastAPI's default 422 `{"detail": [...]}`
    body so the Story 3.2 `/consensus` tests (which accept the default
    shape) are unaffected.

    Pydantic-level triggers that now surface as `SpinError`:
      - empty / missing / oversized / whitespace-only `realm_description`
        → `code="validation_failed"`
      - out-of-range `agent_count` (via `ge=1`, `le=50`)
        → `code="validation_failed"`
      - unknown keys (via `ConfigDict(extra="forbid")`)
        → `code="validation_failed"`
      - malformed `realm_id` (pattern/length)
        → `code="invalid_realm_id"`
    """
    if not request.url.path.startswith(_SPIN_PATH_PREFIX):
        # Preserve FastAPI's default for non-spin endpoints.
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(exc.errors())},
        )

    errors = list(exc.errors())
    code = _classify_validation_error(errors)
    first_msg = errors[0].get("msg", "request body failed validation") if errors else (
        "request body failed validation"
    )
    details = {
        "errors": jsonable_encoder(
            [
                {
                    "loc": list(e.get("loc", ())),
                    "type": e.get("type", ""),
                    "msg": e.get("msg", ""),
                }
                for e in errors
            ]
        )
    }
    return _spin_error_response(400, code, str(first_msg), details)


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
# TODO(refactor): supervisor.py > 2000 lines post-Story 2.2; split into
# consensus.py + realtime.py + spin.py + terraform_adapter.py when Story 4.2
# or 6.1 land. Do NOT pre-split — a refactor mid-story adds risk; the split
# is a dedicated follow-up.


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
        "ts": _iso_now(),
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
