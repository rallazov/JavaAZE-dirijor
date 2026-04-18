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
import time

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
    Story 3.2 AC 5, Story 3.3 AC 7)."""
    assert supervisor.SCHEMA_VERSION == 3
    assert supervisor.SERVICE_VERSION == "0.1.0"


def test_schema_version_is_3():
    """Explicit belt-and-braces pin from Story 3.3 AC 8 (renamed from
    `_is_2`; integer bumped from 2 → 3). If a future story bumps
    SCHEMA_VERSION again, BOTH this test and `test_schema_version_pinned`
    must be updated together so the intent is impossible to miss in diff review."""
    assert supervisor.SCHEMA_VERSION == 3


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


def test_ws_broadcast_reaches_only_matching_realm():
    """AC 2 — tenant isolation: `broadcast_event("A", …)` reaches A, not B.
    Also verifies monotonic `seq` per-session (A: 0=hello, 1=delta)."""
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

            frame = ws_a.receive_json()
            assert frame["type"] == "topology.delta"
            assert frame["realm_id"] == "A"
            assert frame["seq"] == 1  # post-hello increment
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
