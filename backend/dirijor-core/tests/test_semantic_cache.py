# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 4.1 — verified semantic cache (hermetic fakes, no live Qdrant)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

import supervisor
from supervisor import (
    ConsensusRequest,
    SemanticCacheIngestRequest,
    SemanticCacheQueryRequest,
    SemanticCacheSettings,
    VerifiedFact,
)

client = TestClient(supervisor.app)

VEC4 = [0.1, 0.2, 0.3, 0.4]


class _FakeSemanticCache:
    """Minimal protocol implementation for tests."""

    def __init__(self) -> None:
        self.query_hits: list[VerifiedFact] = []
        self.consensus_hits: list[VerifiedFact] | None = None
        self.consensus_miss: str | None = None
        self.raise_on_query = False

    async def ready(self) -> tuple[bool, str | None]:
        return True, None

    async def ingest(self, req: SemanticCacheIngestRequest):
        return supervisor.SemanticCacheIngestResponse(
            fact_id=req.fact_id or "gen-id",
            scope_id=req.scope_id,
            provenance_id=req.provenance_id,
            collection="fake",
            schema_version=supervisor.SCHEMA_VERSION,
        )

    async def query(self, req: SemanticCacheQueryRequest) -> list[VerifiedFact]:
        if self.raise_on_query:
            raise RuntimeError("simulated qdrant failure")
        return list(self.query_hits)

    async def consensus_fetch(
        self, req: ConsensusRequest
    ) -> tuple[list[VerifiedFact], str | None]:
        if self.consensus_miss is not None:
            return [], self.consensus_miss
        if self.consensus_hits is not None:
            return (list(self.consensus_hits), None) if self.consensus_hits else ([], "no_hits")
        if not req.query_vector:
            return [], "query_vector_missing"
        return list(self.query_hits), (None if self.query_hits else "no_hits")


@pytest.fixture
def fake_qdrant_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        supervisor,
        "_SEMANTIC_SETTINGS",
        SemanticCacheSettings(
            mode="qdrant",
            url="http://127.0.0.1:6333",
            collection="t",
            vector_size=4,
            default_score_threshold=0.78,
        ),
    )


def test_semantic_cache_ingest_rejects_missing_provenance(fake_qdrant_settings, monkeypatch):
    monkeypatch.setattr(supervisor, "_SEMANTIC_CACHE", _FakeSemanticCache())
    r = client.post(
        "/semantic-cache/ingest",
        json={
            "scope_id": "s",
            "provenance_id": "   ",
            "verified_by": "v",
            "text": "hello",
            "vector": VEC4,
        },
    )
    assert r.status_code == 422


def test_semantic_cache_query_filters_by_scope(fake_qdrant_settings, monkeypatch):
    fake = _FakeSemanticCache()
    fake.query_hits = [
        VerifiedFact(
            fact_id="a",
            provenance_id="p",
            source_uri="",
            snippet="x",
            score=0.9,
            metadata={},
        )
    ]
    monkeypatch.setattr(supervisor, "_SEMANTIC_CACHE", fake)
    r = client.post(
        "/semantic-cache/query",
        json={
            "query_vector": VEC4,
            "scope_id": "scope-a",
            "limit": 5,
        },
    )
    assert r.status_code == 200
    assert len(r.json()["hits"]) == 1


def test_semantic_cache_query_applies_score_threshold(fake_qdrant_settings, monkeypatch):
    """Threshold is applied in Qdrant backend; fake returns pre-filtered hits."""

    class _ThrFake(_FakeSemanticCache):
        async def query(self, req: SemanticCacheQueryRequest) -> list[VerifiedFact]:
            eff = req.score_threshold if req.score_threshold is not None else 0.78
            return [h for h in self.query_hits if h.score >= eff]

    fake = _ThrFake()
    fake.query_hits = [
        VerifiedFact(
            fact_id="1",
            provenance_id="p",
            source_uri="",
            snippet="lo",
            score=0.5,
            metadata={},
        ),
        VerifiedFact(
            fact_id="2",
            provenance_id="p",
            source_uri="",
            snippet="hi",
            score=0.95,
            metadata={},
        ),
    ]
    monkeypatch.setattr(supervisor, "_SEMANTIC_CACHE", fake)
    r = client.post(
        "/semantic-cache/query",
        json={
            "query_vector": VEC4,
            "scope_id": "s",
            "score_threshold": 0.9,
        },
    )
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert len(hits) == 1
    assert hits[0]["fact_id"] == "2"


def test_consensus_attaches_verified_facts_from_semantic_cache(
    fake_qdrant_settings, monkeypatch
):
    vf = VerifiedFact(
        fact_id="f1",
        provenance_id="prov",
        source_uri="https://ex/x",
        snippet="body",
        score=0.91,
        metadata={"k": 1},
    )
    fake = _FakeSemanticCache()
    fake.consensus_hits = [vf]
    monkeypatch.setattr(supervisor, "_SEMANTIC_CACHE", fake)
    r = client.post(
        "/consensus",
        json={
            "query": "q",
            "opinions": [
                {"agent_id": "a", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "b", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "c", "opinion": "yes", "confidence": 1.0},
            ],
            "query_vector": VEC4,
            "semantic_scope_id": "realm-alpha",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["verified_facts"]) == 1
    assert body["verified_facts"][0]["fact_id"] == "f1"
    assert body["verified_facts"][0]["score"] == 0.91
    assert body["semantic_cache_status"] == "hit"
    assert body["semantic_cache_reason"] is None


def test_consensus_rejects_query_vector_without_semantic_scope_id(
    fake_qdrant_settings, monkeypatch
):
    monkeypatch.setattr(supervisor, "_SEMANTIC_CACHE", _FakeSemanticCache())
    r = client.post(
        "/consensus",
        json={
            "query": "q",
            "opinions": [
                {"agent_id": "a", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "b", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "c", "opinion": "yes", "confidence": 1.0},
            ],
            "query_vector": VEC4,
        },
    )
    assert r.status_code == 422


def test_consensus_logs_miss_when_query_vector_missing(
    fake_qdrant_settings, monkeypatch, caplog
):
    fake = _FakeSemanticCache()
    monkeypatch.setattr(supervisor, "_SEMANTIC_CACHE", fake)
    caplog.set_level(logging.INFO, logger="dirijor.supervisor")
    r = client.post(
        "/consensus",
        json={
            "opinions": [{"agent_id": "a", "opinion": "yes", "confidence": 1.0}],
        },
    )
    assert r.status_code == 200
    assert r.json()["semantic_cache_status"] == "skipped"
    assert r.json()["semantic_cache_reason"] == "query_vector_missing"
    assert any(
        rec.getMessage() == "semantic_cache.miss"
        and getattr(rec, "event", None) == "semantic_cache.miss"
        and getattr(rec, "reason", None) == "query_vector_missing"
        for rec in caplog.records
    ), caplog.records


def test_semantic_cache_unavailable_logs_miss_without_failing_consensus(
    fake_qdrant_settings, monkeypatch, caplog
):
    fake = _FakeSemanticCache()
    fake.consensus_miss = "qdrant_unavailable"
    monkeypatch.setattr(supervisor, "_SEMANTIC_CACHE", fake)
    caplog.set_level(logging.INFO, logger="dirijor.supervisor")
    r = client.post(
        "/consensus",
        json={
            "query": "q",
            "opinions": [
                {"agent_id": "a", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "b", "opinion": "yes", "confidence": 1.0},
                {"agent_id": "c", "opinion": "yes", "confidence": 1.0},
            ],
            "query_vector": VEC4,
            "semantic_scope_id": "realm-alpha",
        },
    )
    assert r.status_code == 200
    assert r.json()["verified_facts"] == []
    assert r.json()["semantic_cache_status"] == "unavailable"
    assert r.json()["semantic_cache_reason"] == "qdrant_unavailable"
    assert any(
        getattr(rec, "reason", None) == "qdrant_unavailable" for rec in caplog.records
    )


def test_health_semantic_cache_ready_when_configured(monkeypatch):
    fake = _FakeSemanticCache()
    monkeypatch.setattr(supervisor, "_SEMANTIC_CACHE", fake)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["checks"]["semantic_cache"]["ready"] is True
    assert r.json()["checks"]["semantic_cache"]["detail"] is None


def test_qdrant_point_id_differs_by_scope_for_same_fact_id():
    a = supervisor._qdrant_point_id("realm-a", "doc-1")
    b = supervisor._qdrant_point_id("realm-b", "doc-1")
    assert a != b
    assert supervisor._qdrant_point_id("realm-a", "doc-1") == a


def test_health_semantic_cache_not_configured_is_optional():
    r = client.get("/health")
    assert r.status_code == 200
    sc = r.json()["checks"]["semantic_cache"]
    assert sc["required"] is False
    assert sc["ready"] is False
    assert sc["detail"] == "not configured"
