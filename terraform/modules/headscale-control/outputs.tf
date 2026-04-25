# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

output "headscale_api_url" {
  description = "Canonical supervisor API base for DIRIJOR_HEADSCALE_API_URL. No trailing slash."
  value       = "https://${var.headscale_fqdn}/api/v1"
}

output "headscale_public_url" {
  description = "Canonical Tailscale login-server origin for DIRIJOR_HEADSCALE_PUBLIC_URL and private-realm headscale_login_url. No trailing slash."
  value       = "https://${var.headscale_fqdn}"
}

output "headscale_droplet_id" {
  description = "DigitalOcean droplet id for the shared Headscale control plane."
  value       = digitalocean_droplet.headscale_control.id
}

output "headscale_droplet_ipv4" {
  description = "Public IPv4 address. Create an A record for headscale_fqdn before relying on Caddy ACME."
  value       = digitalocean_droplet.headscale_control.ipv4_address
}

output "headscale_firewall_id" {
  description = "DigitalOcean firewall protecting the shared Headscale control plane."
  value       = digitalocean_firewall.headscale_control.id
}
