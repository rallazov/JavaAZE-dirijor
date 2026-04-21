# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 7.1 — template manifest schema, canonical signing payload, verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import supervisor
import template_manifest as tm

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMMITTED_TEMPLATE_SCHEMA = _REPO_ROOT / "docs" / "reference" / "schemas" / "dirijor.template_manifest.v1.json"


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


def test_golden_round_trip_hmac(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    key = b"unit-test-hmac-key"
    doc = _base_document()
    sealed = tm.seal_manifest_with_hmac(doc, key=key)
    raw = json.dumps(sealed.model_dump(mode="json")).encode("utf-8")

    res = tm.verify_template_manifest(
        raw,
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
        pin_bindings={"adapter_hint": "terraform-digitalocean"},
    )
    assert isinstance(res, tm.TemplateManifestVerifySuccess)
    assert res.manifest.template_id == "golden-tmpl"


def test_schema_rejects_extra_top_level_key():
    d = _base_document().model_dump(mode="json")
    d["extra_field"] = 1
    raw = json.dumps(d).encode("utf-8")
    res = tm.verify_template_manifest(
        raw,
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
        pin_bindings={"adapter_hint": "terraform-digitalocean"},
    )
    assert isinstance(res, tm.TemplateManifestVerifyFailure)
    assert res.code == "SCHEMA"


def test_schema_rejects_invalid_pins_supervisor_semver(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    d = _base_document().model_dump(mode="json")
    d["pins"]["supervisor_schema_version"] = "not-a-semver"
    raw = json.dumps(d).encode("utf-8")
    res = tm.verify_template_manifest(
        raw,
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
        pin_bindings={"adapter_hint": "terraform-digitalocean"},
    )
    assert isinstance(res, tm.TemplateManifestVerifyFailure)
    assert res.code == "SCHEMA"


def test_parse_rejects_duplicate_json_keys():
    raw = b'{"x": 1, "x": 2}'
    res = tm.verify_template_manifest(
        raw,
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
    )
    assert isinstance(res, tm.TemplateManifestVerifyFailure)
    assert res.code == "PARSE"


def test_signature_failure_on_tamper(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    key = b"unit-test-hmac-key"
    sealed = tm.seal_manifest_with_hmac(_base_document(), key=key)
    text = json.dumps(sealed.model_dump(mode="json"))
    # Single-byte tamper in the serialized JSON (after signing).
    tampered = text.replace("golden-tmpl", "golden-!mpl", 1).encode("utf-8")

    res = tm.verify_template_manifest(
        tampered,
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
        pin_bindings={"adapter_hint": "terraform-digitalocean"},
    )
    assert isinstance(res, tm.TemplateManifestVerifyFailure)
    assert res.code == "SIGNATURE"


def test_pins_supervisor_floor_core_too_old(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
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

    res = tm.verify_template_manifest(
        raw,
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
        pin_bindings={"adapter_hint": "terraform-digitalocean"},
    )
    assert isinstance(res, tm.TemplateManifestVerifyFailure)
    assert res.code == "PINS"


def test_pins_adapter_hint_mismatch(monkeypatch):
    monkeypatch.setenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "unit-test-hmac-key")
    sealed = tm.seal_manifest_with_hmac(_base_document(), key=b"unit-test-hmac-key")
    raw = json.dumps(sealed.model_dump(mode="json")).encode("utf-8")

    res = tm.verify_template_manifest(
        raw,
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
        pin_bindings={"adapter_hint": "wrong-adapter"},
    )
    assert isinstance(res, tm.TemplateManifestVerifyFailure)
    assert res.code == "PINS"


def test_parse_invalid_utf8():
    res = tm.verify_template_manifest(
        b"\xff\xfe not utf-8",
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
    )
    assert isinstance(res, tm.TemplateManifestVerifyFailure)
    assert res.code == "PARSE"


def test_explicit_none_signature_without_hmac_env(monkeypatch):
    monkeypatch.delenv("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", raising=False)
    doc = _base_document()
    raw = json.dumps(doc.model_dump(mode="json")).encode("utf-8")
    res = tm.verify_template_manifest(
        raw,
        effective_supervisor_schema_version=supervisor.SCHEMA_VERSION,
        pin_bindings={"adapter_hint": "terraform-digitalocean"},
    )
    assert isinstance(res, tm.TemplateManifestVerifySuccess)


def test_json_schema_export_matches_snapshot():
    assert _COMMITTED_TEMPLATE_SCHEMA.is_file(), f"missing {_COMMITTED_TEMPLATE_SCHEMA}"
    committed = json.loads(_COMMITTED_TEMPLATE_SCHEMA.read_text(encoding="utf-8"))
    generated = tm.template_manifest_v1_json_schema()
    assert committed == generated

