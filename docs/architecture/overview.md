<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# Architecture overview

> The canonical system diagram lives at
> [`docs/architecture.mermaid`](../architecture.mermaid). This page is
> the **narrated version**: it walks the diagram layer by layer,
> explains why each piece exists, and links to the ADRs that justify
> the key bets.

If anything on this page conflicts with the Mermaid diagram, the diagram
wins. File a PR.

## How to read this page

Dirijor's architecture is best explained as **four concentric rings**,
each enforcing a different guarantee:

1. **Humans** — the canvas UI. The only layer a user touches directly.
2. **Control plane** — Dirijor Core (LangGraph supervisor) + Safety Fortress.
3. **Realm plane** — IaC adapters + private mesh + microVM sandboxes.
4. **Agent plane** — OpenClaw-wrapped agents with policy-gated tool access.

Each outer ring assumes **nothing** about the trust of the ring below
it. That's what makes "zero-trust by default" tractable. See
[Zero-trust by default](../product/concepts/zero-trust.md).

---

## Layer 0 — Humans and the Canvas

**Component:** Next.js + React Flow 2.0 (`frontend/`).

**Role.** The operator's entire world. Composes topology, shows live
safety metrics, hosts the human-in-the-loop gates, surfaces audit
snippets.

**Why a canvas, not YAML?** Operators manage *graphs* of agents and
trust relationships. YAML is a bad fit for graphs — it compiles in the
author's head and nowhere else. A canvas turns the model into the UI.
The PRD encodes this as a non-negotiable:

> *"Drag-and-drop Network Canvas (React Flow) with live topology."*

**Bindings today (v0.1).**

- Canvas shell, inspector, HITL UX: shipped through Epic 1 (Stories 1.1–1.6).
- Live WebSocket binding to Core: **not yet** (lands in Story 3.3 —
  the canvas currently calls `useDirijorRealtime({ url: undefined })`).

---

## Layer 1 — Control plane: Dirijor Core + Safety Fortress

**Components:** `backend/dirijor-core/supervisor.py` (FastAPI + LangGraph),
and the Safety Fortress subsystem (consensus debate loop, verified
semantic cache, anomaly + quarantine, audit export).

**Role.** Coordinates everything. Every agent-to-agent message, every
tool call, every consensus workflow passes through here. The canvas
binds to this layer's stable HTTP/WebSocket contract. So does
observability. So will every future integration.

**Why LangGraph?** It models the supervisor as a stateful graph of
nodes, which matches the mental model of "routes + consensus + safety
hooks" better than a linear chain or ad-hoc async code. See
[ADR-0001 — LangGraph supervisor](adr/0001-langgraph-supervisor.md) for
the full reasoning and alternatives considered.

**Why a stable HTTP contract first?** Because the canvas (Story 3.3) and
observability (Story 6.1) will both bind to it. If the contract drifts,
two subsystems break. Story 3.1 hardened `/`, `/health`, and
`/consensus` into a Pydantic-backed, schema-versioned contract with a
readiness registry — that's the surface every other subsystem speaks to.
See the [Supervisor API reference](../reference/supervisor-api.md).

**Why 95% consensus?** See
[ADR-0002 — Consensus threshold ≥95%](adr/0002-consensus-threshold-95.md)
and [Concept — Consensus](../product/concepts/consensus.md).

**Bindings today (v0.1).**

- `/`, `/health`, `/consensus` hardened contract: shipped (Story 3.1).
- Consensus debate loop: shipped (Story 3.2 — real quorum + rounds).
- Verified semantic cache (Qdrant): **Story 4.1** — `POST /semantic-cache/*`,
  optional consensus augmentation via `query_vector` / `semantic_scope_id`,
  live `semantic_cache` readiness probe (`required: false`; unconfigured URL
  → `ready: false, detail: "not configured"`).
- Anomaly auto-quarantine, audit export: Stories 4.2 / 4.3.

---

## Layer 2 — Realm plane: IaC, mesh, sandbox

**Components:** Terraform/Pulumi adapters (realm manager), Headscale/Tailscale mesh, Firecracker microVMs.

**Role.** Turns a canvas topology into real, isolated, mTLS-authenticated
infrastructure on the private cloud of your choice (DigitalOcean,
Hetzner, Proxmox, self-hosted, Hostinger VPS, …).

**Why IaC adapters, not a vendor SDK?** Portability. The PRD makes
cloud-agnosticism a non-negotiable:

> *"Cloud-agnostic IaC (Terraform/Pulumi adapters)."*

Wrapping Terraform (plus Pulumi later) behind an adapter interface
means a new cloud is a new adapter, not a fork of the supervisor.

**Why a mesh, not direct WireGuard?** A tailnet-style control plane
(Headscale) handles key rotation and ACLs declaratively, so a policy
change doesn't require SSH into every node. The architecture pairs the
mesh with application-layer mTLS for defense in depth.

**Why Firecracker over containers?** MicroVMs give hardware-virtualized
isolation with container-like startup costs. A compromised agent
cannot read another agent's memory — something containers cannot
credibly guarantee. Supported gracefully-degrades on hosts without
Firecracker (Story 5.3 explicit).

**Bindings today (v0.1).**

- `POST /realms/spin` + `DELETE /realms/{job_id}` + `GET /realms/{job_id}` with the `terraform-digitalocean` adapter available when **`DIGITALOCEAN_TOKEN`** and a terraform binary are configured (Story 2.2, 2026-04-18). Story 2.3 (2026-04-19) adds **`EgressPolicyRealmAdapter`** (pre-validate / pre-provision hook → `egress_policy_denied`) and **`terraform/modules/private-realm`** firewall rules with default-deny public Internet egress; optional **`DIRIJOR_ALLOW_PUBLIC_EGRESS`** adds explicit outbound to the Internet in Terraform. Story 5.1 consumes `outputs.mesh_endpoint`.
- Mesh bootstrap automation: Story 5.1 (consumes `SpinJob.outputs.mesh_endpoint`).
- Firecracker lifecycle: Story 5.3 (may trail MVP).

---

## Layer 3 — Agent plane: OpenClaw wrapper + private tools

**Components:** `backend/openclaw-wrapper/` and the tool surface it exposes.

**Role.** The agent itself — wrapped. Every LLM call, every tool
invocation, every outbound network request goes through the wrapper,
which enforces the realm's policy (allowlist, egress rules, HITL gates).

**Why wrap agents instead of trusting them?** Because the whole point
of Dirijor is that *agents are not trusted*. The wrapper is the
enforcement point where "this agent is allowed to call this tool right
now" becomes true or false.

**Bindings today (v0.1).**

- OpenClaw tool surface + egress policy: Story 5.2.
- Integration with supervisor + canvas: follows Epic 3/5 completion.

---

## Cross-cutting: Observability

**Components:** OpenTelemetry spans from Core + runtime → Grafana +
consensus/quality heatmaps, fed back into the canvas HUD.

**Why observability is a first-class layer (not an add-on).** The PRD
makes auditability a hard requirement (NFR3, NFR8). Traces of
consensus rounds, cache hits/misses, quarantine events and policy
denials *are* the evidence that the safety posture works. If they're
bolt-on, they rot.

**Bindings today (v0.1).**

- Core + runtime OTel instrumentation: Story 6.1.
- Grafana dashboards: Story 6.2.
- Canvas-integrated live safety metrics: Story 6.3.

---

## Cross-cutting: Marketplace _(deferred)_

Epic 7 (Stories 7.1, 7.2) adds signed swarm templates and a one-click
import path. Deliberately sequenced *after* provisioning, safety, and
observability because a marketplace that imports into an unsafe plane
is a liability, not a feature.

---

## The honest summary

At v0.1, the **shape** of all four layers exists — canvas, supervisor
contract, docker-compose, wrapper skeleton — but only the canvas shell
and the supervisor contract are production-grade. The rest is wired
into the readiness registry so every dependency can be asked *are you
real yet?* and answer honestly.

That honesty is the point: when Dirijor claims "zero hallucination on
high-stakes outputs" or "100% private by default," the
[supervisor API reference](../reference/supervisor-api.md) is the
single source of truth for whether today's build actually delivers it.

## Related reading

- Canonical diagram: [`docs/architecture.mermaid`](../architecture.mermaid)
- PRD non-negotiables: [`docs/DIRIJOR-PRD.md`](../DIRIJOR-PRD.md)
- Contributor conventions: [`docs/project-context.md`](../project-context.md)
- Planning artifact (epics + stories): `_bmad-output/planning-artifacts/epics.md` (in the repo; gitignored, not on this site)
- Decision records: [**ADR index**](adr/README.md)
