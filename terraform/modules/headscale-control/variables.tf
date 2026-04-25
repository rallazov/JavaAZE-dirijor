# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

variable "do_token" {
  type      = string
  sensitive = true
}

variable "headscale_fqdn" {
  type        = string
  description = "Operator-controlled DNS name for the shared Headscale control plane, e.g. headscale.example.com."

  validation {
    condition     = length(trimspace(var.headscale_fqdn)) > 0 && !strcontains(var.headscale_fqdn, "/")
    error_message = "headscale_fqdn must be a non-empty hostname without scheme or path."
  }
}

variable "region" {
  type        = string
  default     = "nyc3"
  description = "Single DigitalOcean region for the shared Headscale control-plane droplet."
}

variable "droplet_size" {
  type        = string
  default     = "s-1vcpu-512mb-10gb"
  description = "Pinned Phase-0 Headscale control-plane droplet size."
}

variable "ssh_public_key" {
  type        = string
  sensitive   = false
  description = "Operator OpenSSH public key for break-glass droplet access."

  validation {
    condition     = length(trimspace(var.ssh_public_key)) > 0
    error_message = "ssh_public_key must be a non-empty OpenSSH public key."
  }
}

variable "ssh_allowed_cidrs" {
  type        = list(string)
  default     = []
  description = "Optional CIDR allowlist for SSH ingress. Empty default means no public SSH ingress rule is created."
}

variable "lets_encrypt_email" {
  type        = string
  default     = ""
  description = "Optional ACME contact email for Caddy / Let's Encrypt."
}

variable "lets_encrypt_staging" {
  type        = bool
  default     = false
  description = "When true, configures Caddy to use the Let's Encrypt staging CA for repeated destroy/apply tests."
}

variable "headscale_image" {
  type        = string
  default     = "headscale/headscale:0.23.0"
  description = "Pinned Headscale container image tag. Upgrade intentionally in a follow-up story."
}

variable "caddy_image" {
  type        = string
  default     = "caddy:2.8.4-alpine"
  description = "Pinned Caddy image used as the public TLS-terminating reverse proxy."
}
