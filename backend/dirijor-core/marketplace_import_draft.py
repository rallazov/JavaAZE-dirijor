# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 7.2 — map a verified template manifest to Epic 2 realm spin draft fields."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from template_manifest import TemplateManifestDocumentV1

# Mirrors SpinRequest.agent_count upper bound in supervisor.py.
_MAX_IMPORT_AGENTS = 50
_MAX_REALM_DESCRIPTION_LEN = 2000


class MarketplaceRealmDraft(BaseModel):
    """Operator-editable inputs aligned with `SpinRequest` (import path only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_count: int
    realm_description: str
    adapter_hint: str | None = None
    policy_refs: list[dict[str, Any]]


def default_realm_description_imported(
    template_id: str,
    template_version: str,
    *,
    max_length: int = _MAX_REALM_DESCRIPTION_LEN,
) -> str:
    """Deterministic default for `realm_description`; always ≤ max_length and non-blank."""
    tid = template_id.strip() if template_id.strip() else "unknown"
    tv = template_version.strip() if template_version.strip() else "unknown"
    base = f"Imported template: {tid} @ {tv}"
    if len(base) <= max_length:
        return base
    if max_length <= 3:
        return ("." * max_length)[:max_length]
    return base[: max_length - 3] + "..."


def map_verified_manifest_to_realm_draft(
    manifest: TemplateManifestDocumentV1,
) -> MarketplaceRealmDraft | Literal["draft_agent_count_exceeded"]:
    """Build realm draft from an already-verified manifest.

    Callers must run `verify_template_manifest` first — this function does not
    re-verify. If ``len(manifest.agents) > 50``, returns ``draft_agent_count_exceeded``
    (no silent clamp).
    """
    n = len(manifest.agents)
    if n > _MAX_IMPORT_AGENTS:
        return "draft_agent_count_exceeded"
    desc = default_realm_description_imported(
        manifest.template_id,
        manifest.template_version,
        max_length=_MAX_REALM_DESCRIPTION_LEN,
    )
    if not desc.strip():
        raise RuntimeError("default realm_description must not be whitespace-only")
    adapter = manifest.pins.adapter_hint
    policy_refs = [p.model_dump(mode="json") for p in manifest.policy_refs]
    return MarketplaceRealmDraft(
        agent_count=n,
        realm_description=desc,
        adapter_hint=adapter,
        policy_refs=policy_refs,
    )


def template_manifest_pin_bindings_from_env() -> dict[str, str] | None:
    """Pin bindings for `verify_template_manifest` (Story 7.1 pins contract).

    When a manifest sets ``pins.adapter_hint``, verification requires the
    expected value via pin_bindings unless the field is omitted. Operators
    set ``DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT`` to match trusted
    imports in this environment.
    """
    out: dict[str, str] = {}
    hint = os.environ.get("DIRIJOR_TEMPLATE_MANIFEST_PIN_ADAPTER_HINT", "").strip()
    if hint:
        out["adapter_hint"] = hint
    return out if out else None
