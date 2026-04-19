# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

output "realm_vpc_id" {
  value = digitalocean_vpc.realm_vpc.id
}

output "realm_vpc_ip_range" {
  value = digitalocean_vpc.realm_vpc.ip_range
}

output "realm_region" {
  value = "nyc3"
}

output "realm_firewall_id" {
  value = digitalocean_firewall.realm_egress.id
}
