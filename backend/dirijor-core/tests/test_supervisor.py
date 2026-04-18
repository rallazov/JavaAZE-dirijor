# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Tests for the Dirijor Supervisor HTTP surface.

Originally authored for Story 3.1 (structured `/` + `/health`); extended for
Story 3.2 (real `/consensus` debate loop, SCHEMA v2 additive response).

All tests exercise the in-process FastAPI app; no network, no port binding.
The degraded-path tests monkeypatch module-level state (REGISTRY / graph)
and restore it automatically via pytest's monkeypatch fixture — no mutating
public API is shipped just for tests (Story 3.1 AC 6, Story 3.2 AC 7).
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

import supervisor


client = TestClient(supervisor.app)


# --- AC 1 (Story 3.1) --------------------------------------------------------


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


# --- AC 2 (Story 3.1) --------------------------------------------------------


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


# --- AC 3 (Story 3.1) --------------------------------------------------------


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


# --- AC 4 (Story 3.1) + Story 3.2 AC 6 --------------------------------------


_CONSENSUS_V01_KEYS = {"messages", "consensus_score", "verified_facts"}


def test_consensus_smoke():
    """Story 3.2 AC 6 relaxation: the 200 path is now a SCHEMA v2 SUPERSET
    of the v0.1 key-set. The v0.1 keys MUST still be present (AC 4
    invariant) — `issubset`, not exact equality."""
    response = client.post("/consensus", params={"query": "is the sky blue?"})
    assert response.status_code == 200
    body = response.json()
    assert _CONSENSUS_V01_KEYS.issubset(body.keys()), body


def test_consensus_degraded_keeps_v01_key_set(monkeypatch):
    """AC 4 regression guard for the `graph is None` branch — UNCHANGED by
    Story 3.2.

    If LangGraph compilation fails, `/consensus` returns HTTP 503 — the
    body MUST still contain EXACTLY `messages`, `consensus_score`,
    `verified_facts` and nothing else, so strict v0.1 parsers do not break.
    Story 3.2's additive v2 keys are INTENTIONALLY not added to this branch.
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


# --- Story 3.2 AC 5 (schema version bump) -----------------------------------


def test_schema_version_pinned():
    """Loud regression guard — bumping SCHEMA_VERSION requires deliberately
    updating this test AND README sample payloads (Story 3.1 AC 5,
    Story 3.2 AC 5)."""
    assert supervisor.SCHEMA_VERSION == 2
    assert supervisor.SERVICE_VERSION == "0.1.0"


def test_schema_version_is_2():
    """Explicit belt-and-braces pin from Story 3.2 AC 7. If a future story
    bumps SCHEMA_VERSION again, BOTH this test and `test_schema_version_pinned`
    must be updated together so the intent is impossible to miss in diff review."""
    assert supervisor.SCHEMA_VERSION == 2


# --- Story 3.2 AC 1–4, AC 7 (new debate-loop coverage) ----------------------


_CONSENSUS_V2_KEYS = _CONSENSUS_V01_KEYS | {
    "decision",
    "votes",
    "termination_reason",
    "rounds",
    "threshold",
}


def test_consensus_reaches_threshold_one_round():
    """AC 4 — unanimous opinions → threshold reached in a single round."""
    response = client.post(
        "/consensus",
        json={
            "query": "Is the staging DB patched?",
            "opinions": [
                {"agent_id": "grok", "opinion": "yes", "confidence": 0.9},
                {"agent_id": "harper", "opinion": "yes", "confidence": 0.95},
                {"agent_id": "claude", "opinion": "yes", "confidence": 0.99},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert _CONSENSUS_V2_KEYS.issubset(body.keys())
    assert body["consensus_score"] == 1.0
    assert body["rounds"] == 1
    assert body["termination_reason"] == "threshold_reached"
    assert body["decision"] == "yes"
    assert body["threshold"] == 0.95
    assert body["messages"] == ["Is the staging DB patched?"]
    assert body["verified_facts"] == []
    assert len(body["votes"]) == 3
    assert {v["round"] for v in body["votes"]} == {1}


def test_consensus_no_decision_when_below_threshold():
    """AC 2 — below-threshold is a NORMAL outcome, not an error.

    3 distinct opinions, max_rounds=2, default threshold=0.95 → loop exhausts
    rounds, decision is None, HTTP 200 (not 503), consensus_score reflects
    the true final score (not a dummy 0.97).
    """
    response = client.post(
        "/consensus",
        json={
            "opinions": [
                {"agent_id": "a", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "b", "opinion": "no", "confidence": 1.0},
                {"agent_id": "c", "opinion": "maybe", "confidence": 1.0},
            ],
            "max_rounds": 2,
            "threshold": 0.95,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] is None
    assert body["consensus_score"] < 0.95
    assert body["termination_reason"] == "max_rounds_exhausted"
    assert body["rounds"] == 2
    assert body["threshold"] == 0.95


def test_consensus_single_opinion_shortcut():
    """AC 3 — 1 opinion short-circuits the loop."""
    response = client.post(
        "/consensus",
        json={
            "opinions": [
                {"agent_id": "solo", "opinion": "ship it", "confidence": 1.0},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rounds"] == 1
    assert body["termination_reason"] == "single_opinion_shortcut"
    assert body["decision"] == "ship it"
    assert body["consensus_score"] == 1.0


def test_consensus_no_opinions_no_query():
    """AC 3 — empty body → `no_opinions` branch, score 0.0, decision null."""
    response = client.post("/consensus", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] is None
    assert body["termination_reason"] == "no_opinions"
    assert body["consensus_score"] == 0.0
    assert body["rounds"] == 1
    assert body["votes"] == []
    assert body["messages"] == []


def test_consensus_custom_threshold():
    """AC 1 — per-request `threshold` override lets a 2-of-3 majority
    (score ≈ 0.667) cross the bar immediately."""
    response = client.post(
        "/consensus",
        json={
            "opinions": [
                {"agent_id": "a", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "b", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "c", "opinion": "no", "confidence": 1.0},
            ],
            "threshold": 0.5,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["termination_reason"] == "threshold_reached"
    assert body["rounds"] == 1
    assert body["decision"] == "yes"
    assert body["threshold"] == 0.5
    assert body["consensus_score"] >= 0.5


def test_consensus_votes_are_ordered_and_numbered():
    """AC 7 — `votes[i].round` is monotonically non-decreasing and every
    round index from 1..rounds appears (no gaps, no out-of-order entries)."""
    response = client.post(
        "/consensus",
        json={
            "opinions": [
                {"agent_id": "a", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "b", "opinion": "no", "confidence": 1.0},
                {"agent_id": "c", "opinion": "maybe", "confidence": 1.0},
            ],
            "max_rounds": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    rounds_seen = [v["round"] for v in body["votes"]]

    assert rounds_seen == sorted(rounds_seen), rounds_seen
    assert set(rounds_seen) == set(range(1, body["rounds"] + 1))


def test_consensus_v01_keys_still_present_for_query_param_path():
    """AC 6 — the legacy `?query=foo` path still returns the v0.1 keys
    alongside the new SCHEMA v2 keys (superset, not exact equality)."""
    response = client.post("/consensus", params={"query": "foo"})
    assert response.status_code == 200
    body = response.json()
    assert _CONSENSUS_V01_KEYS.issubset(body.keys())
    assert _CONSENSUS_V2_KEYS.issubset(body.keys())
    assert body["messages"] == ["foo"]


# --- Pure-function coverage for the deterministic scorer --------------------


def test_consensus_auto_assigns_agent_ids_when_omitted():
    """Code-review follow-up (Finding 1 — agent_id): `AgentOpinion.agent_id`
    is optional. Posting opinions without `agent_id` (or with an empty
    string) must NOT 422 — the handler fills deterministic `agent-N` ids
    in submission order.
    """
    response = client.post(
        "/consensus",
        json={
            "opinions": [
                {"opinion": "yes"},
                {"opinion": "yes"},
                {"opinion": "yes"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [v["agent_id"] for v in body["votes"]] == ["agent-0", "agent-1", "agent-2"]
    assert body["termination_reason"] == "threshold_reached"
    assert body["decision"] == "yes"


def test_score_round_is_deterministic_first_seen_tiebreak():
    """Direct unit test on `score_round` — when two groups tie in size, the
    FIRST-seen group wins (stable ordering). This keeps response bodies
    diff-stable across platforms and Python dict iteration orders.
    """
    opinions = [
        supervisor.AgentOpinion(agent_id="a", opinion="Yes", confidence=1.0),
        supervisor.AgentOpinion(agent_id="b", opinion="no", confidence=1.0),
        supervisor.AgentOpinion(agent_id="c", opinion="YES", confidence=1.0),
        supervisor.AgentOpinion(agent_id="d", opinion="No", confidence=1.0),
    ]
    score, majority = supervisor.score_round(opinions)
    assert score == 0.5
    # "Yes" was the first opinion in the (tied) largest group — and its
    # ORIGINAL casing is returned, not the normalized key.
    assert majority == "Yes"
