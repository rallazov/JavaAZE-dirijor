# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Private Realm — DigitalOcean VPC only (Story 2.2). Mesh (5.1) and
# Firecracker hosts (5.3) are out of scope here.

provider "digitalocean" {
  token = var.do_token
}

resource "digitalocean_vpc" "realm_vpc" {
  name   = "${var.realm_name}-private-realm"
  region = "nyc3"
}
