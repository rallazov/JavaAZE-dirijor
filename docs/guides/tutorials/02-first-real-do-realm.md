<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# First Real DigitalOcean Realm

This tutorial extends the local first-realm path with the minimum shared
Headscale control-plane setup needed before DigitalOcean agent droplets can join
the mesh.

## Control Plane Setup

Apply `terraform/modules/headscale-control` once in a dedicated Terraform
workspace or one-off root module. It creates a shared Headscale droplet with
Caddy TLS in front; per-realm `private-realm` applies should consume its outputs
rather than creating their own Headscale server.

Canonical mapping:

| Terraform output | Runtime setting |
|---|---|
| `headscale_api_url` | `DIRIJOR_HEADSCALE_API_URL` |
| `headscale_public_url` | `DIRIJOR_HEADSCALE_PUBLIC_URL` |
| `headscale_public_url` | `private-realm` `headscale_login_url` |
| operator-created Headscale key | `DIRIJOR_HEADSCALE_API_KEY` |

```bash
export DIRIJOR_HEADSCALE_API_URL="$(terraform output -raw headscale_api_url)"
export DIRIJOR_HEADSCALE_PUBLIC_URL="$(terraform output -raw headscale_public_url)"
export DIRIJOR_HEADSCALE_API_KEY="<store-outside-git>"
```

The API key is created after Headscale is reachable and must stay outside git
and checked-in Terraform variables. See
`terraform/modules/headscale-control/README.md` for the full runbook, DNS/TLS
requirements, local compose recipe, and the `private-realm` firewall
reachability trade-off.

## Supervisor on the tailnet (Story 9.4)

For **default-deny public egress** droplets, OpenClaw wrappers must **not** use
loopback or a public laptop IP for Core callbacks. Enable supervisor mesh on
the machine running Dirijor Core (`DIRIJOR_SUPERVISOR_MESH_ENABLED` and a
supervisor preauth key), then set **`DIRIJOR_SUPERVISOR_API_URL`** and
**`DIRIJOR_SUPERVISOR_WS_URL`** to your MagicDNS / tailnet base (**`https://`**
and **`wss://`** on the default port — Tailscale Serve — not `http://…:8000`; see
[`supervisor-api.md`](../../reference/supervisor-api.md) — “Supervisor mesh”)
before **`POST /realms/spin`** so `terraform-digitalocean` passes those values
into droplet cloud-init. Operational verification (tcpdump, full golden path) is
Story **9.6**.
