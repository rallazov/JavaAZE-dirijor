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

variable "headscale_login_url" {
  type        = string
  sensitive   = false
  description = "Headscale operator join base URL (scheme + host) for `tailscale up --login-server=`. Aligned with supervisor `control_plane_base_url` / DIRIJOR_HEADSCALE_PUBLIC_URL."

  validation {
    condition     = length(trimspace(var.headscale_login_url)) > 0
    error_message = "headscale_login_url is required (non-empty) for droplet cloud-init and mesh join (Story 9.2)"
  }
}

variable "wrapper_image" {
  type        = string
  sensitive   = false
  description = "OpenClaw wrapper container image (e.g. DIRIJOR_AGENT_WRAPPER_IMAGE)."

  validation {
    condition     = length(trimspace(var.wrapper_image)) > 0
    error_message = "wrapper_image is required (non-empty) for the agent container (Story 9.2)"
  }
}

variable "agent_preauth_keys" {
  type        = list(string)
  sensitive   = true
  description = "Per-droplet Headscale one-shot preauth keys (N = agent_count; minted by supervisor pre-apply)."

  validation {
    condition     = length(var.agent_preauth_keys) == var.agent_count
    error_message = "agent_preauth_keys must have the same length as agent_count (Story 9.2)"
  }
}

variable "supervisor_api_url" {
  type        = string
  default     = ""
  sensitive   = false
  description = "Optional HTTP base URL for droplet→supervisor callbacks over the tailnet (Story 9.4 → DIRIJOR_SUPERVISOR_API_URL on the wrapper). Leave empty for local-only / operator-injected paths."
}

variable "supervisor_ws_url" {
  type        = string
  default     = ""
  sensitive   = false
  description = "Optional WebSocket URL for realm canvas channel (Story 9.4 → DIRIJOR_SUPERVISOR_WS_URL). Must not reuse loopback NEXT_PUBLIC_* values on droplets."
}
