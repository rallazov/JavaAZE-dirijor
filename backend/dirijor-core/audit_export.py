# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Realm-scoped audit ring buffer and ZIP export builder (Story 4.3).

State is in-process per replica (same caveat as quarantine / spin jobs).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import uuid
import zipfile
from collections import deque
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("dirijor.audit_export")

_AUDIT_LOCK = asyncio.Lock()
# Per-realm FIFO; overflow drops oldest (see append).
_AUDIT_DEQUES: dict[str, deque[dict[str, Any]]] = {}


def audit_export_enabled() -> bool:
    """Match ``DIRIJOR_SAFETY_SIGNALS_ENABLED`` truthiness (1 / true / yes)."""
    return (
        os.environ.get("DIRIJOR_AUDIT_EXPORT_ENABLED", "").strip().lower()
        in ("1", "true", "yes")
    )


def _ring_max() -> int:
    raw = os.environ.get("DIRIJOR_AUDIT_RING_MAX", "5000").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 5000
    return max(1, n)


def _max_window_hours() -> int:
    raw = os.environ.get("DIRIJOR_AUDIT_EXPORT_MAX_WINDOW_HOURS", "168").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 168
    return max(1, h)


def export_max_window_hours() -> int:
    """Public wrapper for request validation (Story 4.3)."""
    return _max_window_hours()


def _max_uncompressed_bytes() -> int:
    raw = os.environ.get(
        "DIRIJOR_AUDIT_EXPORT_MAX_UNCOMPRESSED_BYTES", str(20 * 1024 * 1024)
    ).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 20 * 1024 * 1024


def utc_iso_z_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_iso_z(value: str) -> datetime:
    s = str(value).strip()
    if not s.endswith("Z"):
        raise ValueError("timestamp must be UTC ISO-8601 with Z suffix")
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class ConsensusCompletedAuditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str | None
    consensus_score: float
    termination_reason: str
    rounds: int = Field(ge=1)
    threshold: float = Field(ge=0.0, le=1.0)
    vote_count: int = Field(ge=0)
    message_count: int = Field(ge=0)


class SafetyQuarantineAuditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    rule_id: str
    quarantined_at: str
    evidence: dict[str, Any] = Field(default_factory=dict)


def _deque_for(realm_id: str) -> deque[dict[str, Any]]:
    if realm_id not in _AUDIT_DEQUES:
        _AUDIT_DEQUES[realm_id] = deque()
    return _AUDIT_DEQUES[realm_id]


async def append_consensus_completed(
    realm_id: str, payload: ConsensusCompletedAuditPayload
) -> None:
    await _append(realm_id, "consensus.completed", payload)


async def append_quarantine_new(
    realm_id: str, payload: SafetyQuarantineAuditPayload
) -> None:
    await _append(realm_id, "safety.quarantine", payload)


async def _append(
    realm_id: str,
    event_type: Literal["consensus.completed", "safety.quarantine"],
    payload: BaseModel,
) -> None:
    cap = _ring_max()
    event: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "realm_id": realm_id,
        "type": event_type,
        "ts": utc_iso_z_now(),
        "payload": payload.model_dump(mode="json"),
    }
    async with _AUDIT_LOCK:
        d = _deque_for(realm_id)
        while len(d) >= cap:
            dropped = d.popleft()
            logger.info(
                "audit.ring_evicted",
                extra={
                    "event": "audit.ring_evicted",
                    "realm_id": realm_id,
                    "dropped_event_type": dropped.get("type"),
                },
            )
        d.append(event)


async def filtered_events(
    realm_id: str, window_start: datetime, window_end: datetime
) -> list[dict[str, Any]]:
    async with _AUDIT_LOCK:
        d = _AUDIT_DEQUES.get(realm_id)
        events = list(d) if d else []
    out: list[dict[str, Any]] = []
    for ev in events:
        t = parse_utc_iso_z(ev["ts"])
        if window_start <= t < window_end:
            out.append(ev)
    out.sort(key=lambda e: (parse_utc_iso_z(e["ts"]), e["event_id"]))
    return out


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class AuditExportTooLarge(Exception):
    """Raised when the uncompressed export estimate exceeds the configured cap."""

    def __init__(self, *, limit_bytes: int, estimated_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        self.estimated_bytes = estimated_bytes
        super().__init__(limit_bytes, estimated_bytes)


def build_audit_zip(
    *,
    export_id: str,
    realm_id: str,
    window_start: str,
    window_end: str,
    window_semantics: str,
    events: list[dict[str, Any]],
    quarantine_items: list[dict[str, Any]],
    service_version: str,
    schema_version: int,
) -> bytes:
    """Return ZIP bytes or raise AuditExportTooLarge."""

    lines = [json.dumps(ev, separators=(",", ":"), sort_keys=False) for ev in events]
    events_body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    quarantine_body = json.dumps(
        {"items": quarantine_items}, separators=(",", ":")
    ).encode("utf-8")

    member_files: list[tuple[str, bytes]] = [
        ("events.jsonl", events_body),
        ("quarantine_snapshot.json", quarantine_body),
    ]

    est = sum(len(b) for _, b in member_files)
    limit = _max_uncompressed_bytes()
    if est > limit:
        raise AuditExportTooLarge(limit_bytes=limit, estimated_bytes=est)

    files_meta: list[dict[str, Any]] = []
    for path, body in member_files:
        files_meta.append(
            {
                "path": path,
                "sha256": sha256_bytes(body),
                "bytes": len(body),
            }
        )

    created_at = utc_iso_z_now()
    manifest: dict[str, Any] = {
        "export_id": export_id,
        "realm_id": realm_id,
        "window_start": window_start,
        "window_end": window_end,
        "window_semantics": window_semantics,
        "created_at": created_at,
        "supervisor_version": service_version,
        "schema_version": schema_version,
        "manifest_schema": "dirijor.audit_export.v1",
        "files": files_meta,
        "tamper_evidence": {
            "algorithm": "none",
            "note": (
                "No cryptographic signature is attached to this bundle. "
                "SHA-256 entries in `files` are content digests for integrity "
                "checking only, not authenticity. Use network posture (private "
                "bind) until a future story adds signing."
            ),
        },
    }
    manifest_body = json.dumps(manifest, separators=(",", ":"), indent=2).encode(
        "utf-8"
    )
    est2 = est + len(manifest_body)
    if est2 > limit:
        raise AuditExportTooLarge(limit_bytes=limit, estimated_bytes=est2)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_body)
        for path, body in member_files:
            zf.writestr(path, body)
    return buf.getvalue()
