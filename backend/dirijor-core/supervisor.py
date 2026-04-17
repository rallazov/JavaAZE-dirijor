# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Dirijor Supervisor – LangGraph Multi-Agent Consensus Brain
#
# Contract / schema discipline (Story 3.1):
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

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TypedDict

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

logger = logging.getLogger("dirijor.supervisor")

# --- Service identity (single source of truth) -------------------------------

SERVICE_NAME = "dirijor-supervisor"
SERVICE_VERSION = "0.1.0"
SCHEMA_VERSION = 1
STARTED_AT = time.monotonic()
STARTUP_GRACE_S = 1.0

# --- LangGraph Consensus Workflow --------------------------------------------


class AgentState(TypedDict):
    messages: list
    consensus_score: float
    verified_facts: list


def consensus_node(state: AgentState):
    # 3+ agent debate loop until >= 0.95 agreement -- placeholder for Story 3.2.
    # Verified Semantic Cache bypass (Qdrant) lands in Story 4.1.
    state["consensus_score"] = 0.97
    return state


_graph_compile_error: str | None = None
try:
    _workflow = StateGraph(AgentState)
    _workflow.add_node("consensus", consensus_node)
    _workflow.set_entry_point("consensus")
    _workflow.add_edge("consensus", END)
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


# --- Pydantic response models (contract surface) -----------------------------


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


@app.post("/consensus")
def run_consensus(query: str = ""):
    # Placeholder debate loop — real multi-agent consensus lands in Story 3.2.
    # AC 4 contract: the response body MUST expose exactly the v0.1 top-level
    # keys (`messages`, `consensus_score`, `verified_facts`) — no additive
    # fields, even on the degraded path. Operators who need the failure reason
    # poll `GET /health`, where `graph_compiled.detail` carries the exception
    # string. HTTP 503 is the only degraded-state signal on this endpoint.
    if graph is None:
        return JSONResponse(
            status_code=503,
            content={
                "messages": [query] if query else [],
                "consensus_score": 0.0,
                "verified_facts": [],
            },
        )
    result = graph.invoke(
        {
            "messages": [query],
            "consensus_score": 0.0,
            "verified_facts": [],
        }
    )
    return result
