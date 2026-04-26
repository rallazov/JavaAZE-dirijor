<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# headscale-control

`headscale-control` provisions a shared, account-level Headscale control plane
on one DigitalOcean droplet. Apply it once in a dedicated Terraform workspace or
one-off root module. Do not compose it inside `terraform/modules/private-realm`;
realm spins consume its outputs.

## Runtime

The module creates one Ubuntu 22.04 droplet in a configurable region, defaulting
to `nyc3`, pinned to `s-1vcpu-512mb-10gb`. Cloud-init installs Docker, starts a
Headscale container, and places Caddy in front as the TLS-terminating reverse
proxy.

The default image is `headscale/headscale:0.23.0`. When upgrading, use the
configuration example from the same Headscale release tag:
https://headscale.net/0.23.0/ref/configuration/.

State persists under `/var/lib/dirijor/headscale` on the droplet. Caddy ACME
state persists under `/var/lib/dirijor/caddy`. `terraform destroy` deletes the
droplet and therefore destroys Headscale state; all realms that use this control
plane will lose login/bootstrap continuity.

## Listener Layout

| Surface | Binding | Purpose |
|---|---|---|
| Public TCP `80` | Caddy | ACME HTTP-01 and HTTP to HTTPS handling |
| Public TCP `443` | Caddy | HTTPS Headscale API and Tailscale login server |
| Headscale TCP `8080` | Docker network only | Upstream for Caddy; no public port mapping |
| Headscale metrics / gRPC | `127.0.0.1` on droplet | Not exposed in Phase 0 |

Phase 0 uses a single HTTPS origin for Dirijor API calls and Tailscale
`--login-server`: `https://<headscale_fqdn>`. The supervisor API base appends
`/api/v1`. DERP uses Headscale's default DERP map; this module does not publish
a DERP server or public gRPC surface.

The raw Headscale port is not opened in the DigitalOcean firewall and is not
published by Docker. Public ingress is `80/443` only, plus optional SSH when
`ssh_allowed_cidrs` is non-empty.

## DNS and TLS

Create an `A` record for `headscale_fqdn` pointing at
`headscale_droplet_ipv4`. The module sets `ipv6 = false`, so do not create an
`AAAA` record unless you have verified dual-stack routing outside this module.
Caddy obtains Let's Encrypt certificates automatically after DNS resolves to the
droplet.

For repeated destroy/apply tests, set `lets_encrypt_staging = true` to use the
Let's Encrypt staging CA and avoid production rate limits. Use production ACME
for real realms.

## Example Root Module

```hcl
module "headscale_control" {
  source = "../../terraform/modules/headscale-control"

  do_token          = var.do_token
  headscale_fqdn    = "headscale.example.com"
  ssh_public_key    = var.ssh_public_key
  ssh_allowed_cidrs = ["203.0.113.10/32"]
}
```

The API key is intentionally not created or output by Terraform. After the
droplet is reachable, create it once from the Headscale container:

```bash
ssh root@headscale.example.com
docker compose -f /opt/dirijor/headscale/docker-compose.yml exec -it headscale headscale apikeys create
```

This uses the Compose **service name** `headscale`, so it stays correct when
`headscale_image` is overridden in Terraform (no hard-coded image tag in the
operator command).

Copy the printed key once, store it in a password manager, and never commit it
to git or a checked-in `terraform.tfvars`.

## Outputs and Dirijor Env

| Terraform output | Supervisor env var | `private-realm` tfvar |
|---|---|---|
| `headscale_api_url` | `DIRIJOR_HEADSCALE_API_URL` | n/a |
| `headscale_public_url` | `DIRIJOR_HEADSCALE_PUBLIC_URL` | `headscale_login_url` |
| operator-created key | `DIRIJOR_HEADSCALE_API_KEY` | n/a |

Copy-paste shape:

```bash
export DIRIJOR_HEADSCALE_API_URL="$(terraform output -raw headscale_api_url)"
export DIRIJOR_HEADSCALE_PUBLIC_URL="$(terraform output -raw headscale_public_url)"
export DIRIJOR_HEADSCALE_API_KEY="<store-outside-git>"
```

Set `DIRIJOR_HEADSCALE_PUBLIC_URL` explicitly in production even though
`control_plane_base_url()` can derive it from an API URL ending in `/api/v1`.
The canonical values have no trailing slash.

## ACL — supervisor tag (Story 9.4)

The bundled `acl.hujson` grants `tag:dirijor:realm:supervisor` (Tailscale Serve
ports **443** and **8000**) so realm agents can reach a supervisor that joined
the mesh with that tag. A catch-all rule remains for local/dev; tighten in
production once you rely only on tagged nodes.

## Realm Reachability

This module enables the public-URL Phase-0 path. Agent droplets created by
`private-realm` must be able to reach `headscale_public_url` during cloud-init.
With `allow_public_egress = false`, `private-realm` allows only RFC1918 egress,
so a public Headscale URL is blocked unless you add a private path or exception.
For Phase 0, set `DIRIJOR_ALLOW_PUBLIC_EGRESS=1` when using the public control
plane, or provide a private/peered Headscale path in a later story.

See `terraform/modules/private-realm/README.md` "Headscale / firewall
reachability" for the matching realm-side trade-off.

## Local Compose

Repo-root `docker-compose.headscale.yml` is opt-in:

```bash
docker compose -f docker-compose.headscale.yml up -d
```

It exposes a local HTTP origin at `http://127.0.0.1:8080` through Caddy for
supervisor-only development:

```bash
export DIRIJOR_HEADSCALE_API_URL=http://127.0.0.1:8080/api/v1
export DIRIJOR_HEADSCALE_PUBLIC_URL=http://127.0.0.1:8080
```

**Loopback-only URLs are not reachable from remote DigitalOcean droplets. Do not
use this compose path to validate Story 9.2 cloud-init against remote agents
unless you add tunneling or private routing outside this story.**

## Security Notes

Terraform state contains droplet IDs, IPs, and user-data metadata. Use remote
state with encryption and restricted access for shared environments. Headscale
API keys and preauth secrets are operator-owned runtime secrets; keep them out
of Terraform outputs, `.tfvars`, logs, and git.
