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
  egress unless **`var.allow_public_egress`** is true. **`user_data`** is
  rendered with **`templatefile("cloud-init/agent.yaml.tftpl", { ... })`**
  (Story 9.2) — one preauth per `count.index`.
- **Outputs:** `agent_droplet_ids`, `agent_private_ipv4s` (splat over
  `digitalocean_droplet.agent`, `count.index` order).

**Supervisor mesh (Story 9.4):** for **default-deny egress** realms, enable
supervisor mesh on Core and set droplet callback bases to the **tailnet**
hostname (MagicDNS / `100.x`), **not** a public routable IP. See
[`docs/reference/supervisor-api.md`](../../../docs/reference/supervisor-api.md)
(Supervisor mesh) and optional `supervisor_api_url` / `supervisor_ws_url` module
variables (wired from `DIRIJOR_SUPERVISOR_API_URL` / `DIRIJOR_SUPERVISOR_WS_URL`
on the supervisor when writing `terraform.tfvars.json`).

## Bootstrapping agents (Story 9.2)

**New variables (supervisor writes to `terraform.tfvars.json` alongside Story 2.2 / 9.1 fields):**

| Variable | `sensitive` | Notes |
|----------|-------------|--------|
| `headscale_login_url` | no | TLS base for `tailscale up --login-server=`. Aligned with supervisor `control_plane_base_url()` (typically `DIRIJOR_HEADSCALE_PUBLIC_URL` or API URL without `/api/v1`). |
| `wrapper_image` | no | **OpenClaw** wrapper image; supervisor reads **`DIRIJOR_AGENT_WRAPPER_IMAGE`**. The image must be pullable by a fresh droplet without interactive `docker login`; use a public image, pre-baked registry credentials, or a private mirror reachable under your egress posture. |
| `agent_preauth_keys` | **yes** | `list(string)`, **length = `var.agent_count`**. One-shot Headscale preauth per droplet; minted in Core **before** `terraform plan/apply` so the first droplet boot can enroll. Re-apply of the same job mints a fresh set (droplets may be replaced if `user_data` changes). |
| `supervisor_api_url` | no | Optional (default empty). When non-empty, cloud-init adds **`DIRIJOR_SUPERVISOR_API_URL`** to the wrapper container for tailnet HTTP callbacks (Story 9.4). |
| `supervisor_ws_url` | no | Optional (default empty). Tailnet WebSocket base for **`DIRIJOR_SUPERVISOR_WS_URL`**. |

**Cloud-init outline (Ubuntu 22.04):** `apt` install **`ca-certificates`**, **`curl`**, and **`docker.io`**; install Tailscale via **`https://tailscale.com/install.sh`**; write preauth to **`/root/dirijor-preauth`** (mode **0600**); **`tailscale up`** with `--login-server`, `--authkey` from the file, `--advertise-tags=tag:dirijor:realm:<realm_id>`; **`docker pull` / `docker run --net=host`** for the wrapper. No `set -x` / no `echo` of secrets. Hardened environments should replace the public install-script path with a vetted package mirror or pre-baked base image.

**Headscale / firewall reachability:** with **`allow_public_egress: false`**, the droplet can only use RFC1918 destinations unless you add a narrow path. That blocks **`tailscale.com`**, the Headscale public URL, and most package mirrors unless you use a **private** `headscale_login_url` and operator-built images, or you temporarily set **`allow_public_egress: true`** (see ADR-0004 and sprint notes). This is a deployment choice — document the chosen path for your environment.

**Security:** preauth material exists in Terraform state and `user_data` (as today for `do_token`). Per-realm workspaces under **`DIRIJOR_TERRAFORM_WORKSPACE_ROOT`** are ephemeral; restrict access. Keys are not returned on **`GET /realms/{job_id}`**.

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
