<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# ADR-0003: Terraform adapter v0 (DigitalOcean first)

- **Status:** Accepted
- **Date:** 2026-04-18
- **Deciders:** Ramin Allazov (JavaAZE)
- **Related PRD clause:** *"Cloud-agnostic IaC (Terraform/Pulumi adapters)."* — [DIRIJOR-PRD.md](../../DIRIJOR-PRD.md)
- **Related stories:** Story 2.2 (adapter + DELETE), Story 5.1 (mesh), Story 2.3 (egress policy decorator).

## Context

Epic 2 needs a first concrete `RealmAdapter` behind the Story 2.1 seam so
`POST /realms/spin` can provision real infrastructure, not only
`LocalNoopAdapter`. Operators need a destroy path so dev realms do not leave
orphaned cloud resources.

## Decision

1. **DigitalOcean first** — the repo already contained a `terraform/modules/private-realm` stub; the PRD lists DO among supported clouds; a VPC is the smallest useful slice before mesh (5.1) and Firecracker hosts (5.3).
2. **Subprocess Terraform + injected runner** — the adapter shells out to the `terraform` CLI with an injectable `TerraformRunner` protocol so pytest stays hermetic (no binary, no token, no network on CI).
3. **Not Pulumi yet** — keep the `RealmAdapter` protocol cloud-agnostic; Pulumi is a future adapter, not a parallel requirement for v0.2.
4. **Per-realm workspace directories** — isolate `.terraform` state and allow `terraform destroy` via `DELETE /realms/{job_id}` without a global backend.
5. **Placeholder `mesh_endpoint`** — v0.2 returns `tf://<vpc_id>`; Story 5.1 **adds**
   `outputs.headscale_control_url` + `outputs.mesh` when mesh bootstrap is enabled
   but **preserves** `mesh_endpoint` for parsers that still read the placeholder.
6. **`SCHEMA_VERSION` 3→4** — new DELETE route, new `outputs` keys for destroy lifecycle, and nine new `SpinError.code` values; clients can feature-gate destroy UI.

## Consequences

- Operators who want the adapter must supply `DIGITALOCEAN_TOKEN` and install Terraform (not baked into the default slim Docker image).
- Secret scrubbing for terraform stderr is a closed four-pattern list; expand with tests when new leak channels appear.
- Multi-worker deployments still need a shared job store (documented follow-up).

## Alternatives considered

- **Terraform Cloud / TFE API** — rejected for v0.2: extra operational surface and network coupling; subprocess keeps tests deterministic.
- **Pulumi Python SDK** — deferred; would add a dependency and duplicate the adapter abstraction Story 2.1 already defined.

## References

- [Supervisor API — realm spin + DELETE](../../reference/supervisor-api.md)
- Story file: `_bmad-output/implementation-artifacts/2-2-terraform-adapter-v0-single-private-cloud-target.md`
