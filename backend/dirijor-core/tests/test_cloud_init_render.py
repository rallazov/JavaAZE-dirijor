# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 9.2 — hermetic render checks for the DO droplet cloud-init template."""

from __future__ import annotations

import hashlib
import re
import secrets
import string
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_template() -> str:
    p = (
        _repo_root()
        / "terraform"
        / "modules"
        / "private-realm"
        / "cloud-init"
        / "agent.yaml.tftpl"
    )
    return p.read_text(encoding="utf-8")


def _render_like_terraform(
    src: str,
    *,
    preauth_key: str,
    headscale_login_url: str,
    wrapper_image: str,
    realm_id: str,
) -> str:
    """Terraform ``templatefile``-equivalent for the variables we interpolate."""
    return (
        src.replace("${preauth_key}", preauth_key)
        .replace("${headscale_login_url}", headscale_login_url)
        .replace("${wrapper_image}", wrapper_image)
        .replace("${realm_id}", realm_id)
    )


def _strip_volatile(s: str) -> str:
    return re.sub(
        r"tag:dirijor:realm:[^\s]+", "tag:dirijor:realm:REALM", s
    )


def test_cloud_init_authkey_only_in_approved_paths() -> None:
    alphabet = string.ascii_letters + string.digits
    fake = (
        "hskey:unit_long_random_"
        + "".join(secrets.choice(alphabet) for _ in range(32))
    )
    t = _read_template()
    out = _render_like_terraform(
        t,
        preauth_key=fake,
        headscale_login_url="https://headscale.test",
        wrapper_image="ghcr.io/javaaze/openclaw-wrapper:pinned",
        realm_id="realm-abc-123",
    )
    # Single canonical occurrence in root-only file body (or tailscale up path).
    assert out.count(fake) == 1, "preauth should appear once in the rendered payload"
    assert "  - curl" in out
    assert 'docker pull "ghcr.io/javaaze/openclaw-wrapper:pinned"' in out
    assert '--net=host "ghcr.io/javaaze/openclaw-wrapper:pinned"' in out
    assert "write_files" in out and "dirijor-preauth" in out
    assert "set -euo" in out
    assert not re.search(r"^\s*set\s+-x", out, re.MULTILINE)
    for bad in (
        f"echo {fake}",
        f"# {fake}",
    ):
        assert bad not in out
    assert "echo" not in out


def test_cloud_init_redacted_hash_stable_regression() -> None:
    t = _read_template()
    out = _render_like_terraform(
        t,
        preauth_key="__REDACTED__",
        headscale_login_url="https://headscale.test",
        wrapper_image="ghcr.io/wrapper:tag",
        realm_id="realm-fixture",
    )
    digest = hashlib.sha256(
        _strip_volatile(out).encode("utf-8")
    ).hexdigest()
    assert (
        digest
        == "8c23f90f987c68941aaf0731e4c61a44fb02aa0ecb45ae4371d0779a4c4d32c7"
    )
