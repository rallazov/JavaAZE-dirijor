# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 7.2 — POST /marketplace/templates/import-draft + draft mapper."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import marketplace_import_draft as mid
import supervisor
import template_manifest as tm

client = TestClient(supervisor.app)


def _base_document() -> tm.TemplateManifestDocumentV1:
    return tm.TemplateManifestDocumentV1(
        template_id="golden-tmpl",
        template_version="1.0.0",
        manifest_schema=tm.MANIFEST_SCHEMA_V1,
        created_at="2026-04-20T12:00:00Z",
        agents=[
            tm.AgentSlotV1(
                agent_id="agent-1",
                role="worker",
                runtime_hint="openclaw",
                tooling_hint=None,
            )
        ],
        policy_refs=[
            tm.PolicyRefV1(
                kind="egress_policy",
                uri="https://registry.example.invalid/policies/egress/default-deny-v1",
                version="1.0.0",
            )
        ],
        pins=tm.ManifestPinsV1(
            supervisor_schema_version="1.0.0",
            adapter_hint="terraform-digitalocean",
        ),
        signatures=[tm.ManifestSignatureV1(algorithm="none", value="")],
    )


def _doc_with_agent_count(n: int) -> tm.TemplateManifestDocumentV1:
    agents = [
        tm.AgentSlotV1(
            agent_id=f"agent-{i}",
            role="worker",
            runtime_hint=None,
            tooling_hint=None,
        )
        for i in range(n)
    ]
    return tm.TemplateManifestDocumentV1(
        template_id="many",
        template_version="1.0.0",
        manifest_schema=tm.MANIFEST_SCHEMA_V1,
        created_at="2026-04-20T12:00:00Z",
        agents=agents,
        policy_refs=[],
        pins=tm.ManifestPinsV1(supervisor_schema_version="1.0.0", adapter_hint=None),
        signatures=[tm.ManifestSignatureV1(algorithm="none", value="")],
    )


def test_map_verified_manifest_draft_agent_count_exceeded():
    doc = _doc_with_agent_count(51)
    assert mid.map_verified_manifest_to_realm_draft(doc) == "draft_agent_count_exceeded"


def test_map_verified_manifest_success_fields():
    doc = _base_document()
    got = mid.map_verified_manifest_to_realm_draft(doc)
    assert isinstance(got, mid.MarketplaceRealmDraft)
    assert got.agent_count == 1
    assert got.adapter_hint == "terraform-digitalocean"
    assert got.realm_description.startswith("Imported template:")
    assert "golden-tmpl" in got.realm_description
    assert len(got.realm_description) <= 2000
    assert bool(got.realm_description.strip())
    assert len(got.policy_refs) == 1


def test_default_realm_description_truncates_to_2000():
    tid = "x" * 2500
    tv = "1.0.0"
    s = mid.default_realm_description_imported(tid, tv, max_length=2000)
    assert len(s) == 2000


def test_default_realm_description_rejects_zero_max_length():
    with pytest.raises(ValueError, match="max_length"):
        mid.default_realm_description_imported("tmpl", "1.0.0", max_length=0)


def test_import_draft_http_success(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    monkeypatch.setenv(
        "DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT", "terraform-digitalocean"
    )
    sealed = tm.seal_manifest_with_hmac(_base_document(), key=b"unit-test-hmac-key")
    raw = json.dumps(sealed.model_dump(mode="json")).encode("utf-8")
    r = client.post("/marketplace/templates/import-draft", content=raw)
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == supervisor.SCHEMA_VERSION
    assert body["draft"]["agent_count"] == 1
    assert body["draft"]["realm_description"].startswith("Imported template:")
    assert body["draft"]["adapter_hint"] == "terraform-digitalocean"


@pytest.mark.parametrize(
    "raw, code",
    [
        (b'{"x": 1, "x": 2}', "PARSE"),
        (b"{", "PARSE"),
        (b"\xff\xfe not utf-8", "PARSE"),
    ],
)
def test_import_draft_parse_errors(raw: bytes, code: str):
    r = client.post("/marketplace/templates/import-draft", content=raw)
    assert r.status_code == 422
    j = r.json()
    assert j["code"] == code
    assert j["schema_version"] == supervisor.SCHEMA_VERSION
    assert "detail" in j


def test_import_draft_rejects_oversized_body():
    raw = b"x" * (supervisor.MAX_MARKETPLACE_IMPORT_BYTES + 1)
    r = client.post("/marketplace/templates/import-draft", content=raw)
    assert r.status_code == 413
    j = r.json()
    assert j["code"] == "REQUEST_TOO_LARGE"
    assert j["schema_version"] == supervisor.SCHEMA_VERSION
    assert str(supervisor.MAX_MARKETPLACE_IMPORT_BYTES) in j["detail"]


def test_import_draft_schema_extra_field(monkeypatch):
    monkeypatch.setenv(
        "DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT", "terraform-digitalocean"
    )
    d = _base_document().model_dump(mode="json")
    d["extra_field"] = 1
    raw = json.dumps(d).encode("utf-8")
    r = client.post("/marketplace/templates/import-draft", content=raw)
    assert r.status_code == 422
    assert r.json()["code"] == "SCHEMA"


def test_import_draft_signature_failure(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    monkeypatch.setenv(
        "DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT", "terraform-digitalocean"
    )
    key = b"unit-test-hmac-key"
    sealed = tm.seal_manifest_with_hmac(_base_document(), key=key)
    text = json.dumps(sealed.model_dump(mode="json"))
    tampered = text.replace("golden-tmpl", "golden-!mpl", 1).encode("utf-8")
    r = client.post("/marketplace/templates/import-draft", content=tampered)
    assert r.status_code == 422
    assert r.json()["code"] == "SIGNATURE"


def test_import_draft_pins_supervisor_floor(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    monkeypatch.setenv(
        "DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT", "terraform-digitalocean"
    )
    doc = _base_document()
    doc = doc.model_copy(
        update={
            "pins": tm.ManifestPinsV1(
                supervisor_schema_version="99.0.0",
                adapter_hint="terraform-digitalocean",
            )
        }
    )
    sealed = tm.seal_manifest_with_hmac(doc, key=b"unit-test-hmac-key")
    raw = json.dumps(sealed.model_dump(mode="json")).encode("utf-8")
    r = client.post("/marketplace/templates/import-draft", content=raw)
    assert r.status_code == 422
    assert r.json()["code"] == "PINS"


def test_import_draft_pins_adapter_mismatch(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT", "wrong-adapter")
    sealed = tm.seal_manifest_with_hmac(_base_document(), key=b"unit-test-hmac-key")
    raw = json.dumps(sealed.model_dump(mode="json")).encode("utf-8")
    r = client.post("/marketplace/templates/import-draft", content=raw)
    assert r.status_code == 422
    assert r.json()["code"] == "PINS"


def test_import_draft_empty_agents_never_reaches_draft(monkeypatch):
    """v1 requires min_length=1 agents; empty array fails SCHEMA before mapping."""
    monkeypatch.setenv(
        "DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT", "terraform-digitalocean"
    )
    raw = json.dumps(
        {
            "template_id": "e",
            "template_version": "1.0.0",
            "manifest_schema": tm.MANIFEST_SCHEMA_V1,
            "created_at": "2026-04-20T12:00:00Z",
            "agents": [],
            "policy_refs": [],
            "pins": {"supervisor_schema_version": "1.0.0"},
            "signatures": [{"algorithm": "none", "value": ""}],
        }
    ).encode("utf-8")
    r = client.post("/marketplace/templates/import-draft", content=raw)
    assert r.status_code == 422
    assert r.json()["code"] == "SCHEMA"


def test_import_draft_http_51_agents(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    sealed = tm.seal_manifest_with_hmac(
        _doc_with_agent_count(51), key=b"unit-test-hmac-key"
    )
    raw = json.dumps(sealed.model_dump(mode="json")).encode("utf-8")
    r = client.post("/marketplace/templates/import-draft", content=raw)
    assert r.status_code == 422
    j = r.json()
    assert j["code"] == "draft_agent_count_exceeded"
    assert "50" in j["detail"]
