# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 5.1 — mesh bootstrap (hermetic Headscale mocks)."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import mesh_bootstrap as mb
import supervisor

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_httpx_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Force mock transport on the supervisor's httpx module binding.

    ``monkeypatch.setattr(httpx, "AsyncClient", ...)`` would poison the shared
    ``httpx`` module — always delegate to ``_REAL_ASYNC_CLIENT``.
    """

    def _factory(**kwargs: object) -> httpx.AsyncClient:
        merged = {**kwargs, "transport": transport}
        return _REAL_ASYNC_CLIENT(**merged)

    monkeypatch.setattr(supervisor.httpx, "AsyncClient", _factory)


def _hs_handler_ok(realm_id: str):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/user"):
            return httpx.Response(200, json={"users": []})
        if request.method == "POST" and path.rstrip("/").endswith("/user"):
            body = (
                json.loads(request.content.decode())
                if request.content
                else {}
            )
            name = body.get("name", "")
            return httpx.Response(
                200, json={"user": {"id": 42, "name": name}}
            )
        if request.method == "POST" and "preauthkey" in path:
            return httpx.Response(
                200,
                json={
                    "preAuthKey": {
                        "key": "hskey:stub",
                        "expiration": "2099-01-01T00:00:00Z",
                    }
                },
            )
        return httpx.Response(500, text=f"unexpected {request.method} {path}")

    return handler


def test_bootstrap_ready_creates_user_via_mock(monkeypatch):
    monkeypatch.setenv(
        "DIRIJOR_HEADSCALE_API_URL", "http://headscale.test/api/v1"
    )
    realm_id = "realm-unit-abc"
    tr = httpx.MockTransport(_hs_handler_ok(realm_id))

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=tr,
            base_url="http://headscale.test/api/v1",
            headers={"Authorization": "Bearer t"},
        ) as client:
            patch = await mb.bootstrap_ready_realm(
                realm_id=realm_id,
                correlation_id="corr-1",
                aborted=lambda: False,
                client=client,
            )
        assert patch["mesh"]["status"] == "ready"
        assert patch["mesh"]["headscale_user_id"] == 42
        assert patch["headscale_control_url"]

    asyncio.run(_run())


def test_bootstrap_aborted_skips_headscale():
    tr = httpx.MockTransport(
        lambda r: httpx.Response(500, text="should not be called")
    )

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=tr,
            base_url="http://headscale.test/api/v1",
        ) as client:
            with pytest.raises(mb.HeadscaleMeshError) as ei:
                await mb.bootstrap_ready_realm(
                    realm_id="r",
                    correlation_id="c",
                    aborted=lambda: True,
                    client=client,
                )
            assert ei.value.code == "mesh_bootstrap_aborted"

    asyncio.run(_run())


def test_headscale_api_error_surfaces():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(500, text="hs down")
        return httpx.Response(500)

    tr = httpx.MockTransport(handler)

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=tr, base_url="http://hs/api/v1"
        ) as client:
            with pytest.raises(mb.HeadscaleMeshError) as ei:
                await mb.ensure_realm_user(client, "r1", aborted=lambda: False)
            assert ei.value.code == "mesh_headscale_api_error"

    asyncio.run(_run())


def test_mesh_gate_off_preserves_outputs(monkeypatch):
    monkeypatch.delenv("DIRIJOR_MESH_BOOTSTRAP_ENABLED", raising=False)
    monkeypatch.delenv("DIRIJOR_HEADSCALE_API_URL", raising=False)
    monkeypatch.delenv("DIRIJOR_HEADSCALE_API_KEY", raising=False)
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)
    with TestClient(supervisor.app) as client:
        r = client.post(
            "/realms/spin",
            json={"realm_description": "m", "adapter_hint": "local-noop"},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        for _ in range(80):
            g = client.get(f"/realms/{job_id}")
            assert g.status_code == 200
            if g.json()["phase"] == "ready":
                assert "mesh" not in g.json()["outputs"]
                return
        pytest.fail("job did not reach ready")


def test_mesh_gate_on_config_missing(monkeypatch):
    monkeypatch.setenv("DIRIJOR_MESH_BOOTSTRAP_ENABLED", "1")
    monkeypatch.delenv("DIRIJOR_HEADSCALE_API_URL", raising=False)
    monkeypatch.delenv("DIRIJOR_HEADSCALE_API_KEY", raising=False)
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)
    with TestClient(supervisor.app) as client:
        r = client.post(
            "/realms/spin",
            json={"realm_description": "m", "adapter_hint": "local-noop"},
        )
        job_id = r.json()["job_id"]
        for _ in range(80):
            g = client.get(f"/realms/{job_id}")
            body = g.json()
            if body["phase"] == "ready":
                mesh = body["outputs"].get("mesh")
                assert isinstance(mesh, dict)
                assert mesh["status"] == "failed"
                assert mesh["code"] == "mesh_headscale_config_missing"
                return
        pytest.fail("job did not reach ready")


def test_mesh_happy_path_broadcast(monkeypatch):
    monkeypatch.setenv("DIRIJOR_MESH_BOOTSTRAP_ENABLED", "1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_URL", "http://hs.test/api/v1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_KEY", "secret")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_PUBLIC_URL", "https://hs.example.com")
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)

    tr = httpx.MockTransport(_hs_handler_ok("ignored"))
    _patch_httpx_client(monkeypatch, tr)

    seen: list[tuple[str, dict]] = []

    async def _cap(realm_id: str, event_type: str, payload: dict):
        seen.append((event_type, payload))
        return 0

    monkeypatch.setattr(supervisor, "broadcast_event", _cap)

    with TestClient(supervisor.app) as client:
        r = client.post(
            "/realms/spin",
            json={"realm_description": "m", "adapter_hint": "local-noop"},
        )
        job_id = r.json()["job_id"]
        realm_id = r.json()["realm_id"]
        for _ in range(80):
            g = client.get(f"/realms/{job_id}")
            body = g.json()
            if body["phase"] == "ready" and body["outputs"].get(
                "mesh", {}
            ).get("status") == "ready":
                break
        else:
            pytest.fail("mesh did not become ready")

        assert any(
            et == "realm.mesh.state" and p.get("status") == "ready"
            for et, p in seen
        )
        final = client.get(f"/realms/{job_id}").json()
        assert (
            final["outputs"]["headscale_control_url"]
            == "https://hs.example.com"
        )
        assert final["outputs"]["mesh_endpoint"].startswith("noop://")
        assert final["outputs"]["mesh"]["headscale_user_name"] == realm_id


def test_mesh_api_failure_in_outputs(monkeypatch):
    monkeypatch.setenv("DIRIJOR_MESH_BOOTSTRAP_ENABLED", "1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_URL", "http://hs.test/api/v1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_KEY", "k")
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/user" in str(request.url):
            return httpx.Response(200, json={"users": []})
        if request.method == "POST" and request.url.path.endswith("/user"):
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(500)

    tr = httpx.MockTransport(handler)
    _patch_httpx_client(monkeypatch, tr)

    with TestClient(supervisor.app) as client:
        r = client.post(
            "/realms/spin",
            json={"realm_description": "m", "adapter_hint": "local-noop"},
        )
        job_id = r.json()["job_id"]
        for _ in range(80):
            g = client.get(f"/realms/{job_id}")
            body = g.json()
            if body["phase"] == "ready":
                m = body["outputs"].get("mesh", {})
                if m.get("status") == "failed":
                    assert m.get("code") == "mesh_headscale_api_error"
                    return
        pytest.fail("mesh did not fail as expected")


def test_preauth_ttl_default_1800(monkeypatch):
    monkeypatch.delenv("DIRIJOR_MESH_PREAUTH_TTL_SECONDS", raising=False)
    assert mb.preauth_ttl_seconds() == 1800


def test_list_realm_tagged_nodes_filters_by_realm_tag():
    tr = httpx.MockTransport(
        lambda r: httpx.Response(
            200,
            json={
                "nodes": [
                    {
                        "id": "1",
                        "user": {"name": "r1"},
                        "validTags": ["tag:dirijor:realm:r1"],
                    },
                    {"id": "2", "user": {"name": "r1"}},
                    {
                        "id": "3",
                        "user": {"name": "other"},
                        "validTags": ["tag:dirijor:realm:other"],
                    },
                ]
            },
        )
    )

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=tr, base_url="http://h/api/v1"
        ) as c:
            n = await mb.list_realm_tagged_nodes(c, "r1")
        assert len(n) == 1
        assert n[0]["id"] == "1"

    asyncio.run(_run())


def test_list_realm_tagged_nodes_rejects_non_json_200():
    tr = httpx.MockTransport(lambda r: httpx.Response(200, text="not json"))

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=tr, base_url="http://h/api/v1"
        ) as c:
            with pytest.raises(mb.HeadscaleMeshError) as ei:
                await mb.list_realm_tagged_nodes(c, "r1")
        assert ei.value.code == "mesh_headscale_api_error"
        assert "not valid JSON" in ei.value.message

    asyncio.run(_run())


def _hs_handler_topology() -> object:
    last_realm: list[str] = ["unset"]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        u = str(request.url)
        if request.method == "GET" and path.endswith("/user") and "name=" in u:
            from urllib.parse import parse_qs, urlparse

            name = parse_qs(urlparse(u).query).get("name", [""])[0]
            if name:
                last_realm[0] = name
            return httpx.Response(200, json={"users": []})
        if request.method == "POST" and path.rstrip("/").endswith("/user"):
            body = (
                json.loads(request.content.decode())
                if request.content
                else {}
            )
            n = body.get("name", "")
            if n:
                last_realm[0] = n
            return httpx.Response(
                200, json={"user": {"id": 99, "name": n}}
            )
        if request.method == "POST" and "preauthkey" in path:
            return httpx.Response(
                200,
                json={
                    "preAuthKey": {
                        "key": "hskey:stub",
                        "expiration": "2099-01-01T00:00:00Z",
                    }
                },
            )
        if request.method == "GET" and path.rstrip("/").endswith("node"):
            r = last_realm[0]
            return httpx.Response(
                200,
                json={
                    "nodes": [
                        {
                            "id": "n-1",
                            "name": "n1",
                            "online": True,
                            "user": {"id": 1, "name": r},
                            "validTags": [f"tag:dirijor:realm:{r}"],
                        },
                        {
                            "id": "untagged",
                            "name": "untagged",
                            "online": True,
                            "user": {"id": 1, "name": r},
                        },
                    ]
                },
            )
        return httpx.Response(500, text=f"unexpected {request.method} {path}")

    return handler


def test_headscale_topology_agent_patch_uses_canvas_safe_statuses() -> None:
    online = supervisor._agent_patch_from_headscale_node(
        {"id": "n1", "name": "agent-1", "online": True}
    )
    offline = supervisor._agent_patch_from_headscale_node(
        {"id": "n2", "name": "agent-2", "online": False}
    )
    online_int = supervisor._agent_patch_from_headscale_node(
        {"id": "n1-int", "name": "agent-1-int", "online": 1}
    )
    offline_int = supervisor._agent_patch_from_headscale_node(
        {"id": "n2-int", "name": "agent-2-int", "online": 0}
    )
    unknown = supervisor._agent_patch_from_headscale_node(
        {"id": "n3", "name": "agent-3"}
    )
    fallback_name = supervisor._agent_patch_from_headscale_node(
        {"id": "", "name": "agent-name", "online": True}
    )
    missing_id = supervisor._agent_patch_from_headscale_node(
        {"id": 0, "name": "", "online": True}
    )

    assert online is not None
    assert online["status"] == "healthy"
    assert online["safetyScore"] == 1.0
    assert online["meshOnline"] is True
    assert offline is not None
    assert offline["status"] == "degraded"
    assert offline["safetyScore"] == 0.5
    assert offline["meshOnline"] is False
    assert online_int is not None
    assert online_int["status"] == "healthy"
    assert online_int["meshOnline"] is True
    assert offline_int is not None
    assert offline_int["status"] == "degraded"
    assert offline_int["meshOnline"] is False
    assert unknown is not None
    assert unknown["status"] == "pending"
    assert unknown["safetyScore"] == 0.5
    assert fallback_name is not None
    assert fallback_name["id"] == "agent-name"
    assert missing_id is None


def test_topology_delta_from_headscale_node_poll(monkeypatch):
    """Story 9.2: mocked /node yields one topology.delta for matching realm user."""
    monkeypatch.setenv("DIRIJOR_MESH_BOOTSTRAP_ENABLED", "1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_URL", "http://hs.test/api/v1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_KEY", "secret")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_PUBLIC_URL", "https://hs.example.com")
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)
    tr = httpx.MockTransport(_hs_handler_topology())
    _patch_httpx_client(monkeypatch, tr)

    seen: list[tuple[str, dict]] = []
    got_topology = threading.Event()

    async def _cap(realm_id: str, event_type: str, payload: dict):
        seen.append((event_type, payload))
        if event_type == "topology.delta":
            got_topology.set()
        return 0

    monkeypatch.setattr(supervisor, "broadcast_event", _cap)

    with TestClient(supervisor.app) as client:
        client.post(
            "/realms/spin",
            json={"realm_description": "m", "adapter_hint": "local-noop"},
        )
        assert got_topology.wait(
            timeout=5
        ), "topology.delta not broadcast within window"
    topo = [p for et, p in seen if et == "topology.delta"]
    assert any(len(p.get("agents", [])) > 0 for p in topo)
    assert any(p.get("source") == "headscale" for p in topo)
    agent_ids = {a["id"] for p in topo for a in p.get("agents", [])}
    assert "n-1" in agent_ids
    assert "untagged" not in agent_ids
    assert any(
        a.get("status") == "healthy" and a.get("meshOnline") is True
        for p in topo
        for a in p.get("agents", [])
    )


def test_preauth_key_one_shot(monkeypatch):
    monkeypatch.setenv("DIRIJOR_MESH_BOOTSTRAP_ENABLED", "1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_URL", "http://hs.test/api/v1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_KEY", "k")
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)
    tr = httpx.MockTransport(_hs_handler_ok("x"))
    _patch_httpx_client(monkeypatch, tr)

    with TestClient(supervisor.app) as client:
        r = client.post(
            "/realms/spin",
            json={"realm_description": "m", "adapter_hint": "local-noop"},
        )
        job_id = r.json()["job_id"]
        for _ in range(80):
            body = client.get(f"/realms/{job_id}").json()
            if (
                body["phase"] == "ready"
                and body["outputs"].get("mesh", {}).get("status") == "ready"
            ):
                break
        else:
            pytest.fail("timeout")

        p1 = client.post(f"/realms/{job_id}/mesh/preauth-key")
        assert p1.status_code == 200
        assert p1.json()["preauth_key"] == "hskey:stub"
        p2 = client.post(f"/realms/{job_id}/mesh/preauth-key")
        assert p2.status_code == 410
        assert p2.json()["code"] == "mesh_preauth_consumed"


def test_mesh_retry_idempotent(monkeypatch):
    monkeypatch.setenv("DIRIJOR_MESH_BOOTSTRAP_ENABLED", "1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_URL", "http://hs.test/api/v1")
    monkeypatch.setenv("DIRIJOR_HEADSCALE_API_KEY", "k")
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0.01)
    tr = httpx.MockTransport(_hs_handler_ok("x"))
    _patch_httpx_client(monkeypatch, tr)
    with TestClient(supervisor.app) as client:
        r = client.post(
            "/realms/spin",
            json={"realm_description": "m", "adapter_hint": "local-noop"},
        )
        job_id = r.json()["job_id"]
        for _ in range(80):
            body = client.get(f"/realms/{job_id}").json()
            if (
                body["phase"] == "ready"
                and body["outputs"].get("mesh", {}).get("status") == "ready"
            ):
                break
        else:
            pytest.fail("timeout")
        rr = client.post(f"/realms/{job_id}/mesh/retry")
        assert rr.status_code == 200
        assert rr.json()["status"] == "accepted"
