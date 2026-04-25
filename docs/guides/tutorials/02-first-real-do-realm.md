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
