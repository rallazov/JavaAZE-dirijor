# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Private Realm Manager – Dirijor v0.1

terraform {
  required_providers {
    digitalocean = { source = "digitalocean/digitalocean" version = "~> 2.0" }
    # Extend with hetznercloud, proxmox, etc.
  }
}

variable "realm_name" { type = string }
variable "agent_count" { default = 10 }
variable "cloud_provider" { default = "digitalocean" }

resource "digitalocean_vpc" "realm_vpc" {
  name   = "${var.realm_name}-private-realm"
  region = "nyc3"
}

# Headscale + Firecracker provisioning hooks go here (full multi-cloud version ready next command)
output "realm_vpc_id" { value = digitalocean_vpc.realm_vpc.id }
