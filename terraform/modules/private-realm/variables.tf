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
