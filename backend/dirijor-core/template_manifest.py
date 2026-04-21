# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Swarm template manifest schema (v1) and verification (Story 7.1).

Pydantic models are the source of truth; use ``template_manifest_v1_json_schema``
to export derived JSON Schema for consumers and CI.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

# --- Closed error taxonomy for verify_template_manifest ----------------------------

TemplateManifestErrorCode = Literal["PARSE", "SCHEMA", "SIGNATURE", "PINS"]

MANIFEST_SCHEMA_V1: Final = "dirijor.template_manifest.v1"

# Algorithms we can verify in-process (stdlib + env key). Ed25519 reserved for a
# future optional ``cryptography`` dependency — see docs/reference/template-manifest.md.
SignatureAlgorithm = Literal["hmac-sha256", "ed25519", "none"]


@dataclass(frozen=True, slots=True)
class TemplateManifestVerifySuccess:
    """Manifest parsed, schema-valid, signature OK, pins OK."""

    manifest: TemplateManifestDocumentV1


@dataclass(frozen=True, slots=True)
class TemplateManifestVerifyFailure:
    code: TemplateManifestErrorCode
    detail: str


TemplateManifestVerifyResult = TemplateManifestVerifySuccess | TemplateManifestVerifyFailure


# --- v1 models (extra=forbid everywhere) --------------------------------------


def _semver_triple(s: str) -> tuple[int, int, int]:
    s = str(s).strip()
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", s)
    if not m:
        raise ValueError(f"expected semver major.minor.patch, got {s!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _semver_ge(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return a >= b


class AgentSlotV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    runtime_hint: str | None = None
    tooling_hint: str | None = None


class PolicyRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["egress_policy", "hitl_policy", "tool_policy"]
    uri: str = Field(min_length=1)
    version: str | None = None


class ManifestPinsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supervisor_schema_version: str = Field(
        description="Minimum Core SCHEMA_VERSION as semver (major.minor.patch)."
    )
    adapter_hint: str | None = None

    @field_validator("supervisor_schema_version")
    @classmethod
    def _supervisor_schema_version_semver(cls, v: str) -> str:
        _semver_triple(v)
        return v


class ManifestSignatureV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: SignatureAlgorithm
    key_id: str | None = None
    value: str = ""


class TemplateManifestDocumentV1(BaseModel):
    """Wire document including embedded ``signatures`` (single-file artifact)."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1)
    template_version: str = Field(min_length=1)
    manifest_schema: Literal["dirijor.template_manifest.v1"]
    created_at: str
    agents: list[AgentSlotV1] = Field(min_length=1)
    policy_refs: list[PolicyRefV1]
    pins: ManifestPinsV1
    signatures: list[ManifestSignatureV1] = Field(min_length=1)

    @field_validator("created_at")
    @classmethod
    def _created_at_utc_z(cls, v: str) -> str:
        s = str(v).strip()
        if not s.endswith("Z"):
            raise ValueError("created_at must be UTC ISO-8601 with Z suffix")
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return s

    @field_validator("template_version")
    @classmethod
    def _template_version_semver(cls, v: str) -> str:
        _semver_triple(v)
        return v


def _json_object_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``json.loads`` hook: reject duplicate keys (stdlib default last-key-wins)."""
    out: dict[str, Any] = {}
    for key, val in pairs:
        if key in out:
            raise json.JSONDecodeError(f"duplicate object key {key!r}", "", 0)
        out[key] = val
    return out


def canonical_json_bytes(obj: Any) -> bytes:
    """UTF-8 JSON with recursively sorted object keys (v1 canonicalization)."""

    def _sort(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: _sort(o[k]) for k in sorted(o.keys())}
        if isinstance(o, list):
            return [_sort(x) for x in o]
        return o

    text = json.dumps(_sort(obj), ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8")


def signing_payload_bytes(doc: TemplateManifestDocumentV1) -> bytes:
    """Bytes signed or authenticated — manifest content only, ``signatures`` omitted."""
    payload = doc.model_dump(mode="json", exclude={"signatures"})
    return canonical_json_bytes(payload)


def _verify_hmac_sha256(*, key: bytes, message: bytes, value_b64: str) -> bool:
    try:
        digest = base64.b64decode(value_b64, validate=True)
    except (binascii.Error, ValueError):
        return False
    expected = hmac.new(key, message, hashlib.sha256).digest()
    if len(digest) != len(expected):
        return False
    return hmac.compare_digest(digest, expected)


def _verify_signatures(
    doc: TemplateManifestDocumentV1,
    *,
    hmac_key: bytes | None,
) -> str | None:
    """Return an error detail string if verification fails; else None."""
    message = signing_payload_bytes(doc)
    for sig in doc.signatures:
        if sig.algorithm == "none":
            # Explicit stub — no cryptographic integrity (honest; see Story 4.3 tone).
            continue
        if sig.algorithm == "ed25519":
            return "ed25519 verification is not implemented in Core v1 (no bundled key material)"
        if sig.algorithm == "hmac-sha256":
            if not hmac_key:
                return "hmac-sha256 requires DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY"
            if not _verify_hmac_sha256(key=hmac_key, message=message, value_b64=sig.value):
                return "hmac-sha256 signature mismatch"
            continue
    return None


def _verify_pins(
    doc: TemplateManifestDocumentV1,
    *,
    effective_supervisor_schema_version: int,
    pin_bindings: dict[str, str] | None,
) -> str | None:
    pins = doc.pins
    min_sv = _semver_triple(pins.supervisor_schema_version)
    core_sv = (effective_supervisor_schema_version, 0, 0)
    if not _semver_ge(core_sv, min_sv):
        return (
            f"Core SCHEMA_VERSION {effective_supervisor_schema_version} maps to "
            f"{effective_supervisor_schema_version}.0.0, below manifest minimum "
            f"{pins.supervisor_schema_version}"
        )

    raw = pins.model_dump(mode="json")
    for key, val in raw.items():
        if key == "supervisor_schema_version" or val is None:
            continue
        if not isinstance(val, str):
            continue
        if pin_bindings is None or key not in pin_bindings:
            return f"missing pin binding for pins.{key}"
        if pin_bindings[key] != val:
            return f"pin mismatch on {key!r}"
    return None


def verify_template_manifest(
    raw: bytes | bytearray,
    *,
    effective_supervisor_schema_version: int,
    pin_bindings: dict[str, str] | None = None,
) -> TemplateManifestVerifyResult:
    """Parse, schema-validate, verify signatures, then verify pins.

    * **PARSE** — invalid UTF-8, invalid JSON, or duplicate JSON object keys.
    * **SCHEMA** — Pydantic validation (including ``extra`` keys at parse time via JSON).
    * **SIGNATURE** — missing/invalid HMAC, unsupported algorithm, or tamper.
    * **PINS** — supervisor semver floor or exact-string pin mismatch.

    ``pin_bindings`` supplies expected values for non-``supervisor_schema_version`` pin
    fields that are present on the manifest (exact equality, v1).
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return TemplateManifestVerifyFailure(code="PARSE", detail=str(e))

    try:
        data = json.loads(text, object_pairs_hook=_json_object_pairs_no_duplicates)
    except json.JSONDecodeError as e:
        return TemplateManifestVerifyFailure(code="PARSE", detail=str(e))

    if not isinstance(data, dict):
        return TemplateManifestVerifyFailure(
            code="SCHEMA", detail="manifest root must be a JSON object"
        )

    try:
        doc = TemplateManifestDocumentV1.model_validate(data)
    except ValidationError as e:
        return TemplateManifestVerifyFailure(code="SCHEMA", detail=str(e))

    hmac_key_raw = os.environ.get("DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY", "").strip()
    hmac_key = hmac_key_raw.encode("utf-8") if hmac_key_raw else None

    sig_err = _verify_signatures(doc, hmac_key=hmac_key)
    if sig_err:
        return TemplateManifestVerifyFailure(code="SIGNATURE", detail=sig_err)

    pin_err = _verify_pins(
        doc,
        effective_supervisor_schema_version=effective_supervisor_schema_version,
        pin_bindings=pin_bindings,
    )
    if pin_err:
        return TemplateManifestVerifyFailure(code="PINS", detail=pin_err)

    return TemplateManifestVerifySuccess(manifest=doc)


def template_manifest_v1_json_schema() -> dict[str, Any]:
    """Derived JSON Schema for ``dirijor.template_manifest.v1`` wire document."""
    adapter = TypeAdapter(TemplateManifestDocumentV1)
    return adapter.json_schema()


def seal_manifest_with_hmac(
    doc: TemplateManifestDocumentV1,
    *,
    key: bytes,
) -> TemplateManifestDocumentV1:
    """Attach a single ``hmac-sha256`` signature over the v1 signing payload (tooling/tests)."""
    msg = signing_payload_bytes(doc)
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    sig = ManifestSignatureV1(
        algorithm="hmac-sha256",
        value=base64.b64encode(digest).decode("ascii"),
    )
    return doc.model_copy(update={"signatures": [sig]})
