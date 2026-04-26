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


def test_private_realm_story_9_1_droplet_and_ssh_key_resources() -> None:
    root = _repo_root()
    main_tf = _read(root / "terraform" / "modules" / "private-realm" / "main.tf")
    assert 'resource "digitalocean_droplet" "agent"' in main_tf
    assert "count = var.agent_count" in main_tf
    tag_lit = 'tags = ["dirijor-realm-${var.realm_name}"]'
    assert main_tf.count(tag_lit) == 2
    assert 'vpc_uuid = digitalocean_vpc.realm_vpc.id' in main_tf
    assert 'ssh_keys = [digitalocean_ssh_key.operator.fingerprint]' in main_tf
    assert 'image    = "ubuntu-22-04-x64"' in main_tf
    assert 'size     = "s-1vcpu-512mb-10gb"' in main_tf
    assert 'region   = "nyc3"' in main_tf
    assert 'resource "digitalocean_ssh_key" "operator"' in main_tf
    assert "public_key = var.ssh_public_key" in main_tf
    assert "depends_on = [" in main_tf
    assert "digitalocean_vpc.realm_vpc" in main_tf
    assert "digitalocean_firewall.realm_egress" in main_tf
    d0 = main_tf.index('resource "digitalocean_droplet" "agent"')
    droplet_chunk = main_tf[d0:]
    assert droplet_chunk.count("tags =") == 1
    assert tag_lit in droplet_chunk
    assert '"0.0.0.0/0"' not in droplet_chunk
    assert "templatefile(" in main_tf
    assert "cloud-init/agent.yaml.tftpl" in main_tf
    assert "var.agent_preauth_keys[count.index]" in main_tf


def test_private_realm_story_9_2_mesh_variables() -> None:
    vtf = _read(
        _repo_root() / "terraform" / "modules" / "private-realm" / "variables.tf"
    )
    for name in (
        "headscale_login_url",
        "wrapper_image",
        "agent_preauth_keys",
    ):
        assert f'variable "{name}"' in vtf
    block = vtf.split('variable "agent_preauth_keys"', 1)[1]
    assert "sensitive" in block[:500]
    assert "length(var.agent_preauth_keys) == var.agent_count" in vtf


def test_private_realm_story_9_4_supervisor_callback_variables() -> None:
    vtf = _read(
        _repo_root() / "terraform" / "modules" / "private-realm" / "variables.tf"
    )
    assert 'variable "supervisor_api_url"' in vtf
    assert 'variable "supervisor_ws_url"' in vtf
    api_block = vtf.split('variable "supervisor_api_url"', 1)[1].split(
        'variable "supervisor_ws_url"', 1
    )[0]
    assert "default" in api_block and '""' in api_block


def test_private_realm_story_9_1_outputs_splat() -> None:
    otf = _read(_repo_root() / "terraform" / "modules" / "private-realm" / "outputs.tf")
    assert 'output "agent_droplet_ids"' in otf
    assert 'output "agent_private_ipv4s"' in otf
    assert "digitalocean_droplet.agent[*].id" in otf
    assert "digitalocean_droplet.agent[*].ipv4_address_private" in otf


def test_private_realm_story_9_1_ssh_variable_no_default() -> None:
    vtf = _read(_repo_root() / "terraform" / "modules" / "private-realm" / "variables.tf")
    assert 'variable "ssh_public_key"' in vtf
    head = vtf.split('variable "ssh_public_key"', 1)[1].split("validation", 1)[0]
    assert "default" not in head
    assert "length(trimspace(var.ssh_public_key)) > 0" in vtf
    assert "ssh_public_key must be a non-empty OpenSSH public key" in vtf


def test_private_realm_public_egress_cidr_literals_unchanged_count() -> None:
    main_tf = _read(_repo_root() / "terraform" / "modules" / "private-realm" / "main.tf")
    assert main_tf.count('"0.0.0.0/0"') == 3
