# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Private Realm — DigitalOcean VPC + tagged firewall with default-deny
# public Internet egress (Story 2.3). Mesh (5.1) and Firecracker hosts (5.3)
# are out of scope here.

provider "digitalocean" {
  token = var.do_token
}

locals {
  private_cidrs = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
  ]
}

resource "digitalocean_vpc" "realm_vpc" {
  name   = "${var.realm_name}-private-realm"
  region = "nyc3"
}

# Tag-scoped firewall — applies to future droplets tagged
# `dirijor-realm-<realm_name>`. Outbound to the public Internet is omitted
# unless `allow_public_egress` is true (FR10 / NFR6 default posture).
resource "digitalocean_firewall" "realm_egress" {
  name = "${var.realm_name}-egress"
  tags = ["dirijor-realm-${var.realm_name}"]

  depends_on = [digitalocean_vpc.realm_vpc]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "1-65535"
    source_addresses = local.private_cidrs
  }

  inbound_rule {
    protocol         = "udp"
    port_range       = "1-65535"
    source_addresses = local.private_cidrs
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = local.private_cidrs
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = local.private_cidrs
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = local.private_cidrs
  }

  dynamic "outbound_rule" {
    for_each = var.allow_public_egress ? [1] : []
    content {
      protocol              = "tcp"
      port_range            = "1-65535"
      destination_addresses = ["0.0.0.0/0", "::/0"]
    }
  }

  dynamic "outbound_rule" {
    for_each = var.allow_public_egress ? [1] : []
    content {
      protocol              = "udp"
      port_range            = "1-65535"
      destination_addresses = ["0.0.0.0/0", "::/0"]
    }
  }

  dynamic "outbound_rule" {
    for_each = var.allow_public_egress ? [1] : []
    content {
      protocol              = "icmp"
      destination_addresses = ["0.0.0.0/0", "::/0"]
    }
  }
}

resource "digitalocean_ssh_key" "operator" {
  name       = "${var.realm_name}-operator"
  public_key = var.ssh_public_key
}

resource "digitalocean_droplet" "agent" {
  count = var.agent_count

  name     = "${var.realm_name}-agent-${count.index}"
  size     = "s-1vcpu-512mb-10gb"
  image    = "ubuntu-22-04-x64"
  region   = "nyc3"
  vpc_uuid = digitalocean_vpc.realm_vpc.id

  tags = ["dirijor-realm-${var.realm_name}"]

  ssh_keys = [digitalocean_ssh_key.operator.fingerprint]

  backups    = false
  monitoring = false
  ipv6       = false
  user_data = templatefile(
    "${path.module}/cloud-init/agent.yaml.tftpl",
    {
      preauth_key          = var.agent_preauth_keys[count.index]
      headscale_login_url  = var.headscale_login_url
      wrapper_image        = var.wrapper_image
      realm_id             = var.realm_name
      supervisor_api_url   = var.supervisor_api_url
      supervisor_ws_url    = var.supervisor_ws_url
    }
  )

  depends_on = [
    digitalocean_vpc.realm_vpc,
    digitalocean_firewall.realm_egress,
  ]
}
