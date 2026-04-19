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
