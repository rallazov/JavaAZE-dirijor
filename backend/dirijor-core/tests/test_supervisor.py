# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Tests for the Dirijor Supervisor HTTP + WebSocket surface.

Originally authored for Story 3.1 (structured `/` + `/health`); extended for
Story 3.2 (real `/consensus` debate loop, SCHEMA v2 additive response);
further extended for Story 3.3 (WebSocket `/ws/realm/{realm_id}` channel,
`broadcast_event` API, realtime readiness entry, SCHEMA v3 additive bump).

All tests exercise the in-process FastAPI app; no network, no port binding.
The degraded-path tests monkeypatch module-level state (REGISTRY / graph /
HEARTBEAT_INTERVAL_S / _authorize_realm / _send_envelope) and restore it
automatically via pytest's monkeypatch fixture — no mutating public API is
shipped just for tests (Story 3.1 AC 6, Story 3.2 AC 7, Story 3.3 AC 8).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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
    assert {"graph_compiled", "consensus_engine", "semantic_cache", "anomaly_policy", "mesh"} <= set(
        names
    )
    assert names["graph_compiled"].required is True
    assert names["consensus_engine"].required is True
    assert names["semantic_cache"].required is False
    assert names["anomaly_policy"].required is False
    assert names["mesh"].required is False

    checks = supervisor.resolve_readiness()
    assert checks["semantic_cache"]["detail"] == "not configured"
    assert checks["mesh"]["ready"] is True
    assert "mesh bootstrap disabled" in (checks["mesh"]["detail"] or "")


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
    Story 3.2 AC 5, Story 3.3 AC 7, Story 2.2 AC 10)."""
    assert supervisor.SCHEMA_VERSION == 9
    assert supervisor.SERVICE_VERSION == "0.1.0"


def test_schema_version_is_9():
    """Explicit belt-and-braces pin — Story 7.2 bumped 8 → 9. If a future
    story bumps SCHEMA_VERSION again, BOTH this test and
    `test_schema_version_pinned` must be updated together."""
    assert supervisor.SCHEMA_VERSION == 9


# --- Story 3.2 AC 1–4, AC 7 (new debate-loop coverage) ----------------------


_CONSENSUS_V2_KEYS = _CONSENSUS_V01_KEYS | {
    "decision",
    "votes",
    "termination_reason",
    "rounds",
    "threshold",
    "semantic_cache_status",
    "semantic_cache_reason",
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
    assert body["semantic_cache_status"] == "skipped"
    assert body["semantic_cache_reason"] == "query_vector_missing"
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


# --- Story 3.3 — WebSocket channel, readiness, RootStatus.realtime ---------
#
# All WS tests use `TestClient(supervisor.app).websocket_connect(...)` — no
# port binding, no uvicorn boot. Broadcast-side orchestration uses
# `asyncio.run(...)` because Starlette's test-mode `WebSocket.send_json`
# pushes into thread-safe anyio memory streams; no app-loop binding required.


_WS_ENVELOPE_KEYS = {"type", "schema_version", "realm_id", "ts", "seq", "payload"}
_WS_SUPPORTED_TYPES = {
    "session.hello",
    "topology.delta",
    "metrics.update",
    "hitl.pending",
    "realm.mesh.state",
    "heartbeat",
    "session.bye",
}


def _drain_connections() -> None:
    """Reset the module-level registry between WS tests so an earlier test's
    half-collected session does not leak into a later assertion.

    `_CONNECTIONS` is legitimately shared state — we don't expose a
    `reset()` helper on the supervisor (tests MUST not drive production API
    surface), so we reach in defensively only here."""
    supervisor._CONNECTIONS.clear()
    supervisor._last_metrics_payload_sig.clear()


def _drain_ws_until_types(ws, types_ok: set[str], *, deadline_s: float = 2.0):
    """Receive frames until `type` is in `types_ok` (skips heartbeats, etc.)."""

    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        frame = ws.receive_json()
        if frame["type"] in types_ok:
            return frame
    raise AssertionError(f"timeout waiting for one of {types_ok!r}")


def test_ws_accepts_valid_realm_id():
    """AC 1 — 101 upgrade + first frame is the canonical `session.hello`
    envelope with `seq == 0` and all 5 payload keys present."""
    _drain_connections()
    with TestClient(supervisor.app) as local_client:
        with local_client.websocket_connect("/ws/realm/demo") as ws:
            hello = ws.receive_json()
    assert set(hello.keys()) == _WS_ENVELOPE_KEYS
    assert hello["type"] == "session.hello"
    assert hello["schema_version"] == supervisor.SCHEMA_VERSION
    assert hello["realm_id"] == "demo"
    assert hello["seq"] == 0
    assert hello["ts"].endswith("Z")

    payload = hello["payload"]
    assert set(payload.keys()) == {
        "service_version",
        "schema_version",
        "supported_event_types",
        "heartbeat_interval_s",
        "connection_id",
    }
    assert payload["service_version"] == supervisor.SERVICE_VERSION
    assert payload["schema_version"] == supervisor.SCHEMA_VERSION
    assert set(payload["supported_event_types"]) == _WS_SUPPORTED_TYPES
    assert payload["heartbeat_interval_s"] == supervisor.HEARTBEAT_INTERVAL_S
    # uuid4 strings are 36 chars with 4 dashes.
    assert len(payload["connection_id"]) == 36
    assert payload["connection_id"].count("-") == 4


def test_ws_rejects_missing_realm_id():
    """AC 1 — empty/whitespace realm_id fails regex → close 4401 BEFORE accept."""
    _drain_connections()
    with TestClient(supervisor.app) as local_client:
        # %20 decodes to a single space, which fails `^[a-zA-Z0-9_-]{1,64}$`.
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with local_client.websocket_connect("/ws/realm/%20"):
                pass
    assert exc_info.value.code == 4401


def test_ws_rejects_malformed_realm_id():
    """AC 1 — characters outside `[a-zA-Z0-9_-]` → close 4401."""
    _drain_connections()
    with TestClient(supervisor.app) as local_client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with local_client.websocket_connect("/ws/realm/bad.realm"):
                pass
    assert exc_info.value.code == 4401


def test_ws_rejects_forbidden_realm(monkeypatch):
    """AC 1 — `_authorize_realm` returning `(False, …)` → close 4403."""
    _drain_connections()
    monkeypatch.setattr(
        supervisor,
        "_authorize_realm",
        lambda realm_id: (False, "denied"),
    )
    with TestClient(supervisor.app) as local_client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with local_client.websocket_connect("/ws/realm/demo"):
                pass
    assert exc_info.value.code == 4403


def test_ws_metrics_update_after_session_hello():
    """Story 6.3 — Core-derived HUD arrives over `metrics.update` after connect."""
    _drain_connections()
    with TestClient(supervisor.app) as local_client:
        with local_client.websocket_connect("/ws/realm/hud-demo") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "session.hello"
            frame = _drain_ws_until_types(ws, {"metrics.update"}, deadline_s=2.0)
            assert frame["type"] == "metrics.update"
            pl = frame["payload"]
            assert "latencyMs" in pl
            assert "securityPosture" in pl
            assert "auditPreview" in pl
            assert "quarantinedAgentCount" in pl
            assert isinstance(pl["auditPreview"], list)
            assert isinstance(pl["quarantinedAgentCount"], int)


def test_ws_metrics_update_after_consensus_with_realm():
    """Story 6.3 — consensus with realm_id fans out a refreshed metrics frame."""
    _drain_connections()
    with TestClient(supervisor.app) as local_client:
        with local_client.websocket_connect("/ws/realm/metrics-realm") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "session.hello"
            _drain_ws_until_types(ws, {"metrics.update"}, deadline_s=2.0)
            response = local_client.post(
                "/consensus",
                json={"realm_id": "metrics-realm", "opinions": [{"opinion": "yes"}]},
            )
            assert response.status_code == 200, response.text
            frame = _drain_ws_until_types(ws, {"metrics.update"}, deadline_s=2.0)
            assert frame["payload"]["latencyMs"] >= 1


def test_ws_broadcast_reaches_only_matching_realm():
    """AC 2 — tenant isolation: `broadcast_event("A", …)` reaches A, not B.
    Also verifies monotonic `seq` per-session (A: 0=hello, N× `metrics.update`,
    then `topology.delta` at seq 1+N)."""
    _drain_connections()
    with TestClient(supervisor.app) as local_client:
        with local_client.websocket_connect("/ws/realm/A") as ws_a, \
             local_client.websocket_connect("/ws/realm/B") as ws_b:
            hello_a = ws_a.receive_json()
            hello_b = ws_b.receive_json()
            assert hello_a["type"] == "session.hello"
            assert hello_a["seq"] == 0
            assert hello_b["type"] == "session.hello"

            delivered = asyncio.run(
                supervisor.broadcast_event(
                    "A",
                    "topology.delta",
                    {"agents": [{"id": "x", "label": "x"}]},
                )
            )
            assert delivered == 1

            # Story 6.3 may emit multiple `metrics.update` frames (initial + ≤1 Hz
            # reconcile) before the test's `topology.delta` — drain all of them.
            metrics_seen = 0
            frame = ws_a.receive_json()
            while frame["type"] == "metrics.update":
                metrics_seen += 1
                frame = ws_a.receive_json()
            assert frame["type"] == "topology.delta"
            assert frame["realm_id"] == "A"
            assert frame["seq"] == 1 + metrics_seen  # hello=0, then N metrics, then delta
            assert frame["payload"]["agents"][0]["id"] == "x"

            # B must NOT have received the frame. Starlette's test-mode WS
            # close-drains pending messages on `__exit__` — if a frame had
            # leaked here we would see it next. We assert by draining and
            # ensuring no matching event_type was seen.
    assert supervisor._CONNECTIONS == {} or not supervisor._CONNECTIONS.get("A")


def test_ws_broadcast_rejects_unsupported_event_type():
    """AC 2 hardening (code-review patch) — `broadcast_event` fails fast
    on an unsupported `event_type`. A typo like 'topolgy.delta' must
    raise BEFORE any frame is sent, so downstream emitters (Story 4.x
    anomaly, 6.x HUD) cannot silently drift from `_SUPPORTED_EVENT_TYPES`
    without a SCHEMA_VERSION bump. The error message MUST name the bad
    value so the failure is debuggable from a single log line."""
    with pytest.raises(ValueError, match="topolgy.delta"):
        asyncio.run(supervisor.broadcast_event("demo", "topolgy.delta", {}))


def test_ws_heartbeat_emitted_on_idle(monkeypatch):
    """AC 3 — with HEARTBEAT_INTERVAL_S monkeypatched to 0.05s, at least one
    `heartbeat` envelope arrives within 0.5s of an idle connection."""
    _drain_connections()
    monkeypatch.setattr(supervisor, "HEARTBEAT_INTERVAL_S", 0.05)

    with TestClient(supervisor.app) as local_client:
        with local_client.websocket_connect("/ws/realm/demo") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "session.hello"

            heartbeat_seen = False
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                frame = ws.receive_json()
                if frame["type"] == "heartbeat":
                    assert frame["payload"] == {}
                    assert frame["realm_id"] == "demo"
                    assert frame["seq"] >= 1
                    heartbeat_seen = True
                    break
    assert heartbeat_seen


def test_ws_disconnect_cleans_up_registry():
    """AC 3 / route finally-block — after session context exits, the realm
    bucket is pruned (no leaked references in `_CONNECTIONS`)."""
    _drain_connections()
    realm = "cleanup-target"
    assert supervisor._CONNECTIONS.get(realm) is None

    with TestClient(supervisor.app) as local_client:
        with local_client.websocket_connect(f"/ws/realm/{realm}") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "session.hello"
            assert realm in supervisor._CONNECTIONS
            assert len(supervisor._CONNECTIONS[realm]) == 1

    # The route's finally-block runs asynchronously; give it up to 1s to
    # drain, mirroring the heartbeat-fixture bounded-poll pattern.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and supervisor._CONNECTIONS.get(realm):
        time.sleep(0.01)
    assert supervisor._CONNECTIONS.get(realm) is None


def test_ws_close_1011_on_send_failure(monkeypatch):
    """AC 3 — when an outbound send raises, `broadcast_event` evicts the
    session AND closes the underlying WebSocket with code 1011."""
    _drain_connections()
    original = supervisor._send_envelope
    call_count = {"n": 0}

    async def failing_send(session, type_, payload):
        call_count["n"] += 1
        if call_count["n"] == 1:
            await original(session, type_, payload)  # hello passes through
            return
        raise RuntimeError("simulated send failure")

    monkeypatch.setattr(supervisor, "_send_envelope", failing_send)
    monkeypatch.setattr(supervisor, "_ensure_metrics_reconcile_loop", lambda: None)

    async def _noop_metrics(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(supervisor, "emit_realm_metrics_update", _noop_metrics)

    with TestClient(supervisor.app) as local_client:
        with local_client.websocket_connect("/ws/realm/fail") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "session.hello"

            asyncio.run(
                supervisor.broadcast_event("fail", "topology.delta", {})
            )

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
    assert exc_info.value.code == 1011


def test_health_includes_realtime_channel_dep():
    """AC 7 — `/health.checks["realtime_channel"]` is required + ready."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "realtime_channel" in body["checks"]
    assert body["checks"]["realtime_channel"] == {
        "ready": True,
        "required": True,
        "detail": None,
    }


# --- Story 2.1 (Realm spin) -------------------------------------------------
#
# AC 8 coverage. 13 new cases live under this banner — do NOT split
# test_supervisor.py until the flat file crosses the documented threshold
# (Story 4.2 or 6.1, per the TODO comment in supervisor.py).
#
# The lifecycle + conflict tests share a fixture that speeds / slows the
# LocalNoopAdapter provision window so the sync `TestClient` + poll pattern
# is deterministic. See `test_spin_job_progresses_through_lifecycle` for
# the canonical async caveat comment.


_SPIN_RESPONSE_KEYS = {
    "job_id",
    "realm_id",
    "phase",
    "adapter",
    "created_at",
    "status_url",
    "schema_version",
}


@pytest.fixture(autouse=True)
def _drain_spin_jobs():
    """Reset the in-process spin registries between every test so one
    test's lingering job cannot trip a later test's conflict / lookup
    assertions. `autouse=True` — the fixture applies to all tests in
    this module (including pre-Story-2.1 tests, which do not touch the
    registries and so are unaffected). Per-test explicit
    `_clear_spin_state()` calls below are retained as cheap belt-and-
    suspenders and to keep the individual Story 2.1 tests self-documenting.
    """
    supervisor._SPIN_JOBS.clear()
    supervisor._JOB_BY_REALM.clear()
    supervisor._RUNNING_DESTROY_TASKS.clear()
    yield
    supervisor._SPIN_JOBS.clear()
    supervisor._JOB_BY_REALM.clear()
    supervisor._RUNNING_DESTROY_TASKS.clear()


def _clear_spin_state() -> None:
    supervisor._SPIN_JOBS.clear()
    supervisor._JOB_BY_REALM.clear()


def test_spin_accepts_valid_request_returns_202():
    """AC 1 — minimal valid body → 202 + strict SpinResponse key set
    + initial phase == 'validating'."""
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": "smoke test"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body.keys()) == _SPIN_RESPONSE_KEYS, body
    assert body["phase"] == "validating"
    assert body["adapter"] == "local-noop"
    assert body["schema_version"] == supervisor.SCHEMA_VERSION
    assert body["created_at"].endswith("Z")
    assert body["status_url"] == f"/realms/{body['job_id']}"
    assert supervisor._REALM_ID_RE.match(body["realm_id"])


def test_spin_echoes_caller_provided_realm_id():
    """AC 1 — a valid caller-supplied realm_id is echoed verbatim."""
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": "echo test", "realm_id": "demo-a"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["realm_id"] == "demo-a"


def test_spin_generates_realm_id_when_absent():
    """AC 1 — server-minted realm_id matches `_REALM_ID_RE` and starts
    with the documented `realm-` prefix."""
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": "auto-id"},
    )
    assert response.status_code == 202
    realm_id = response.json()["realm_id"]
    assert realm_id.startswith("realm-")
    assert supervisor._REALM_ID_RE.match(realm_id)


def test_spin_rejects_empty_description():
    """AC 2 — empty `realm_description` → 400 + SpinError(code="validation_failed").

    The `RequestValidationError` handler translates Pydantic's default
    422 into the closed `SpinError` envelope on `/realms/*` endpoints so
    the on-wire contract is invariant across every non-2xx path.
    """
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": ""},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert set(body.keys()) == {"code", "message", "details"}
    assert body["code"] == "validation_failed"


def test_spin_rejects_oversized_description():
    """AC 2 — 2001-char description → 400 + SpinError(code="validation_failed")."""
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": "x" * 2001},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "validation_failed"


def test_spin_rejects_whitespace_only_description():
    """AC 2 — whitespace-only `realm_description` (`"   "`, `"\\n"`) is
    stripped and rejected with 400 + SpinError(code="validation_failed")
    so a meaningless job cannot land in the registry."""
    _clear_spin_state()
    for payload in ("   ", "\n", "\t\t"):
        response = client.post(
            "/realms/spin",
            json={"realm_description": payload},
        )
        assert response.status_code == 400, response.text
        assert response.json()["code"] == "validation_failed"


def test_spin_rejects_invalid_realm_id():
    """AC 2 — `realm_id` with whitespace fails the regex pattern →
    400 + SpinError(code="invalid_realm_id")."""
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": "bad id", "realm_id": "bad id"},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "invalid_realm_id"


def test_spin_rejects_unknown_adapter():
    """AC 2 — unregistered adapter hint → 400 `adapter_unknown` with
    `details.supported_adapters` listing the registered names."""
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": "wrong adapter", "adapter_hint": "aws"},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "adapter_unknown"
    assert body["details"]["supported_adapters"] == ["local-noop"]


def test_spin_rejects_conflict_on_active_realm(monkeypatch):
    """AC 2 — back-to-back POSTs with the same `realm_id` → 409
    `realm_id_conflict` while the first job is still non-terminal.

    Uses a scoped `with TestClient(...) as local_client` so the ASGI
    lifespan portal stays alive across both POSTs — otherwise the
    ephemeral per-request portal cancels the background task between
    calls and `_JOB_BY_REALM` is released before the second POST lands.
    """
    _clear_spin_state()
    # Pin the provision window high so the first job stays in `provisioning`
    # across the second POST — otherwise the conflict check races the
    # background runner finishing and releasing `_JOB_BY_REALM`.
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 5.0)

    with TestClient(supervisor.app) as local_client:
        first = local_client.post(
            "/realms/spin",
            json={"realm_description": "first", "realm_id": "dup-realm"},
        )
        assert first.status_code == 202

        second = local_client.post(
            "/realms/spin",
            json={"realm_description": "second", "realm_id": "dup-realm"},
        )
        assert second.status_code == 409, second.text
        body = second.json()
        assert body["code"] == "realm_id_conflict"
        assert body["details"]["existing_job_id"] == first.json()["job_id"]

    # Drop the stuck job so the next test's registry starts clean.
    _clear_spin_state()


def test_spin_job_progresses_through_lifecycle(monkeypatch):
    # Known limitation: TestClient is sync. The background runner spawned
    # via asyncio.create_task only progresses between client.get() calls
    # on the shared event loop. The bounded time.sleep + client.get poll
    # below is the canonical pattern — do NOT rewrite as an async test
    # without also switching the whole suite to httpx.AsyncClient, which
    # is a separate (deferred) refactor tracked in Known follow-ups.
    #
    # The scoped `with TestClient(...) as local_client` block is load-bearing:
    # it opens the ASGI lifespan portal so the event loop stays alive across
    # every poll, keeping the asyncio.create_task(_run_spin_job) task runnable
    # between sync GETs. Without it, each request spins an ephemeral portal
    # and the background runner is cancelled mid-sleep.
    _clear_spin_state()
    # Longer provisioning window so the sync poll loop can reliably observe
    # the validating → provisioning transition; without this, the 10 µs-class
    # validate() + default noop provision complete before the first poll.
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.15)

    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={"realm_description": "lifecycle test"},
        )
        assert resp.status_code == 202
        post_body = resp.json()
        # AC 1 — the POST response itself carries the initial phase.
        assert post_body["phase"] == "validating"
        job_id = post_body["job_id"]
        created_at = post_body["created_at"]

        seen: list[str] = [post_body["phase"]]
        # AC 3 — `updated_at` advances monotonically on every phase
        # transition. Capture the first `updated_at` observed for each
        # phase so we can assert three distinct values
        # (validating → provisioning → ready).
        updated_at_by_phase: dict[str, str] = {}
        final_body: dict = {}
        for _ in range(400):  # max ~2s wall time @ 5ms/poll
            time.sleep(0.005)
            r = local_client.get(f"/realms/{job_id}")
            assert r.status_code == 200
            body = r.json()
            phase = body["phase"]
            if phase not in updated_at_by_phase:
                updated_at_by_phase[phase] = body["updated_at"]
            if seen[-1] != phase:
                seen.append(phase)
            final_body = body
            if phase in ("ready", "failed"):
                break

    assert final_body, "no final body captured"
    assert final_body["phase"] == "ready", final_body
    assert final_body["error"] is None
    assert final_body["outputs"]["mesh_endpoint"] == f"noop://{final_body['realm_id']}"
    assert final_body["outputs"]["adapter"] == "local-noop"
    assert final_body["updated_at"].endswith("Z")
    assert final_body["updated_at"] >= created_at  # monotonic advance
    # Full lifecycle: validating (from POST) → provisioning → ready.
    assert seen[0] == "validating"
    assert seen[-1] == "ready"
    assert "provisioning" in seen
    # AC 3 — three distinct `updated_at` values across the transitions.
    # validating `updated_at` from the POST response (not a subsequent
    # poll, because the background task advances the phase before the
    # first GET can observe it) plus provisioning / ready from the poll
    # loop. All three must be monotonically ordered by ISO-8601 string
    # comparison (safe because `_iso_now` pads to microseconds + `Z`).
    validating_updated_at = post_body["created_at"]
    provisioning_updated_at = updated_at_by_phase["provisioning"]
    ready_updated_at = updated_at_by_phase["ready"]
    assert validating_updated_at != provisioning_updated_at
    assert provisioning_updated_at != ready_updated_at
    assert validating_updated_at != ready_updated_at
    assert (
        validating_updated_at
        <= provisioning_updated_at
        <= ready_updated_at
    )


def test_spin_failure_surfaces_structured_error(monkeypatch):
    """AC 4 — an exception from `adapter.provision` terminates the job as
    `failed` with `error.code == 'adapter_error'` and a bounded
    `traceback_preview` attached."""
    _clear_spin_state()
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)

    async def _boom(req, job):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        supervisor._ADAPTERS["local-noop"], "provision", _boom
    )

    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={"realm_description": "fail me"},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        final_body: dict = {}
        for _ in range(200):
            time.sleep(0.01)
            r = local_client.get(f"/realms/{job_id}")
            assert r.status_code == 200
            final_body = r.json()
            if final_body["phase"] in ("ready", "failed"):
                break

    assert final_body["phase"] == "failed", final_body
    assert final_body["error"] is not None
    assert final_body["error"]["code"] == "adapter_error"
    assert final_body["error"]["message"] == "boom"
    assert final_body["error"]["details"]["exc_type"] == "RuntimeError"
    assert "traceback_preview" in final_body["error"]["details"]
    assert len(final_body["error"]["details"]["traceback_preview"]) <= 500
    assert final_body["outputs"] == {}


def test_get_realm_job_404_on_unknown_id():
    """AC 3 — unknown job_id returns 404 + the SpinError envelope."""
    _clear_spin_state()
    response = client.get("/realms/does-not-exist")
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["code"] == "job_not_found"
    assert body["details"]["job_id"] == "does-not-exist"


def test_health_includes_realm_manager_dep():
    """AC 6 — `/health.checks["realm_manager"]` is required + ready."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "realm_manager" in body["checks"]
    assert body["checks"]["realm_manager"] == {
        "ready": True,
        "required": True,
        "detail": None,
    }


# --- Story 2.1 code-review patches (2026-04-18) ------------------------------


def test_update_job_refuses_to_mutate_terminal_phase():
    """AC 4 — `_update_job` raises `RuntimeError` on any attempt to
    mutate a `ready` / `failed` job. Guards the documented terminal-
    phase immutability invariant so a future refactor that removes the
    assert is caught directly (not just via full-lifecycle post-conditions).
    """
    for terminal in ("ready", "failed"):
        job = supervisor.SpinJob(
            job_id="job-immutable-test",
            realm_id="realm-immutable",
            phase=terminal,
            adapter="local-noop",
            created_at="2026-04-18T00:00:00.000000Z",
            status_url="/realms/job-immutable-test",
            updated_at="2026-04-18T00:00:00.000000Z",
            realm_description="immutability test",
            agent_count=1,
            outputs={},
            error=None,
            schema_version=supervisor.SCHEMA_VERSION,
        )
        with pytest.raises(RuntimeError, match="refusing to mutate terminal"):
            supervisor._update_job(job, phase="provisioning")


def test_spin_rejects_503_when_realm_manager_unready(monkeypatch):
    """AC 2 — readiness registry reports `realm_manager` not-ready →
    503 + `SpinError(code="realm_manager_unavailable")` on POST /realms/spin.
    Exercised by zeroing `_ADAPTERS` so `_probe_realm_manager` returns
    `(False, "no adapters registered")`.
    """
    _clear_spin_state()
    monkeypatch.setattr(supervisor, "_ADAPTERS", {})
    response = client.post(
        "/realms/spin",
        json={"realm_description": "unready probe"},
    )
    assert response.status_code == 503, response.text
    body = response.json()
    assert set(body.keys()) == {"code", "message", "details"}
    assert body["code"] == "realm_manager_unavailable"
    # Per `_spin_error_response` contract: `details` is `{}` on this path
    # (the probe detail is already the human-readable message).
    assert body["details"] == {}


def test_spin_rejects_empty_adapter_hint_as_unknown():
    """AC 2 — explicit empty-string `adapter_hint` is NOT silently
    coerced to `local-noop`; the caller must see 400 `adapter_unknown`
    so a misconfigured client does not drift onto the noop adapter.
    """
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": "empty hint", "adapter_hint": ""},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "adapter_unknown"
    assert body["details"]["supported_adapters"] == ["local-noop"]


@pytest.mark.parametrize(
    ("agent_count", "expected_status"),
    [
        (0, 400),
        (1, 202),
        (50, 202),
        (51, 400),
    ],
)
def test_spin_agent_count_boundaries(agent_count, expected_status):
    """AC 2 — `agent_count ∈ [1, 50]` at the boundary. 0 and 51 produce
    400 + `validation_failed`; 1 and 50 produce 202 so the spec'd bounds
    cannot be silently loosened. A separate test covers non-integer
    payloads (`"3"`) below."""
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={
            "realm_description": f"boundary test {agent_count}",
            "agent_count": agent_count,
        },
    )
    assert response.status_code == expected_status, response.text
    if expected_status == 400:
        assert response.json()["code"] == "validation_failed"


def test_spin_rejects_non_integer_agent_count():
    """AC 2 — `agent_count` must be an int. Pydantic's default coercion
    would happily turn `"3"` into `3`; the test pins the expectation that
    non-integer JSON types fail validation (via `ConfigDict` strict-ish
    behavior over Pydantic v2) rather than silently coercing."""
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={
            "realm_description": "str agent_count",
            "agent_count": "three",
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "validation_failed"


def test_spin_rejects_unknown_keys_via_extra_forbid():
    """AC 2 — `SpinRequest.model_config = ConfigDict(extra="forbid")`
    rejects unknown keys. A refactor that flipped to `extra="ignore"`
    would silently loosen the documented "unknown keys rejected early"
    contract; this test pins the behavior.
    """
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={"realm_description": "bogus key", "bogus_key": 1},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "validation_failed"


def test_spin_error_rejects_unknown_code_at_construction():
    """Closed-enum enforcement — `SpinError(code="not_in_enum", ...)` is
    rejected by Pydantic because `SpinErrorCode` is a `Literal`. Pins
    the invariant documented in the `SpinError` docstring.
    """
    with pytest.raises(Exception):  # Pydantic's ValidationError subclass
        supervisor.SpinError(code="not_in_enum", message="nope", details={})


def test_spin_validation_error_rejects_unknown_code_at_construction():
    """Closed-enum enforcement — `SpinValidationError("quota_exceeded", ...)`
    must raise `ValueError` so a future adapter cannot smuggle a new
    code onto the wire without documenting it.
    """
    with pytest.raises(ValueError, match="not in closed enum"):
        supervisor.SpinValidationError("quota_exceeded", "nope")


def test_spin_running_task_set_is_released_after_terminal(monkeypatch):
    """P1 — `_RUNNING_SPIN_TASKS` holds a strong ref to the background
    task so it cannot be GC'd mid-execution; the done-callback releases
    the entry so the set does not leak entries across the process lifetime.
    """
    _clear_spin_state()
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)

    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={"realm_description": "task-set release"},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        for _ in range(200):
            time.sleep(0.01)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                break

    # After the task completes the done-callback must have fired,
    # releasing the strong reference so `_RUNNING_SPIN_TASKS` is empty
    # and the process doesn't accumulate task objects.
    assert supervisor._RUNNING_SPIN_TASKS == set()


def test_root_includes_realtime_block():
    """AC 7 — `GET /` body gains the additive `realtime` block."""
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert "realtime" in body
    assert set(body["realtime"].keys()) == {
        "connections",
        "heartbeat_interval_s",
        "schema_version",
    }
    assert body["realtime"]["schema_version"] == supervisor.SCHEMA_VERSION
    assert body["realtime"]["heartbeat_interval_s"] == supervisor.HEARTBEAT_INTERVAL_S
    assert body["realtime"]["connections"] >= 0

    # v0.1 superset invariant still holds (AC 9) — `realtime` is purely additive.
    for legacy_key in ("service", "version", "status", "consensus_engine"):
        assert legacy_key in body


# --- Story 2.2 (Terraform adapter) --------------------------------------------


def _tf_output_stdout() -> str:
    return json.dumps(
        {
            "realm_vpc_id": {
                "value": "d3b3a0c4-1234-5678-9abc-def012345678",
                "type": "string",
            },
            "realm_vpc_ip_range": {
                "value": "10.10.0.0/16",
                "type": "string",
            },
        }
    )


@dataclass
class _StubTerraformRunner:
    """Records terraform CLI calls; returns canned `CompletedRun` per subcommand."""

    calls: list[tuple[list[str], Path, tuple[str, ...]]] = field(
        default_factory=list
    )
    queue: dict[str, supervisor.CompletedRun] = field(default_factory=dict)
    raise_on: dict[str, BaseException] = field(default_factory=dict)

    async def run(self, args, *, cwd, env, timeout_s):
        env_keys = tuple(sorted(env.keys()))
        self.calls.append((list(args), cwd, env_keys))
        step = args[0] if args else ""
        if step in self.raise_on:
            raise self.raise_on[step]
        if step in self.queue:
            return self.queue[step]
        if step == "output":
            return supervisor.CompletedRun(0, _tf_output_stdout(), "", 0.01)
        if step == "plan" and cwd:
            (Path(cwd) / "tfplan.binary").write_bytes(b"plan-bytes-for-digest")
        return supervisor.CompletedRun(0, "", "", 0.01)


def _tf_env_provider() -> dict[str, str]:
    return {
        "DIGITALOCEAN_TOKEN": "do_pat_" + "0" * 64,
        "TF_VAR_do_token": "do_pat_" + "0" * 64,
        "TF_IN_AUTOMATION": "1",
        "TF_INPUT": "0",
        "HOME": "/tmp",
        "PATH": "/usr/bin",
    }


def test_terraform_adapter_registered_when_token_and_binary_present(monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    monkeypatch.setattr(supervisor.shutil, "which", lambda b: "/usr/local/bin/terraform")
    adapter = supervisor._build_terraform_adapter()
    assert adapter is not None
    assert adapter.name == "terraform-digitalocean"


def test_terraform_adapter_skipped_when_token_absent(monkeypatch):
    monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)
    monkeypatch.setattr(supervisor.shutil, "which", lambda b: "/usr/local/bin/terraform")
    assert supervisor._build_terraform_adapter() is None


def test_terraform_adapter_skipped_when_binary_missing(monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    monkeypatch.setattr(supervisor.shutil, "which", lambda b: None)
    monkeypatch.setenv("DIRIJOR_TERRAFORM_BINARY", "/nonexistent/terraform")
    assert supervisor._build_terraform_adapter() is None


def test_spin_terraform_adapter_accepts_and_returns_202(monkeypatch, tmp_path):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    response = client.post(
        "/realms/spin",
        json={
            "realm_description": "finance prod",
            "adapter_hint": "terraform-digitalocean",
            "agent_count": 3,
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["adapter"] == "terraform-digitalocean"
    assert body["schema_version"] == supervisor.SCHEMA_VERSION


def test_spin_terraform_lifecycle_progresses_to_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "finance prod",
                "adapter_hint": "terraform-digitalocean",
                "agent_count": 3,
            },
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            r = local_client.get(f"/realms/{job_id}")
            final = r.json()
            if final["phase"] in ("ready", "failed"):
                break
        assert final["phase"] == "ready"
        assert final["outputs"]["adapter"] == "terraform-digitalocean"
        assert final["outputs"]["mesh_endpoint"].startswith("tf://")
        assert final["outputs"]["realm_vpc_id"]
        assert isinstance(final["outputs"]["tf_workspace"], str)


def test_spin_terraform_invokes_commands_in_order(monkeypatch, tmp_path):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "order test",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        ws = tmp_path / resp.json()["realm_id"]
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                break
    expected = [
        ["init", "-input=false", "-no-color"],
        ["validate", "-no-color"],
        ["plan", "-input=false", "-no-color", "-var-file=terraform.tfvars.json", "-out=tfplan.binary"],
        ["apply", "-input=false", "-auto-approve", "-no-color", "tfplan.binary"],
        ["output", "-json", "-no-color"],
    ]
    assert [c[0] for c in stub.calls] == expected
    for args, cwd, env_keys in stub.calls:
        assert cwd == ws
        assert "DIGITALOCEAN_TOKEN" in env_keys


def test_spin_terraform_init_failure_surfaces_terraform_init_failed(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    stub.queue["init"] = supervisor.CompletedRun(1, "", "init failed hard", 0.01)
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "fail init",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["phase"] == "failed"
    assert final["error"]["code"] == "terraform_init_failed"
    assert final["error"]["details"]["step"] == "init"


def test_spin_terraform_validate_failure_surfaces_terraform_validate_failed(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    stub.queue["validate"] = supervisor.CompletedRun(1, "", "validate bad", 0.01)
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "fail val",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["error"]["code"] == "terraform_validate_failed"
    assert final["error"]["details"]["step"] == "validate"


def test_spin_terraform_plan_failure_surfaces_terraform_plan_failed(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    stub.queue["plan"] = supervisor.CompletedRun(1, "", "plan bad", 0.01)
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "fail plan",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["error"]["code"] == "terraform_plan_failed"
    assert final["error"]["details"]["step"] == "plan"


def test_spin_terraform_apply_failure_surfaces_terraform_apply_failed(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    stub.queue["apply"] = supervisor.CompletedRun(1, "", "apply bad", 0.01)
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "fail apply",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["error"]["code"] == "terraform_apply_failed"
    assert final["error"]["details"]["partial_apply"] is True
    assert "DELETE /realms/" in final["error"]["message"]


def test_spin_terraform_apply_failure_scrubs_do_pat_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    token = "do_pat_" + "a" * 64
    stub = _StubTerraformRunner()
    stub.queue["apply"] = supervisor.CompletedRun(
        1, "", f"leaked {token} in stderr", 0.01
    )
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "scrub test",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    preview = final["error"]["details"]["stderr_preview"]
    assert token not in preview
    assert "do_pat_<REDACTED>" in preview


def test_spin_terraform_command_timeout_surfaces_terraform_command_timeout(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    stub.raise_on["plan"] = TimeoutError()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "timeout",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["error"]["code"] == "terraform_command_timeout"
    assert final["error"]["details"]["step"] == "plan"
    assert final["error"]["details"]["timeout_s"] == tf._cmd_timeout_s


def test_spin_terraform_credentials_missing_at_validate_time_surfaces_adapter_credentials_missing(
    monkeypatch, tmp_path
):
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=supervisor._default_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "no creds",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["error"]["code"] == "adapter_credentials_missing"


def test_destroy_on_ready_job_returns_202_and_runs_terraform_destroy(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "destroy me",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] == "ready":
                break
        d = local_client.delete(f"/realms/{job_id}")
        assert d.status_code == 202
        assert d.json()["outputs"]["destroy_requested_at"]
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["outputs"].get("destroyed"):
                break
        assert body["outputs"]["destroyed"] is True
        assert body["outputs"]["destroyed_at"]
        destroy_calls = [c for c in stub.calls if c[0] and c[0][0] == "destroy"]
    assert destroy_calls, "expected terraform destroy"


def test_destroy_on_non_ready_job_returns_409_destroy_invalid_state(monkeypatch):
    _clear_spin_state()
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)

    async def _stall_validate(self, req: supervisor.SpinRequest) -> None:
        await asyncio.sleep(30.0)

    monkeypatch.setattr(supervisor.LocalNoopAdapter, "validate", _stall_validate)
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "slow",
                "adapter_hint": "local-noop",
            },
        )
        job_id = resp.json()["job_id"]
        del_resp = local_client.delete(f"/realms/{job_id}")
        assert del_resp.status_code == 409
        err = del_resp.json()
        assert err["code"] == "destroy_invalid_state"
        assert err["details"]["current_phase"] == "validating"


def test_destroy_idempotent_on_already_destroyed_returns_204(monkeypatch):
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={"realm_description": "noop destroy", "adapter_hint": "local-noop"},
        )
        job_id = resp.json()["job_id"]
        for _ in range(200):
            time.sleep(0.01)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] == "ready":
                break
        first = local_client.delete(f"/realms/{job_id}")
        assert first.status_code == 202
        for _ in range(200):
            time.sleep(0.01)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["outputs"].get("destroyed"):
                break
        second = local_client.delete(f"/realms/{job_id}")
        assert second.status_code == 204


def test_delete_realm_job_409_destroy_already_requested_injected():
    """Second DELETE while destroy is in flight → 409 destroy_already_requested."""
    _clear_spin_state()
    jid = str(uuid.uuid4())
    rid = "realm-409destroy"
    now = supervisor._iso_now()
    job = supervisor.SpinJob(
        job_id=jid,
        realm_id=rid,
        phase="ready",
        adapter="local-noop",
        created_at=now,
        status_url=f"/realms/{jid}",
        updated_at=now,
        realm_description="x",
        agent_count=1,
        outputs={"destroy_requested_at": now, "destroyed": False},
        error=None,
        schema_version=supervisor.SCHEMA_VERSION,
    )
    supervisor._SPIN_JOBS[jid] = job
    supervisor._JOB_BY_REALM[rid] = jid
    resp = client.delete(f"/realms/{jid}")
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "destroy_already_requested"


def test_delete_realm_job_500_when_adapter_not_registered():
    _clear_spin_state()
    jid = str(uuid.uuid4())
    rid = "realm-noadapter"
    now = supervisor._iso_now()
    job = supervisor.SpinJob(
        job_id=jid,
        realm_id=rid,
        phase="ready",
        adapter="not-registered-adapter-name",
        created_at=now,
        status_url=f"/realms/{jid}",
        updated_at=now,
        realm_description="x",
        agent_count=1,
        outputs={},
        error=None,
        schema_version=supervisor.SCHEMA_VERSION,
    )
    supervisor._SPIN_JOBS[jid] = job
    supervisor._JOB_BY_REALM[rid] = jid
    resp = client.delete(f"/realms/{jid}")
    assert resp.status_code == 500
    assert resp.json()["code"] == "internal"


def test_destroy_failure_surfaces_terraform_destroy_failed_in_outputs(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    stub.queue["destroy"] = supervisor.CompletedRun(1, "", "destroy failed", 0.01)
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "destroy fail",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] == "ready":
                break
        local_client.delete(f"/realms/{job_id}")
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            out = body.get("outputs") or {}
            if out.get("destroy_error"):
                final = body
                break
        assert final["outputs"]["destroy_error"]["code"] == "terraform_destroy_failed"


def test_spin_terraform_malformed_output_json_surfaces_terraform_apply_failed(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    stub.queue["output"] = supervisor.CompletedRun(0, "{not-json", "", 0.01)
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "bad output json",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["phase"] == "failed"
    assert final["error"]["code"] == "terraform_apply_failed"
    assert final["error"]["details"].get("reason") == "terraform_output_malformed"


def test_spin_terraform_output_step_nonzero_surfaces_terraform_apply_failed(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    stub.queue["output"] = supervisor.CompletedRun(1, "", "output cmd failed", 0.01)
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": tf,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "output nonzero",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["phase"] == "failed"
    assert final["error"]["code"] == "terraform_apply_failed"
    assert final["error"]["details"].get("reason") == "terraform_output_failed"


# --- Story 2.3 (default-deny egress) ------------------------------------------


def test_terraform_write_tfvars_allow_public_egress_default_false(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("DIRIJOR_ALLOW_PUBLIC_EGRESS", raising=False)
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    req = supervisor.SpinRequest(realm_description="d", agent_count=2)
    tf._write_tfvars(ws, req, "realm-abc")
    data = json.loads((ws / "terraform.tfvars.json").read_text())
    assert data["allow_public_egress"] is False


def test_terraform_write_tfvars_allow_public_egress_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DIRIJOR_ALLOW_PUBLIC_EGRESS", "1")
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    ws = tmp_path / "ws2"
    ws.mkdir()
    req = supervisor.SpinRequest(realm_description="d", agent_count=2)
    tf._write_tfvars(ws, req, "realm-xyz")
    data = json.loads((ws / "terraform.tfvars.json").read_text())
    assert data["allow_public_egress"] is True


def test_spin_validation_error_accepts_egress_policy_denied():
    exc = supervisor.SpinValidationError(
        code="egress_policy_denied",
        message="policy",
        details={"reason": "policy_hook"},
    )
    assert exc.code == "egress_policy_denied"


def test_spin_egress_policy_denied_when_env_set(monkeypatch, tmp_path):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    monkeypatch.setenv("DIRIJOR_EGRESS_POLICY_DENY", "1")
    stub = _StubTerraformRunner()
    inner = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    wrapped = supervisor._wrap_realm_adapter_with_egress_policy(inner)
    monkeypatch.setattr(
        supervisor,
        "_ADAPTERS",
        {
            "local-noop": supervisor._ADAPTERS["local-noop"],
            "terraform-digitalocean": wrapped,
        },
    )
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={
                "realm_description": "policy deny",
                "adapter_hint": "terraform-digitalocean",
            },
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["phase"] == "failed"
    assert final["error"]["code"] == "egress_policy_denied"
    assert final["error"]["details"]["policy_id"] == "egress-default-v0"
    assert [c[0] for c in stub.calls] == []


def test_egress_policy_deny_env_does_not_affect_local_noop(monkeypatch):
    monkeypatch.setenv("DIRIJOR_EGRESS_POLICY_DENY", "1")
    _clear_spin_state()
    with TestClient(supervisor.app) as local_client:
        resp = local_client.post(
            "/realms/spin",
            json={"realm_description": "noop under deny flag"},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        final: dict = {}
        for _ in range(400):
            time.sleep(0.005)
            body = local_client.get(f"/realms/{job_id}").json()
            if body["phase"] in ("ready", "failed"):
                final = body
                break
    assert final["phase"] == "ready"


def test_terraform_adapter_invalid_cmd_timeout_env_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("DIRIJOR_TERRAFORM_CMD_TIMEOUT_S", "not-a-float")
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path,
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
        cmd_timeout_s=42.5,
    )
    assert tf._cmd_timeout_s == 42.5


def test_terraform_destroy_rejects_workspace_outside_root(monkeypatch, tmp_path):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    stub = _StubTerraformRunner()
    tf = supervisor.TerraformAdapter(
        workspace_root=tmp_path / "wr",
        subprocess_runner=stub,
        env_provider=_tf_env_provider,
        module_source=tmp_path / "mod",
    )
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text("# stub\n", encoding="utf-8")
    outside = tmp_path / "escape_ws"
    outside.mkdir()
    job = supervisor.SpinJob(
        job_id="job-ws",
        realm_id="realm-ws",
        phase="ready",
        adapter=tf.name,
        created_at=supervisor._iso_now(),
        status_url="/realms/job-ws",
        updated_at=supervisor._iso_now(),
        realm_description="x",
        agent_count=1,
        outputs={"tf_workspace": str(outside.resolve())},
        error=None,
        schema_version=supervisor.SCHEMA_VERSION,
    )
    with pytest.raises(supervisor.SpinValidationError) as ei:
        asyncio.run(tf.destroy(job))
    assert ei.value.code == "terraform_destroy_failed"
    assert "escape" in ei.value.message.lower() or "workspace root" in (
        ei.value.message + str(ei.value.details)
    ).lower()


def test_delete_realm_job_404_on_unknown_id():
    _clear_spin_state()
    response = client.delete("/realms/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "job_not_found"


@pytest.mark.parametrize(
    ("raw", "expected_substr"),
    [
        ("prefix do_pat_" + "b" * 64 + " suffix", "do_pat_<REDACTED>"),
        ("prefix do_v1_" + "c" * 64 + " suffix", "do_v1_<REDACTED>"),
        ("export DIGITALOCEAN_TOKEN=supersecret", "DIGITALOCEAN_TOKEN=<REDACTED>"),
        ('{"token": "abc123xyz"}', '"token": "<REDACTED>"'),
    ],
)
def test_scrub_secrets_masks_all_documented_patterns(raw, expected_substr):
    out = supervisor._scrub_secrets(raw)
    assert expected_substr in out
    if "do_pat" in raw:
        assert "do_pat_b" not in out


def test_local_noop_destroy_is_idempotent_noop():
    job = supervisor.SpinJob(
        job_id="j1",
        realm_id="realm-x",
        phase="ready",
        adapter="local-noop",
        created_at="2026-04-18T00:00:00.000000Z",
        status_url="/realms/j1",
        updated_at="2026-04-18T00:00:00.000000Z",
        realm_description="x",
        agent_count=1,
        outputs={},
        error=None,
        schema_version=supervisor.SCHEMA_VERSION,
    )
    asyncio.run(supervisor._ADAPTERS["local-noop"].destroy(job))
    asyncio.run(supervisor._ADAPTERS["local-noop"].destroy(job))
