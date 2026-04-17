# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Tests for Story 3.1 — Supervisor hardening & health endpoints.

All tests exercise the in-process FastAPI app; no network, no port binding.
The degraded-path test monkeypatches a probe on the module-level REGISTRY and
restores it automatically via pytest's monkeypatch fixture — no mutating
public API is shipped just for tests (AC 6, Dev Notes → Testing requirements).
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

import supervisor


client = TestClient(supervisor.app)


# --- AC 1 --------------------------------------------------------------------


def test_root_shape():
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()

    expected_top_level = {
        "service",
        "version",
        "schema_version",
        "status",
        "consensus_engine",
        "dependencies",
        "uptime_s",
    }
    assert expected_top_level.issubset(body.keys()), body

    # v0.1 superset invariants (AC 4)
    assert body["service"] == "dirijor-supervisor"
    assert body["version"] == supervisor.SERVICE_VERSION
    assert body["schema_version"] == supervisor.SCHEMA_VERSION

    # Every declared dependency shows up with the canonical entry shape.
    declared_names = {dep.name for dep in supervisor.REGISTRY}
    assert set(body["dependencies"].keys()) == declared_names
    for entry in body["dependencies"].values():
        assert set(entry.keys()) == {"ready", "required", "detail"}


def test_root_status_operational_when_ready():
    response = client.get("/")
    body = response.json()
    assert body["status"] == "operational"
    assert body["consensus_engine"] == "ready"


# --- AC 2 --------------------------------------------------------------------


def test_health_ok_when_ready():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()

    expected_top_level = {
        "status",
        "checks",
        "version",
        "schema_version",
        "uptime_s",
        "timestamp",
    }
    assert expected_top_level.issubset(body.keys()), body
    assert body["status"] == "ok"
    # timestamp is ISO-8601 ending in Z (UTC)
    assert body["timestamp"].endswith("Z")

    declared_names = {dep.name for dep in supervisor.REGISTRY}
    assert set(body["checks"].keys()) == declared_names


def test_health_503_when_required_dep_degraded(monkeypatch):
    """Flip one required dep to not-ready via the public registry — the body
    shape must stay identical and the HTTP code must flip to 503 (AC 2)."""
    # Push uptime past STARTUP_GRACE_S so the status aggregator resolves to
    # "degraded" (not "starting") deterministically.
    monkeypatch.setattr(
        supervisor, "STARTED_AT", time.monotonic() - (supervisor.STARTUP_GRACE_S + 5.0)
    )
    degraded = [
        supervisor.DependencyCheck(
            name="graph_compiled",
            required=True,
            probe=lambda: (False, "forced not ready for test"),
        ),
        supervisor.DependencyCheck(
            name="consensus_engine",
            required=True,
            probe=lambda: (False, "forced not ready for test"),
        ),
        supervisor.DependencyCheck(
            name="semantic_cache",
            required=False,
            probe=lambda: (False, "planned — see Story 4.1"),
        ),
        supervisor.DependencyCheck(
            name="mesh",
            required=False,
            probe=lambda: (False, "planned — see Story 5.1"),
        ),
    ]
    monkeypatch.setattr(supervisor, "REGISTRY", degraded)

    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()

    # Body shape is identical to the 200 path.
    expected_top_level = {
        "status",
        "checks",
        "version",
        "schema_version",
        "uptime_s",
        "timestamp",
    }
    assert expected_top_level.issubset(body.keys()), body
    assert body["status"] == "degraded"
    assert body["checks"]["graph_compiled"]["ready"] is False
    assert body["checks"]["graph_compiled"]["detail"] == "forced not ready for test"


def test_health_never_500s_when_probe_raises(monkeypatch):
    """A buggy probe must degrade gracefully — `/health` must return a shaped
    503, never propagate an exception (AC 2: "never raises")."""
    monkeypatch.setattr(
        supervisor, "STARTED_AT", time.monotonic() - (supervisor.STARTUP_GRACE_S + 5.0)
    )

    def _boom() -> tuple[bool, str | None]:
        raise RuntimeError("simulated probe failure")

    patched = [
        supervisor.DependencyCheck("graph_compiled", True, _boom),
        supervisor.DependencyCheck("consensus_engine", True, _boom),
        supervisor.DependencyCheck("semantic_cache", False, lambda: (False, "planned")),
        supervisor.DependencyCheck("mesh", False, lambda: (False, "planned")),
    ]
    monkeypatch.setattr(supervisor, "REGISTRY", patched)

    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["graph_compiled"]["ready"] is False
    assert "probe raised" in body["checks"]["graph_compiled"]["detail"]


# --- AC 3 --------------------------------------------------------------------


def test_registry_contains_required_dependencies():
    names = {dep.name: dep for dep in supervisor.REGISTRY}
    assert {"graph_compiled", "consensus_engine", "semantic_cache", "mesh"} <= set(
        names
    )
    assert names["graph_compiled"].required is True
    assert names["consensus_engine"].required is True
    assert names["semantic_cache"].required is False
    assert names["mesh"].required is False

    checks = supervisor.resolve_readiness()
    assert checks["semantic_cache"]["detail"] == "planned — see Story 4.1"
    assert checks["mesh"]["detail"] == "planned — see Story 5.1"


# --- AC 4 --------------------------------------------------------------------


_CONSENSUS_V01_KEYS = {"messages", "consensus_score", "verified_facts"}


def test_consensus_smoke():
    response = client.post("/consensus", params={"query": "is the sky blue?"})
    assert response.status_code == 200
    body = response.json()
    # v0.1 top-level contract must be preserved exactly (AC 4 — "no regression").
    # Exact-set equality (not subset) guards against additive keys leaking in.
    assert set(body.keys()) == _CONSENSUS_V01_KEYS


def test_consensus_degraded_keeps_v01_key_set(monkeypatch):
    """AC 4 regression guard for the `graph is None` branch.

    If LangGraph compilation fails, `/consensus` returns HTTP 503 — but the
    body MUST still contain exactly `messages`, `consensus_score`,
    `verified_facts` and nothing else, so strict v0.1 parsers do not break.
    """
    monkeypatch.setattr(supervisor, "graph", None)
    response = client.post("/consensus", params={"query": "any"})
    assert response.status_code == 503
    body = response.json()
    assert set(body.keys()) == _CONSENSUS_V01_KEYS
    assert body["messages"] == ["any"]
    assert body["consensus_score"] == 0.0
    assert body["verified_facts"] == []


def test_root_preserves_v01_superset():
    """`/` must keep the v0.1 keys docker-compose, README, and the agent
    wrapper read (AC 4)."""
    response = client.get("/")
    body = response.json()
    for legacy_key in ("service", "version", "status", "consensus_engine"):
        assert legacy_key in body


# --- AC 5 / AC 6 -------------------------------------------------------------


def test_schema_version_pinned():
    """Loud regression guard — bumping SCHEMA_VERSION requires deliberately
    updating this test AND README sample payloads (AC 5)."""
    assert supervisor.SCHEMA_VERSION == 1
    assert supervisor.SERVICE_VERSION == "0.1.0"
