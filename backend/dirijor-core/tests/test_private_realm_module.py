# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Hermetic assertions on Story 2.3 terraform module sources (no terraform binary).

AC 8: module egress logic is pinned without `terraform validate` in CI when
the binary is unavailable.
"""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_private_realm_main_tf_firewall_realm_egress_default_deny_structure() -> None:
    main_tf = _repo_root() / "terraform" / "modules" / "private-realm" / "main.tf"
    text = _read(main_tf)
    assert 'resource "digitalocean_firewall" "realm_egress"' in text
    assert "local.private_cidrs" in text
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        assert cidr in text, f"missing RFC1918 block {cidr}"
    assert text.count('destination_addresses = local.private_cidrs') >= 3
    assert 'for_each = var.allow_public_egress ? [1] : []' in text
    assert text.count('dynamic "outbound_rule"') == 3
    assert '"0.0.0.0/0"' in text and '"::/0"' in text


def test_private_realm_variables_allow_public_egress_defaults_false() -> None:
    vtf = _repo_root() / "terraform" / "modules" / "private-realm" / "variables.tf"
    text = _read(vtf)
    assert 'variable "allow_public_egress"' in text
    assert "default     = false" in text or "default = false" in text
