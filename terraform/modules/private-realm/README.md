<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# private-realm (DigitalOcean VPC)

Story 2.2 ships a **minimal** DigitalOcean VPC for Dirijor’s `terraform-digitalocean` adapter. This module intentionally stops at VPC provisioning so the adapter surface stays small.

- **In scope (v0.2):** one `digitalocean_vpc` per realm, outputs for VPC id / CIDR / region.
- **Story 5.1:** mesh enrollment (Headscale) and consumption of `outputs.mesh_endpoint` from Core.
- **Story 5.3:** Firecracker-capable host droplets inside the VPC.

See [`docs/architecture/adr/0003-terraform-adapter-v0.md`](../../../docs/architecture/adr/0003-terraform-adapter-v0.md) and the implementation story `_bmad-output/implementation-artifacts/2-2-terraform-adapter-v0-single-private-cloud-target.md`.
