<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# private-realm (DigitalOcean VPC + egress firewall)

Story 2.2 introduced a **minimal** DigitalOcean VPC per realm. Story 2.3 adds a
**tag-scoped Cloud Firewall** so outbound traffic to the **public Internet** is
**not** permitted unless the operator explicitly opts in.

## Security posture

| Variable / input | Default | Meaning |
|---|---|---|
| `allow_public_egress` | `false` | Firewall **outbound** allows only RFC1918 (`10/8`, `172.16/12`, `192.168/16`) for tcp/udp/icmp. |
| `allow_public_egress` | `true` | Adds explicit outbound rules to `0.0.0.0/0` and `::/0` (tcp/udp/icmp) in addition to private ranges. |

The Dirijor Core `terraform-digitalocean` adapter sets `allow_public_egress` from
the supervisor environment: **`DIRIJOR_ALLOW_PUBLIC_EGRESS`** (truthy values:
`1`, `true`, `yes`, `on`). The DigitalOcean token is **never** written to
`terraform.tfvars.json` — it is passed via `TF_VAR_do_token` / provider env as in
Story 2.2.

**Inbound:** restricted to the same RFC1918 source ranges (private/mesh-oriented
traffic). Adjust in a dedicated story if public ingress is required.

**Tag:** `dirijor-realm-<realm_name>` — attach droplets / workers to this tag in
later stories so the firewall applies.

## Compute (Story 9.1)

- **`var.ssh_public_key`** (required, no default) — operator OpenSSH public key;
  the supervisor reads **`DIRIJOR_DO_SSH_PUBLIC_KEY`** and writes it to
  `terraform.tfvars.json`. Blank values fail module validation.
- **`digitalocean_ssh_key.operator`** — per-realm key resource named
  `${var.realm_name}-operator` (destroyed with the realm).
- **`digitalocean_droplet.agent`** — `count = var.agent_count`, pinned
  **`size`** `s-1vcpu-512mb-10gb`, **`image`** `ubuntu-22-04-x64`, **`region`**
  `nyc3` (must match the VPC). Tags **`["dirijor-realm-${var.realm_name}"]`**
  (byte-identical to the Story 2.3 firewall) so droplets inherit default-deny
  egress unless **`var.allow_public_egress`** is true. **`user_data`** is `""`
  in 9.1 (Story 9.2 replaces with `templatefile(...)` cloud-init).
- **Outputs:** `agent_droplet_ids`, `agent_private_ipv4s` (splat over
  `digitalocean_droplet.agent`, `count.index` order).

**Out of scope here:** Story 9.2 (cloud-init / mesh join `user_data`), Story 9.4
(supervisor-in-mesh private callback path).

## Scope

- **In scope:** one `digitalocean_vpc`, one `digitalocean_firewall`, Story 9.1
  compute (`ssh_key` + `agent` droplets), outputs for VPC id, CIDR, region,
  firewall id, droplet ids, private IPv4 list.
- **Story 5.1:** supervisor-side Headscale enrollment after spin (`outputs.mesh_endpoint`
  placeholder preserved; see `docs/reference/supervisor-api.md`) — this Terraform module is unchanged.
- **Story 5.3:** Firecracker-capable host droplets inside the VPC.

See [`docs/architecture/adr/0003-terraform-adapter-v0.md`](../../../docs/architecture/adr/0003-terraform-adapter-v0.md),
[`docs/architecture/adr/0004-default-deny-egress-terraform.md`](../../../docs/architecture/adr/0004-default-deny-egress-terraform.md),
and `_bmad-output/implementation-artifacts/2-2-terraform-adapter-v0-single-private-cloud-target.md`.
