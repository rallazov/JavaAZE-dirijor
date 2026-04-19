<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# ADR-0004: Default-deny public egress at the Terraform layer (Story 2.3)

- **Status:** Accepted
- **Date:** 2026-04-19
- **Deciders:** Ramin Allazov (JavaAZE)
- **Related PRD clauses:** FR10 (“100% private — zero public internet exposure by
  default”), NFR6 (privacy / explicit egress only by policy)
- **Related stories:** Story 2.3 (policy hooks + module), Story 2.2 (adapter), Story 5.2
  (OpenClaw egress — separate enforcement point)

## Context

Epic 2 provisions isolated realms via `terraform-digitalocean`. A VPC alone does
not prove “no public Internet egress” — operators need **explicit** network rules
that deny outbound to the public Internet unless policy allows it.

## Decision

1. **Terraform-first posture** — Express default-deny public egress as
   `digitalocean_firewall` outbound rules that whitelist only RFC1918 destinations
   by default. Optional outbound to `0.0.0.0/0` / `::/0` is gated by the module
   variable `allow_public_egress`, fed from operator env
   **`DIRIJOR_ALLOW_PUBLIC_EGRESS`** (truthy) via `terraform.tfvars.json` (no
   `SCHEMA_VERSION` bump for this story).
2. **Composable Core hook** — Wrap only the terraform adapter with
   `EgressPolicyRealmAdapter`, which runs `_enforce_spin_egress_policy` before
   `validate` / `provision`. `TerraformAdapter` stays free of one-off checks so
   decorators remain composable.
3. **Closed `SpinError.code`** — Add **`egress_policy_denied`** for pre-provision
   denials. v0 uses **`DIRIJOR_EGRESS_POLICY_DENY=1`** to exercise the path in
   tests and drills; production rules extend the same hook.
4. **No SCHEMA bump** — Wire shape unchanged; policy and Terraform variables are
   env- and module-driven.

## Consequences

- Operators who need public egress for a realm must set **`DIRIJOR_ALLOW_PUBLIC_EGRESS`**
  on the supervisor process before spin (documented in the API reference).
- Firewalls attach via **tags** (`dirijor-realm-<realm_id>`); droplets created in
  later stories must use the tag for rules to apply.
- Application-layer egress (OpenClaw) remains a separate enforcement point (Epic 5).

## Alternatives considered

- **Only application-level egress control** — Rejected for this story: FR10/NFR6
  require infrastructure posture by construction, not only runtime wrappers.
- **New POST field for allow-egress** — Deferred: would require `SCHEMA_VERSION`
  and frontend sync; env-driven opt-in matches operator workflows for v0.3.

## References

- [`docs/reference/supervisor-api.md`](../../reference/supervisor-api.md)
- [`terraform/modules/private-realm/README.md`](https://github.com/JavaAZE/JavaAZE-dirijor/blob/main/terraform/modules/private-realm/README.md)
