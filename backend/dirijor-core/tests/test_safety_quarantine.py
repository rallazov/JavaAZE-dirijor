# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 4.2 — anomaly policy load, quarantine registry, HTTP + WS hooks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import safety_policy
import supervisor
from safety_policy import AnomalyPolicyDocument, AnomalyRule, WhenConsensusScoreBelow


@pytest.fixture(autouse=True)
def _reset_quarantine_state():
    supervisor._QUARANTINE_BY_REALM.clear()
    supervisor._QUARANTINE_DEDUPE_LAST.clear()
    doc, err = safety_policy.load_anomaly_policy_from_path(None)
    supervisor._ANOMALY_POLICY_DOC = doc
    supervisor._ANOMALY_POLICY_LOAD_ERROR = err
    yield
    supervisor._QUARANTINE_BY_REALM.clear()
    supervisor._QUARANTINE_DEDUPE_LAST.clear()
    supervisor._ANOMALY_POLICY_DOC = doc
    supervisor._ANOMALY_POLICY_LOAD_ERROR = err


def test_policy_load_empty_path():
    doc, err = safety_policy.load_anomaly_policy_from_path(None)
    assert err is None
    assert doc is not None
    assert doc.rules == []


def test_policy_load_valid_json(tmp_path: Path):
    p = tmp_path / "pol.json"
    p.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "id": "r1",
                        "description": "x",
                        "when": {"type": "consensus_score_below", "threshold": 0.5},
                        "action": "quarantine",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doc, err = safety_policy.load_anomaly_policy_from_path(str(p))
    assert err is None
    assert doc is not None and len(doc.rules) == 1


def test_policy_load_invalid_type(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "id": "r1",
                        "when": {"type": "unknown_matcher", "x": 1},
                        "action": "quarantine",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doc, err = safety_policy.load_anomaly_policy_from_path(str(p))
    assert doc is None
    assert err is not None


def test_broadcast_event_unknown_type_still_raises():
    with pytest.raises(ValueError, match="unsupported event_type"):
        asyncio.run(supervisor.broadcast_event("demo", "not.a.real.type", {}))


def test_consensus_triggers_quarantine_and_broadcasts(monkeypatch):
    captured: list[tuple[str, str, dict]] = []

    async def _cap(realm_id: str, event_type: str, payload: dict):
        captured.append((realm_id, event_type, payload))
        return 0

    monkeypatch.setattr(supervisor, "broadcast_event", _cap)

    supervisor._ANOMALY_POLICY_DOC = AnomalyPolicyDocument(
        rules=[
            AnomalyRule(
                id="low-quorum",
                description="Score below 0.9",
                when=WhenConsensusScoreBelow(threshold=0.9),
            )
        ]
    )
    supervisor._ANOMALY_POLICY_LOAD_ERROR = None

    client = TestClient(supervisor.app)
    body = {
        "realm_id": "realm-a",
        "anomaly_subject_agent_id": "agent-0",
        "opinions": [
            {"agent_id": "a1", "opinion": "buy", "confidence": 1.0},
            {"agent_id": "a2", "opinion": "sell", "confidence": 1.0},
            {"agent_id": "a3", "opinion": "hold", "confidence": 1.0},
        ],
        "max_rounds": 2,
        "threshold": 0.95,
    }
    r = client.post("/consensus", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["consensus_score"] < 0.9

    topo = [x for x in captured if x[1] == "topology.delta"]
    hitl = [x for x in captured if x[1] == "hitl.pending"]
    assert len(topo) == 1
    assert topo[0][0] == "realm-a"
    assert topo[0][2]["agents"][0]["id"] == "agent-0"
    assert topo[0][2]["agents"][0]["status"] == "quarantined"
    assert len(hitl) == 1
    assert hitl[0][2]["action"]["id"].startswith("quarantine:realm-a:agent-0:")

    listed = client.get("/safety/quarantine/realm-a")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["agent_id"] == "agent-0"
    assert items[0]["rule_id"] == "low-quorum"
    assert items[0]["realm_id"] == "realm-a"


def test_quarantine_realm_isolation():
    supervisor._ANOMALY_POLICY_DOC = AnomalyPolicyDocument(
        rules=[
            AnomalyRule(
                id="term",
                when=safety_policy.WhenConsensusTerminationIn(
                    reasons=["no_opinions"],
                ),
            )
        ]
    )
    supervisor._ANOMALY_POLICY_LOAD_ERROR = None

    client = TestClient(supervisor.app)
    r = client.post(
        "/consensus",
        json={"realm_id": "r1", "anomaly_subject_agent_id": "x", "opinions": []},
    )
    assert r.status_code == 200
    assert client.get("/safety/quarantine/r1").json()["items"]
    assert client.get("/safety/quarantine/r2").json()["items"] == []


def test_quarantine_list_invalid_realm():
    client = TestClient(supervisor.app)
    bad = client.get("/safety/quarantine/!!!")
    assert bad.status_code == 400
    assert bad.json()["code"] == "invalid_realm_id"


def test_two_rules_same_agent_both_listed(monkeypatch):
    async def _noop_broadcast(*_a, **_k):
        return 0

    monkeypatch.setattr(supervisor, "broadcast_event", _noop_broadcast)
    monkeypatch.setattr(supervisor, "_SAFETY_SIGNALS_ENABLED", True)

    supervisor._ANOMALY_POLICY_DOC = AnomalyPolicyDocument(
        rules=[
            AnomalyRule(
                id="rule-a",
                when=safety_policy.WhenSignalTypeEq(signal_type="demo"),
            ),
            AnomalyRule(
                id="rule-b",
                when=safety_policy.WhenSignalTypeEq(signal_type="demo"),
            ),
        ]
    )
    supervisor._ANOMALY_POLICY_LOAD_ERROR = None

    client = TestClient(supervisor.app)
    assert (
        client.post(
            "/safety/signal",
            json={
                "realm_id": "multi",
                "agent_id": "agent-1",
                "signal_type": "demo",
            },
        ).status_code
        == 204
    )
    items = client.get("/safety/quarantine/multi").json()["items"]
    assert len(items) == 2
    rule_ids = {row["rule_id"] for row in items}
    assert rule_ids == {"rule-a", "rule-b"}
    assert all(row["agent_id"] == "agent-1" for row in items)


def test_safety_signal_tool_regex(monkeypatch):
    async def _noop_broadcast(*_a, **_k):
        return 0

    monkeypatch.setattr(supervisor, "broadcast_event", _noop_broadcast)
    monkeypatch.setattr(supervisor, "_SAFETY_SIGNALS_ENABLED", True)

    supervisor._ANOMALY_POLICY_DOC = AnomalyPolicyDocument(
        rules=[
            AnomalyRule(
                id="danger-tool",
                when=safety_policy.WhenToolNameRegex(pattern=r"^rm\s+-rf"),
            )
        ]
    )
    supervisor._ANOMALY_POLICY_LOAD_ERROR = None

    client = TestClient(supervisor.app)
    sig = client.post(
        "/safety/signal",
        json={
            "realm_id": "z9",
            "agent_id": "tool-runner",
            "signal_type": "tool_call",
            "tool_name": "rm -rf /",
            "evidence": {"trace": "synthetic"},
        },
    )
    assert sig.status_code == 204
    listed = client.get("/safety/quarantine/z9").json()["items"]
    assert len(listed) == 1
    assert listed[0]["rule_id"] == "danger-tool"


def test_safety_signal_disabled_by_default():
    supervisor._ANOMALY_POLICY_DOC = AnomalyPolicyDocument(rules=[])
    supervisor._ANOMALY_POLICY_LOAD_ERROR = None
    client = TestClient(supervisor.app)
    r = client.post(
        "/safety/signal",
        json={
            "realm_id": "z9",
            "agent_id": "a",
            "signal_type": "x",
        },
    )
    assert r.status_code == 403


def test_anomaly_policy_probe_surfaces_load_error(monkeypatch, tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(supervisor, "_ANOMALY_POLICY_LOAD_ERROR", "forced policy error")
    checks = supervisor.resolve_readiness()
    assert checks["anomaly_policy"]["ready"] is False
    assert "forced policy error" in (checks["anomaly_policy"]["detail"] or "")
