# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 6.1 — OpenTelemetry span wiring (isolated subprocess so TracerProvider is set first)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parent.parent


def test_consensus_emits_manual_spans_when_tracer_provider_configured() -> None:
    script = """
import os
os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

class _ListExporter(SpanExporter):
    def __init__(self):
        self.finished = []

    def export(self, spans):
        self.finished.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None

exporter = _ListExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)

import supervisor
from fastapi.testclient import TestClient

client = TestClient(supervisor.app)
resp = client.post(
    "/consensus",
    json={"query": "otel-smoke", "opinions": [{"opinion": "yes", "agent_id": "a0"}]},
)
assert resp.status_code == 200, resp.text
names = [s.name for s in exporter.finished]
assert "dirijor.consensus" in names, names
assert "dirijor.semantic_cache.consensus_fetch" in names, names
"""
    r = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_CORE),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if r.returncode != 0:
        pytest.fail(r.stderr or r.stdout or "subprocess failed")


def test_quarantine_emits_otel_span_when_tracer_provider_configured() -> None:
    """Story 6.2 — dirijor.safety.quarantine_record on quarantine notify path."""
    script = """
import os
os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

class _ListExporter(SpanExporter):
    def __init__(self):
        self.finished = []

    def export(self, spans):
        self.finished.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None

exporter = _ListExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)

import supervisor
from fastapi.testclient import TestClient
from safety_policy import AnomalyPolicyDocument, AnomalyRule, WhenConsensusScoreBelow

async def _noop(*_a, **_k):
    return 0

supervisor.broadcast_event = _noop
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
names = [s.name for s in exporter.finished]
assert "dirijor.safety.quarantine_record" in names, names
"""
    r = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_CORE),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if r.returncode != 0:
        pytest.fail(r.stderr or r.stdout or "subprocess failed")


def test_default_pytest_suite_has_no_otlp_dependency() -> None:
    """Guard: normal `pytest` path must not require a collector (provider unset)."""
    from fastapi.testclient import TestClient

    import supervisor

    client = TestClient(supervisor.app)
    r = client.post("/consensus", json={"query": "x", "opinions": [{"opinion": "y"}]})
    assert r.status_code == 200
