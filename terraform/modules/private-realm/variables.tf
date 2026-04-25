# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

variable "realm_name" {
  type = string
}

variable "agent_count" {
  type    = number
  default = 3
}

variable "cloud_provider" {
  type    = string
  default = "digitalocean"
}

variable "do_token" {
  type      = string
  sensitive = true
}

variable "allow_public_egress" {
  type        = bool
  default     = false
  description = "When false (default), firewall outbound allows only RFC1918 destinations. When true, adds explicit outbound to 0.0.0.0/0 and ::/0 (operator opt-in)."
}

variable "ssh_public_key" {
  type        = string
  sensitive   = false
  description = "Operator OpenSSH public key injected into every agent droplet (DIRIJOR_DO_SSH_PUBLIC_KEY). Required when the terraform-digitalocean adapter is active."

  validation {
    condition     = length(trimspace(var.ssh_public_key)) > 0
    error_message = "ssh_public_key must be a non-empty OpenSSH public key"
  }
}
