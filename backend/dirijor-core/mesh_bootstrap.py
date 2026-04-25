# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Headscale-shaped mesh bootstrap for realm spin outputs (Story 5.1).

Uses the Headscale HTTP API under ``/api/v1`` with ``Authorization: Bearer``.
All network I/O goes through an injectable ``httpx.AsyncClient`` so tests stay
hermetic via ``httpx.MockTransport``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

logger = logging.getLogger("dirijor.mesh_bootstrap")


def mesh_bootstrap_enabled() -> bool:
    """Truthiness aligned with ``DIRIJOR_AUDIT_EXPORT_ENABLED`` / safety signals."""
    raw = os.environ.get("DIRIJOR_MESH_BOOTSTRAP_ENABLED", "").strip().lower()
    return raw in ("1", "true", "yes")


def headscale_credentials_configured() -> bool:
    api = os.environ.get("DIRIJOR_HEADSCALE_API_URL", "").strip()
    key = os.environ.get("DIRIJOR_HEADSCALE_API_KEY", "").strip()
    return bool(api and key)


def control_plane_base_url() -> str:
    """Operator join URL for ``HEADSCALE_URL`` (TLS base, no ``/api/v1``)."""
    pub = os.environ.get("DIRIJOR_HEADSCALE_PUBLIC_URL", "").strip().rstrip("/")
    if pub:
        return pub
    api = os.environ.get("DIRIJOR_HEADSCALE_API_URL", "").strip().rstrip("/")
    if api.endswith("/api/v1"):
        return api[: -len("/api/v1")]
    return api


def realm_acl_tags(realm_id: str) -> list[str]:
    """Realm-scoped ACL tag namespace (applied via preauth keys)."""
    return [f"tag:dirijor:realm:{realm_id}"]


class HeadscaleMeshError(Exception):
    """Structured Headscale / bootstrap failure (no HTTP response — for try/except)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def _users_from_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "users" in data:
        return list(data["users"])
    u = data.get("user")
    if isinstance(u, dict):
        return [u]
    return []


async def _find_user_id(client: httpx.AsyncClient, realm_id: str) -> int | None:
    r = await client.get("/user", params={"name": realm_id})
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise HeadscaleMeshError(
            "mesh_headscale_api_error",
            f"list user failed: HTTP {r.status_code}",
            http_status=r.status_code,
        )
    data = r.json()
    for u in _users_from_payload(data):
        if u.get("name") == realm_id and u.get("id") is not None:
            return int(u["id"])
    return None


async def _create_user(client: httpx.AsyncClient, realm_id: str) -> int:
    r = await client.post("/user", json={"name": realm_id})
    if r.status_code >= 400:
        if r.status_code in (409, 400):
            retry = await _find_user_id(client, realm_id)
            if retry is not None:
                return retry
        raise HeadscaleMeshError(
            "mesh_headscale_api_error",
            f"create user failed: HTTP {r.status_code}",
            http_status=r.status_code,
        )
    data = r.json()
    user = data.get("user")
    if not isinstance(user, dict):
        user = data
    uid = user.get("id")
    if uid is None:
        raise HeadscaleMeshError(
            "mesh_headscale_api_error",
            "create user response missing id",
            http_status=r.status_code,
        )
    return int(uid)


async def ensure_realm_user(
    client: httpx.AsyncClient,
    realm_id: str,
    *,
    aborted: Callable[[], bool],
) -> int:
    if aborted():
        raise HeadscaleMeshError("mesh_bootstrap_aborted", "destroy requested")
    uid = await _find_user_id(client, realm_id)
    if uid is not None:
        return uid
    if aborted():
        raise HeadscaleMeshError("mesh_bootstrap_aborted", "destroy requested")
    return await _create_user(client, realm_id)


def preauth_ttl_seconds() -> int:
    raw = os.environ.get("DIRIJOR_MESH_PREAUTH_TTL_SECONDS", "1800").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 1800
    return max(60, min(n, 86400 * 7))


async def bootstrap_ready_realm(
    *,
    realm_id: str,
    correlation_id: str,
    aborted: Callable[[], bool],
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Return ``outputs`` patch (``mesh``, ``headscale_control_url``)."""
    user_id = await ensure_realm_user(client, realm_id, aborted=aborted)
    if aborted():
        raise HeadscaleMeshError("mesh_bootstrap_aborted", "destroy requested")
    tags = realm_acl_tags(realm_id)
    control = control_plane_base_url()
    mesh: dict[str, Any] = {
        "status": "ready",
        "headscale_user_id": user_id,
        "headscale_user_name": realm_id,
        "realm_tags": tags,
        "correlation_id": correlation_id,
    }
    return {
        "mesh": mesh,
        "headscale_control_url": control,
    }


async def issue_preauth_key(
    *,
    user_id: int,
    realm_id: str,
    client: httpx.AsyncClient,
) -> tuple[str, str]:
    """Create a one-shot preauth key; returns ``(key, expiration_iso_z)``."""
    exp = datetime.now(timezone.utc) + timedelta(seconds=preauth_ttl_seconds())
    exp_iso = exp.strftime("%Y-%m-%dT%H:%M:%SZ")
    tags = realm_acl_tags(realm_id)
    body: dict[str, Any] = {
        "user": user_id,
        "reusable": False,
        "ephemeral": False,
        "expiration": exp_iso,
        "aclTags": tags,
    }
    r = await client.post("/preauthkey", json=body)
    if r.status_code >= 400:
        raise HeadscaleMeshError(
            "mesh_headscale_api_error",
            f"preauthkey create failed: HTTP {r.status_code}",
            http_status=r.status_code,
        )
    data = r.json()
    pak = data.get("preAuthKey") or data.get("pre_auth_key") or {}
    if not isinstance(pak, dict):
        pak = {}
    key = pak.get("key")
    if not key:
        raise HeadscaleMeshError(
            "mesh_headscale_api_error",
            "preauthkey response missing key",
            http_status=r.status_code,
        )
    exp_out = pak.get("expiration")
    exp_str = exp_iso
    if isinstance(exp_out, dict) and "seconds" in exp_out:
        exp_str = datetime.fromtimestamp(
            int(exp_out["seconds"]), tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(exp_out, str) and exp_out:
        exp_str = exp_out
    return str(key), exp_str


def _node_tag_values(node: dict[str, Any]) -> set[str]:
    tags: set[str] = set()
    for key in (
        "validTags",
        "forcedTags",
        "tags",
        "aclTags",
        "advertisedTags",
        "advertiseTags",
    ):
        raw = node.get(key)
        if isinstance(raw, str):
            tags.add(raw)
        elif isinstance(raw, list):
            tags.update(str(x) for x in raw if x is not None)
    return tags


async def list_realm_tagged_nodes(
    client: httpx.AsyncClient, realm_id: str
) -> list[dict[str, Any]]:
    """Headscale ``GET /api/v1/node`` — filter to active realm-tagged nodes."""
    r = await client.get("/node")
    if r.status_code >= 400:
        raise HeadscaleMeshError(
            "mesh_headscale_api_error",
            f"list node failed: HTTP {r.status_code}",
            http_status=r.status_code,
        )
    data = r.json() if r.content else {}
    if not isinstance(data, dict):
        return []
    raw = data.get("nodes")
    if raw is None:
        raw = data.get("node")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    realm_tag = realm_acl_tags(realm_id)[0]
    for n in raw:
        if not isinstance(n, dict):
            continue
        if realm_tag in _node_tag_values(n):
            out.append(n)
    return out


async def list_realm_user_nodes(
    client: httpx.AsyncClient, realm_id: str
) -> list[dict[str, Any]]:
    """Compatibility wrapper; Story 9.2 topology is realm-tag based."""
    return await list_realm_tagged_nodes(client, realm_id)


def log_bootstrap_finished(
    *,
    realm_id: str,
    job_id: str,
    correlation_id: str,
    status: str,
    code: str | None = None,
) -> None:
    """Structured log line — never pass secrets or raw Headscale responses."""
    extra: dict[str, object] = {
        "event": "mesh.bootstrap.done",
        "realm_id": realm_id,
        "job_id": job_id,
        "correlation_id": correlation_id,
        "mesh_status": status,
    }
    if code:
        extra["mesh_code"] = code
    (logger.warning if status == "failed" else logger.info)(
        "mesh.bootstrap.done",
        extra=extra,
    )
