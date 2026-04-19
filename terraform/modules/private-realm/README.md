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

## Scope

- **In scope:** one `digitalocean_vpc`, one `digitalocean_firewall`, outputs for
  VPC id, CIDR, region, firewall id.
- **Story 5.1:** mesh enrollment (Headscale) and `outputs.mesh_endpoint` consumption.
- **Story 5.3:** Firecracker-capable host droplets inside the VPC.

See [`docs/architecture/adr/0003-terraform-adapter-v0.md`](../../../docs/architecture/adr/0003-terraform-adapter-v0.md),
[`docs/architecture/adr/0004-default-deny-egress-terraform.md`](../../../docs/architecture/adr/0004-default-deny-egress-terraform.md),
and `_bmad-output/implementation-artifacts/2-2-terraform-adapter-v0-single-private-cloud-target.md`.
