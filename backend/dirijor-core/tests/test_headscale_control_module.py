# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Hermetic assertions on Story 9.3 Headscale control-plane sources.

These tests intentionally avoid Terraform, Docker, DigitalOcean credentials, and
network access. They pin the operator-facing contract with lightweight source
checks so accidental removal of TLS/proxy/firewall wiring is caught in CI.
"""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_headscale_control_module_expected_files_exist() -> None:
    module = _repo_root() / "terraform" / "modules" / "headscale-control"
    for name in ("main.tf", "variables.tf", "outputs.tf", "versions.tf", "README.md"):
        assert (module / name).exists(), f"missing headscale-control/{name}"


def test_headscale_control_module_droplet_cost_tier_and_cloud_init() -> None:
    text = _read(_repo_root() / "terraform" / "modules" / "headscale-control" / "main.tf")
    assert 'resource "digitalocean_droplet" "headscale_control"' in text
    assert 'resource "digitalocean_firewall" "headscale_control"' in text
    assert "size     = var.droplet_size" in text
    assert 'image    = "ubuntu-22-04-x64"' in text
    assert "templatefile(" in text
    assert "cloud-init/headscale-control.yaml.tftpl" in text
    assert "headscale_api_key" not in text

    variables = _read(
        _repo_root() / "terraform" / "modules" / "headscale-control" / "variables.tf"
    )
    assert 'variable "region"' in variables
    assert 'default     = "nyc3"' in variables
    assert 'variable "droplet_size"' in variables
    assert 'default     = "s-1vcpu-512mb-10gb"' in variables


def test_headscale_control_module_tls_proxy_and_no_raw_headscale_exposure() -> None:
    module = _repo_root() / "terraform" / "modules" / "headscale-control"
    main_tf = _read(module / "main.tf")
    cloud_init = _read(module / "cloud-init" / "headscale-control.yaml.tftpl")

    assert "caddy" in cloud_init.lower()
    assert "reverse_proxy headscale:8080" in cloud_init
    assert "https://${headscale_fqdn}" in cloud_init
    assert "letsencrypt" in cloud_init.lower() or "acme" in cloud_init.lower()
    assert "image: ${headscale_image}" in cloud_init
    assert "headscale/headscale" in _read(module / "variables.tf")
    assert "/var/lib/dirijor/headscale" in cloud_init
    assert "127.0.0.1:8080:8080" not in cloud_init
    assert "8080:8080" not in cloud_init

    assert 'port_range       = "80"' in main_tf
    assert 'port_range       = "443"' in main_tf
    assert 'port_range       = "8080"' not in main_tf


def test_headscale_control_module_outputs_no_trailing_slash_contract() -> None:
    outputs = _read(
        _repo_root() / "terraform" / "modules" / "headscale-control" / "outputs.tf"
    )
    assert 'output "headscale_api_url"' in outputs
    assert 'output "headscale_public_url"' in outputs
    assert '"https://${var.headscale_fqdn}/api/v1"' in outputs
    assert '"https://${var.headscale_fqdn}"' in outputs
    assert "api_key" not in outputs.lower()
    assert "preauth" not in outputs.lower()


def test_headscale_control_compose_is_opt_in_loopback_only() -> None:
    root = _repo_root()
    compose = root / "docker-compose.headscale.yml"
    assert compose.exists(), "missing repo-root docker-compose.headscale.yml"
    text = _read(compose)
    assert "headscale/headscale" in text
    assert "caddy:" in text
    assert "127.0.0.1:8080:80" in text
    assert "DIRIJOR_" not in text

    root_compose = _read(root / "docker-compose.yml")
    assert "docker-compose.headscale.yml" not in root_compose
    assert "include:" not in root_compose


def test_headscale_control_firewall_posture_documented_and_implemented() -> None:
    module = _repo_root() / "terraform" / "modules" / "headscale-control"
    main_tf = _read(module / "main.tf")
    readme = _read(module / "README.md")
    assert 'resource "digitalocean_firewall" "headscale_control"' in main_tf
    assert 'port_range       = "80"' in main_tf
    assert 'port_range       = "443"' in main_tf
    assert "var.ssh_allowed_cidrs" in main_tf
    assert "raw Headscale port" in readme
    assert "80/443" in readme
    assert "ssh_allowed_cidrs" in readme
