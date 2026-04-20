# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 4.3 — audit ring, POST /audit/export ZIP bundles, manifest integrity."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

import audit_export as audit_export_lib
import supervisor


@pytest.fixture(autouse=True)
def _isolate_audit_and_quarantine():
    audit_export_lib._AUDIT_DEQUES.clear()
    supervisor._QUARANTINE_BY_REALM.clear()
    supervisor._QUARANTINE_DEDUPE_LAST.clear()
    yield
    audit_export_lib._AUDIT_DEQUES.clear()
    supervisor._QUARANTINE_BY_REALM.clear()
    supervisor._QUARANTINE_DEDUPE_LAST.clear()


def _window_surrounding_now(*, hours_each_side: float = 1.0) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=hours_each_side)).replace(microsecond=0)
    end = (now + timedelta(hours=hours_each_side)).replace(microsecond=0)
    return (
        start.isoformat().replace("+00:00", "Z"),
        end.isoformat().replace("+00:00", "Z"),
    )


def _export_zip(
    client: TestClient,
    *,
    realm_id: str = "realm-a",
    window_start: str = "2026-01-01T00:00:00Z",
    window_end: str = "2026-01-02T00:00:00Z",
):
    return client.post(
        "/audit/export",
        json={
            "realm_id": realm_id,
            "window_start": window_start,
            "window_end": window_end,
        },
    )


def _read_zip_members(z: zipfile.ZipFile) -> dict[str, bytes]:
    return {n: z.read(n) for n in z.namelist()}


def _verify_manifest_against_files(manifest: dict[str, Any], files: dict[str, bytes]) -> None:
    for entry in manifest["files"]:
        path = entry["path"]
        assert path in files
        body = files[path]
        assert len(body) == entry["bytes"]
        assert audit_export_lib.sha256_bytes(body) == entry["sha256"]


def test_export_disabled_returns_403(monkeypatch):
    monkeypatch.delenv("DIRIJOR_AUDIT_EXPORT_ENABLED", raising=False)
    client = TestClient(supervisor.app)
    r = _export_zip(client)
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "audit_export_disabled"
    assert "DIRIJOR_AUDIT_EXPORT_ENABLED" in body["message"]


def test_export_enabled_succeeds(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    client = TestClient(supervisor.app)
    r = _export_zip(client)
    assert r.status_code == 200
    assert r.headers.get("content-type") == "application/zip"
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "dirijor-audit-realm-a-" in cd

    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf) as zf:
        files = _read_zip_members(zf)
        assert "manifest.json" in files
        assert "events.jsonl" in files
        assert "quarantine_snapshot.json" in files
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        assert manifest["window_semantics"] == "half_open_utc"
        assert manifest["realm_id"] == "realm-a"
        assert manifest["manifest_schema"] == "dirijor.audit_export.v1"
        assert manifest["schema_version"] == supervisor.SCHEMA_VERSION
        assert manifest["tamper_evidence"]["algorithm"] == "none"
        _verify_manifest_against_files(manifest, files)
    assert files["events.jsonl"] == b"" or files["events.jsonl"].decode().strip() == ""


def test_invalid_realm_id_returns_400(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    client = TestClient(supervisor.app)
    r = client.post(
        "/audit/export",
        json={
            "realm_id": "bad realm!",
            "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-01-02T00:00:00Z",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "audit_export_invalid_window"


def test_window_must_be_half_open(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    client = TestClient(supervisor.app)
    r = client.post(
        "/audit/export",
        json={
            "realm_id": "r1",
            "window_start": "2026-01-02T00:00:00Z",
            "window_end": "2026-01-01T00:00:00Z",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "audit_export_invalid_window"


def test_window_must_use_z_suffix(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    client = TestClient(supervisor.app)
    r = client.post(
        "/audit/export",
        json={
            "realm_id": "r1",
            "window_start": "2026-01-01T00:00:00+00:00",
            "window_end": "2026-01-02T00:00:00Z",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "audit_export_invalid_window"


def test_max_window_span_enforced(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_MAX_WINDOW_HOURS", "24")
    client = TestClient(supervisor.app)
    r = client.post(
        "/audit/export",
        json={
            "realm_id": "r1",
            "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-01-03T00:00:00Z",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "audit_export_invalid_window"


def test_oversize_export_returns_413(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_MAX_UNCOMPRESSED_BYTES", "64")
    client = TestClient(supervisor.app)
    r = _export_zip(client)
    assert r.status_code == 413
    body = r.json()
    assert body["code"] == "audit_export_too_large"
    assert body["details"]["limit_bytes"] == 64


def test_half_open_excludes_event_at_window_end(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    seq = iter(
        [
            "2026-01-01T06:00:00Z",
            "2026-01-01T12:00:00Z",
            "2026-01-01T12:00:01Z",
        ]
    )
    monkeypatch.setattr(audit_export_lib, "utc_iso_z_now", lambda: next(seq))

    async def _append_both():
        p1 = audit_export_lib.ConsensusCompletedAuditPayload(
            decision="yes",
            consensus_score=1.0,
            termination_reason="threshold_reached",
            rounds=1,
            threshold=0.95,
            vote_count=1,
            message_count=0,
        )
        p2 = audit_export_lib.ConsensusCompletedAuditPayload(
            decision="no",
            consensus_score=0.5,
            termination_reason="max_rounds_exhausted",
            rounds=2,
            threshold=0.95,
            vote_count=2,
            message_count=0,
        )
        await audit_export_lib.append_consensus_completed("realm-a", p1)
        await audit_export_lib.append_consensus_completed("realm-a", p2)

    asyncio.run(_append_both())

    client = TestClient(supervisor.app)
    r = _export_zip(
        client,
        window_start="2026-01-01T00:00:00Z",
        window_end="2026-01-01T12:00:00Z",
    )
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        events_raw = zf.read("events.jsonl").decode("utf-8").strip()
    lines = [ln for ln in events_raw.split("\n") if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["type"] == "consensus.completed"
    assert row["payload"]["decision"] == "yes"


def test_ring_eviction_logs(caplog, monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_RING_MAX", "1")
    caplog.set_level(logging.INFO, logger="dirijor.audit_export")
    seq = iter(["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"])
    monkeypatch.setattr(audit_export_lib, "utc_iso_z_now", lambda: next(seq))

    async def _two():
        p = audit_export_lib.ConsensusCompletedAuditPayload(
            decision=None,
            consensus_score=0.0,
            termination_reason="no_opinions",
            rounds=1,
            threshold=0.95,
            vote_count=0,
            message_count=0,
        )
        await audit_export_lib.append_consensus_completed("r1", p)
        await audit_export_lib.append_consensus_completed("r1", p)

    asyncio.run(_two())
    assert any(
        getattr(rec, "message", "") == "audit.ring_evicted"
        or "audit.ring_evicted" in str(rec.msg)
        for rec in caplog.records
    )


def test_quarantine_idempotent_no_second_audit_row(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")

    async def _double():
        await supervisor._record_quarantine_and_broadcast(
            realm_id="r1",
            agent_id="a1",
            rule_id="rule-1",
            rule_description="d",
            evidence={"k": 1},
            safety_score_hint=0.1,
            label_hint=None,
        )
        await supervisor._record_quarantine_and_broadcast(
            realm_id="r1",
            agent_id="a1",
            rule_id="rule-1",
            rule_description="d",
            evidence={"k": 2},
            safety_score_hint=0.2,
            label_hint=None,
        )

    asyncio.run(_double())

    client = TestClient(supervisor.app)
    ws, we = _window_surrounding_now()
    r = _export_zip(client, realm_id="r1", window_start=ws, window_end=we)
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        lines = [
            ln
            for ln in zf.read("events.jsonl").decode("utf-8").split("\n")
            if ln.strip()
        ]
    quarantine_rows = [
        json.loads(ln) for ln in lines if json.loads(ln)["type"] == "safety.quarantine"
    ]
    assert len(quarantine_rows) == 1


def test_tamper_detection_helper_flags_hash_mismatch():
    files = {
        "events.jsonl": b'{"x":1}\n',
        "quarantine_snapshot.json": b'{"items":[]}',
    }
    manifest = {
        "files": [
            {
                "path": "events.jsonl",
                "sha256": audit_export_lib.sha256_bytes(files["events.jsonl"]),
                "bytes": len(files["events.jsonl"]),
            },
            {
                "path": "quarantine_snapshot.json",
                "sha256": audit_export_lib.sha256_bytes(
                    files["quarantine_snapshot.json"]
                ),
                "bytes": len(files["quarantine_snapshot.json"]),
            },
        ]
    }
    _verify_manifest_against_files(manifest, files)
    mutated = dict(files)
    mutated["events.jsonl"] = b'{"x":2}\n'
    with pytest.raises(AssertionError):
        _verify_manifest_against_files(manifest, mutated)


def test_consensus_with_realm_writes_audit_row(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    client = TestClient(supervisor.app)
    body = {
        "realm_id": "realm-x",
        "query": "hello",
        "max_rounds": 1,
        "threshold": 0.95,
    }
    r = client.post("/consensus", json=body)
    assert r.status_code == 200

    ws, we = _window_surrounding_now()
    r2 = _export_zip(
        client,
        realm_id="realm-x",
        window_start=ws,
        window_end=we,
    )
    assert r2.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r2.content)) as zf:
        lines = [ln for ln in zf.read("events.jsonl").decode().split("\n") if ln]
    assert any(json.loads(ln)["type"] == "consensus.completed" for ln in lines)


def test_consensus_without_realm_has_no_audit_row(monkeypatch):
    monkeypatch.setenv("DIRIJOR_AUDIT_EXPORT_ENABLED", "1")
    client = TestClient(supervisor.app)
    body = {"query": "hello", "max_rounds": 1, "threshold": 0.95}
    r = client.post("/consensus", json=body)
    assert r.status_code == 200

    ws, we = _window_surrounding_now()
    r2 = _export_zip(
        client,
        realm_id="realm-x",
        window_start=ws,
        window_end=we,
    )
    assert r2.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r2.content)) as zf:
        raw = zf.read("events.jsonl").decode().strip()
    assert raw == ""
