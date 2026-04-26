# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 9.4 — supervisor mesh argv / config rendering (hermetic, no network)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import supervisor
import supervisor_mesh as sm


def test_supervisor_mesh_disabled_by_default() -> None:
    assert sm.supervisor_mesh_enabled() is False


def test_build_tailscale_argv_shapes() -> None:
    td = sm.build_tailscaled_argv(state_dir=Path("/tmp/ts-state"))
    assert td[0] == "tailscaled"
    assert any(x.startswith("--state=") for x in td)
    assert "--tun=userspace-networking" in td
    assert any(x.startswith("--socket=") for x in td)

    up = sm.build_tailscale_up_argv(
        login_server="https://hs.example.com",
        authkey_placeholder="<redacted>",
    )
    assert up[:2] == ["tailscale", f"--socket={sm.tailscale_socket_path()}"]
    assert "up" in up
    assert "--login-server=https://hs.example.com" in up
    assert "--authkey=<redacted>" in up
    assert "--advertise-tags=tag:dirijor:realm:supervisor" in up
    assert "--accept-routes=false" in up

    serve = sm.build_tailscale_serve_argv(local_port=8000)
    assert serve[0] == "tailscale"
    assert "serve" in serve
    assert "--bg" in serve
    assert "--yes" in serve
    assert serve[-1] == "8000"


def test_serve_config_json_proxy_target() -> None:
    doc = sm.serve_config_json(local_port=8000, cert_domain="supervisor.dirijor.internal")
    assert doc["TCP"]["443"]["HTTPS"] is True
    h = doc["Web"]["supervisor.dirijor.internal:443"]["Handlers"]["/"]
    assert h["Proxy"] == "http://127.0.0.1:8000"


def test_login_server_uses_control_plane_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIRIJOR_HEADSCALE_PUBLIC_URL", "https://cp.example")
    monkeypatch.delenv("DIRIJOR_HEADSCALE_API_URL", raising=False)
    assert sm.login_server_url() == "https://cp.example"


@pytest.mark.parametrize("flag", ["1", "true", "yes"])
def test_mesh_enabled_truthy(flag: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIRIJOR_SUPERVISOR_MESH_ENABLED", flag)
    assert sm.supervisor_mesh_enabled() is True


def test_health_503_when_mesh_enabled_without_authkey(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIRIJOR_SUPERVISOR_MESH_ENABLED", "1")
    monkeypatch.delenv("DIRIJOR_SUPERVISOR_AUTHKEY", raising=False)
    monkeypatch.setattr(supervisor, "STARTED_AT", time.monotonic() - 10.0)
    with TestClient(supervisor.app) as client:
        r = client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["checks"]["supervisor_mesh"]["ready"] is False
    assert "AUTHKEY" in (body["checks"]["supervisor_mesh"]["detail"] or "")


def test_health_ok_when_mesh_dry_run_with_authkey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIRIJOR_SUPERVISOR_MESH_ENABLED", "1")
    monkeypatch.setenv("DIRIJOR_SUPERVISOR_AUTHKEY", "hskey:opaque-test-placeholder")
    monkeypatch.setenv("DIRIJOR_SUPERVISOR_MESH_DRY_RUN", "1")
    with TestClient(supervisor.app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["checks"]["supervisor_mesh"]["ready"] is True
