# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Supervisor Headscale mesh sidecar (Story 9.4).

Runs ``tailscaled`` with userspace networking and ``tailscale up`` / ``serve``
so realm agents on default-deny egress can reach Core over the tailnet.

Hermetic tests assert argv / config **shapes** only — never log or assert real
preauth material.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import mesh_bootstrap as mesh_bootstrap_lib

logger = logging.getLogger("dirijor.supervisor_mesh")

_SUPERVISOR_MESH_TAG = "tag:dirijor:realm:supervisor"

_runtime_ready: bool = False
_startup_error: str | None = None
_tailscaled_proc: subprocess.Popen[bytes] | None = None


def supervisor_mesh_enabled() -> bool:
    """Truthiness aligned with ``DIRIJOR_MESH_BOOTSTRAP_ENABLED`` / audit export."""
    raw = os.environ.get("DIRIJOR_SUPERVISOR_MESH_ENABLED", "").strip().lower()
    return raw in ("1", "true", "yes")


def supervisor_mesh_dry_run() -> bool:
    raw = os.environ.get("DIRIJOR_SUPERVISOR_MESH_DRY_RUN", "").strip().lower()
    return raw in ("1", "true", "yes")


def supervisor_mesh_authkey() -> str:
    return os.environ.get("DIRIJOR_SUPERVISOR_AUTHKEY", "").strip()


def supervisor_listen_port() -> int:
    raw = os.environ.get("DIRIJOR_SUPERVISOR_PORT", "8000").strip()
    try:
        return int(raw)
    except ValueError:
        return 8000


def tailscale_state_dir() -> Path:
    return Path(
        os.environ.get("DIRIJOR_SUPERVISOR_TS_STATE_DIR", "/var/lib/dirijor-tailscale")
    ).expanduser()


def tailscale_socket_path() -> str:
    return os.environ.get(
        "DIRIJOR_SUPERVISOR_TS_SOCKET", "/tmp/dirijor-tailscaled.sock"
    )


def default_supervisor_mesh_api_base() -> str:
    """Documented default for operator / tfvars (MagicDNS under Story 9.3 recipe)."""
    host = os.environ.get("DIRIJOR_SUPERVISOR_MESH_HOSTNAME", "").strip()
    if host:
        return f"http://{host}:{supervisor_listen_port()}"
    return f"http://supervisor.dirijor.internal:{supervisor_listen_port()}"


def default_supervisor_mesh_ws_base() -> str:
    host = os.environ.get("DIRIJOR_SUPERVISOR_MESH_HOSTNAME", "").strip()
    h = host or "supervisor.dirijor.internal"
    return f"ws://{h}:{supervisor_listen_port()}"


def login_server_url() -> str:
    """Reuse agent join base (``DIRIJOR_HEADSCALE_PUBLIC_URL`` / API strip)."""
    return mesh_bootstrap_lib.control_plane_base_url().strip().rstrip("/")


def build_tailscaled_argv(*, state_dir: Path | None = None) -> list[str]:
    st = state_dir or tailscale_state_dir()
    return [
        "tailscaled",
        f"--state={st}",
        "--tun=userspace-networking",
        f"--socket={tailscale_socket_path()}",
    ]


def build_tailscale_up_argv(
    *,
    login_server: str,
    authkey_placeholder: str,
    socket_path: str | None = None,
) -> list[str]:
    """Argv for ``tailscale up`` (use a redacted placeholder in tests)."""
    sock = socket_path or tailscale_socket_path()
    return [
        "tailscale",
        f"--socket={sock}",
        "up",
        f"--login-server={login_server}",
        f"--authkey={authkey_placeholder}",
        f"--advertise-tags={_SUPERVISOR_MESH_TAG}",
        "--accept-routes=false",
    ]


def build_tailscale_serve_argv(
    *,
    local_port: int,
    socket_path: str | None = None,
) -> list[str]:
    """Expose loopback HTTP on ``local_port`` to the tailnet via Serve (HTTPS)."""
    sock = socket_path or tailscale_socket_path()
    return [
        "tailscale",
        f"--socket={sock}",
        "serve",
        "--bg",
        "--yes",
        str(local_port),
    ]


def serve_config_json(*, local_port: int, cert_domain: str) -> dict[str, Any]:
    """Shape-only helper for ``TS_SERVE_CONFIG`` (operators substitute ``cert_domain``)."""
    key = f"{cert_domain}:443"
    return {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {
            key: {
                "Handlers": {
                    "/": {"Proxy": f"http://127.0.0.1:{local_port}"},
                }
            }
        },
    }


def runtime_ready() -> bool:
    return _runtime_ready


def startup_error() -> str | None:
    return _startup_error


def _reset_runtime_state() -> None:
    global _runtime_ready, _startup_error, _tailscaled_proc
    _runtime_ready = False
    _startup_error = None
    _tailscaled_proc = None


def _which_or_none(name: str) -> str | None:
    return shutil.which(name)


def _run_checked(argv: list[str], *, timeout_s: float = 120.0) -> None:
    r = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if len(err) > 400:
            err = err[:397] + "..."
        raise RuntimeError(f"{' '.join(argv[:3])}... exited {r.returncode}: {err}")


async def ensure_sidecar_started_async() -> None:
    """Lifespan hook: start tailscaled + up + serve when mesh mode is on."""
    global _runtime_ready, _startup_error, _tailscaled_proc

    _reset_runtime_state()
    if not supervisor_mesh_enabled():
        _runtime_ready = True
        return
    if not supervisor_mesh_authkey():
        logger.error(
            "supervisor_mesh.authkey_missing",
            extra={"event": "supervisor_mesh.authkey_missing"},
        )
        _startup_error = "DIRIJOR_SUPERVISOR_AUTHKEY missing or blank"
        return
    if supervisor_mesh_dry_run():
        _runtime_ready = True
        return

    td = _which_or_none("tailscaled")
    ts = _which_or_none("tailscale")
    if not td or not ts:
        _startup_error = "tailscaled or tailscale not found in PATH"
        logger.error(
            "supervisor_mesh.binary_missing",
            extra={"event": "supervisor_mesh.binary_missing"},
        )
        return

    state = tailscale_state_dir()
    try:
        state.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _startup_error = f"state dir {state}: {exc}"
        return

    sock = Path(tailscale_socket_path())
    sock.parent.mkdir(parents=True, exist_ok=True)
    if sock.exists():
        try:
            sock.unlink()
        except OSError:
            pass

    tail_argv = build_tailscaled_argv(state_dir=state)
    tail_argv[0] = td
    try:
        _tailscaled_proc = subprocess.Popen(
            tail_argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        _startup_error = f"tailscaled start failed: {exc}"
        return

    # Wait for socket
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if sock.exists():
            break
        if _tailscaled_proc.poll() is not None:
            _startup_error = "tailscaled exited early (see container logs / stderr)"
            _tailscaled_proc = None
            return
        await asyncio.sleep(0.1)
    else:
        _startup_error = "tailscaled socket did not appear in time"
        await shutdown_sidecar_async()
        return

    up_argv = build_tailscale_up_argv(
        login_server=login_server_url(),
        authkey_placeholder=supervisor_mesh_authkey(),
    )
    up_argv[0] = ts
    serve_argv = build_tailscale_serve_argv(local_port=supervisor_listen_port())
    serve_argv[0] = ts

    try:
        await asyncio.to_thread(_run_checked, up_argv)
        await asyncio.to_thread(_run_checked, serve_argv, timeout_s=60.0)
    except Exception as exc:  # noqa: BLE001 — surface to readiness
        _startup_error = f"{type(exc).__name__}: {exc}"
        logger.exception("supervisor_mesh.sidecar_failed")
        await shutdown_sidecar_async()
        return

    _runtime_ready = True


async def shutdown_sidecar_async() -> None:
    global _tailscaled_proc, _runtime_ready
    proc = _tailscaled_proc
    _tailscaled_proc = None
    _runtime_ready = False
    if proc is None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            proc.kill()
    except OSError:
        pass
