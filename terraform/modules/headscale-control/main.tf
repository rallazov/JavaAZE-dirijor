# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Shared Headscale control plane: account-level module, apply once outside
# per-realm private-realm workspaces.

provider "digitalocean" {
  token = var.do_token
}

locals {
  control_tags = ["dirijor-headscale-control"]
}

resource "digitalocean_ssh_key" "operator" {
  name       = "dirijor-headscale-control-operator"
  public_key = var.ssh_public_key
}

resource "digitalocean_droplet" "headscale_control" {
  name     = "dirijor-headscale-control"
  size     = var.droplet_size
  image    = "ubuntu-22-04-x64"
  region   = var.region
  ssh_keys = [digitalocean_ssh_key.operator.fingerprint]
  tags     = local.control_tags

  backups    = false
  monitoring = true
  ipv6       = false

  user_data = templatefile(
    "${path.module}/cloud-init/headscale-control.yaml.tftpl",
    {
      caddy_image           = var.caddy_image
      headscale_fqdn        = var.headscale_fqdn
      headscale_image       = var.headscale_image
      lets_encrypt_email    = var.lets_encrypt_email
      lets_encrypt_staging  = var.lets_encrypt_staging
    }
  )
}

resource "digitalocean_firewall" "headscale_control" {
  name = "dirijor-headscale-control"
  tags = local.control_tags

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  dynamic "inbound_rule" {
    for_each = length(var.ssh_allowed_cidrs) > 0 ? [1] : []
    content {
      protocol         = "tcp"
      port_range       = "22"
      source_addresses = var.ssh_allowed_cidrs
    }
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  depends_on = [digitalocean_droplet.headscale_control]
}
