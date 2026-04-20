<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# Concept — Zero-trust by default

> Dirijor realms assume **every** network path is hostile until proven
> otherwise. No public egress. No implicit trust between agents. No
> tools reachable without a policy object. This is a *default*, not a
> feature toggle.

## Why this is a default, not a feature

The standard posture for agent platforms today is **deny-after-incident**:
you ship with broad egress, discover what breaks, and lock things down
reactively. This is the posture that produces headlines.

Dirijor inverts it. Realms ship **deny-by-default**, and every
permission is an explicit, auditable policy object. This is the direct
operational reading of two PRD non-negotiables:

> *"100% private — zero public internet exposure by default."*
>
> *"Zero-Trust Private Mesh: Headscale/Tailscale + mTLS + WireGuard;
> Firecracker microVM Sandboxing."*
> — [DIRIJOR-PRD.md](../../DIRIJOR-PRD.md) and [architecture.mermaid](../../architecture.mermaid)

Calling it a "default" is deliberate. Security configurations that can
be forgotten, get forgotten. Security *defaults* cannot be forgotten —
they're what happens when you do nothing.

## The three layers of zero-trust in Dirijor

Dirijor enforces zero-trust at three independent layers. A compromise
at one layer does not compromise the others.

### Layer 1 — Mesh identity (Headscale/Tailscale + mTLS)

Every node in a realm has a cryptographic identity. Every connection is
mTLS-authenticated. Nodes that don't hold a valid mesh credential
*cannot see each other on the network* — they don't get a "permission
denied," they get no route at all.

- **Why mesh over direct WireGuard?** A tailnet-style control plane
  (Headscale) manages key rotation and access lists declaratively, so
  policy changes don't require per-node SSH.
- **Why mTLS on top of mesh?** Defense in depth. If the mesh layer is
  ever misconfigured, application-layer mTLS still refuses the traffic.

### Layer 2 — Runtime isolation (Firecracker microVMs)

Each agent runs in its own Firecracker microVM — a lightweight,
hardware-virtualized boundary. A compromised agent cannot read another
agent's memory, peek at its filesystem, or escalate into the host.

Firecracker is a hard requirement for the "real" runtime. On
development hosts that don't support it, the runtime degrades gracefully
with an explicit capability bit — so you always know whether you're
running with real isolation or not. (See Story 5.3 in
`_bmad-output/planning-artifacts/epics.md`.)

### Layer 3 — Policy-gated tool access (OpenClaw wrapper)

Agents cannot invoke tools directly. Every tool call goes through the
OpenClaw wrapper, which checks a realm-scoped allowlist before letting
the call reach the outside world. The defaults:

- **No public internet egress.** Outbound HTTP is blocked unless a
  policy object enables it for a specific domain, port, or tool.
- **No cross-realm traffic.** An agent in realm A cannot reach an
  agent in realm B even if both run on the same host.
- **No privileged tools.** Shell, filesystem writes, and destructive
  actions are off by default and require explicit policy objects +
  (optionally) human-in-the-loop gates.

This is what PRD non-negotiable #7 turns into at runtime:

> *"Turns raw OpenClaw agents into safe, orchestrated digital employees."*

## "Private by default" operational reading

Operationally, "private by default" means a newly-spun realm will
refuse, out of the box, all of the following — no configuration required:

- Public HTTP requests from any agent.
- DNS lookups outside the realm's resolver.
- Traffic to agents in other realms on the same host.
- Tool invocations not on the default allowlist.
- Reads of secrets not explicitly scoped to that agent.

Turning any of these on is a *positive action* an operator takes
knowingly, with the consequence recorded in the audit stream.

## Human-in-the-loop is part of the trust boundary

Zero-trust does not mean "zero humans." For destructive or high-impact
actions, the correct answer is often "ask a human." Dirijor bakes this
into the canvas: critical pending actions show up in the inspector
with approve/reject controls, a visible safety score, and the exact
context the agent was operating on. See Story 1.5 in
`_bmad-output/planning-artifacts/epics.md`.

The consequence: **no destructive step runs without conscious consent.**
That's a guarantee you can't reproduce by layering filters on top of a
permissive system — it has to be part of the default posture.

## What zero-trust is *not*

- **Not "the network is secure."** The network is *assumed hostile*.
  The realm's guarantees come from authentication and policy, not from
  network topology.
- **Not an egress-off switch.** Realms with no public egress are still
  fully operational — agents talk to each other, to tools exposed via
  private integrations, and to the supervisor. "Private" ≠ "offline."
- **Not "configure once, trust forever."** Mesh keys rotate. Policy
  objects are audited. Every connection re-authenticates on every
  session.

## Current implementation status (v0.1)

- **Canvas shell, inspector, HITL UX** — implemented (Epic 1, Stories 1.1–1.6).
- **Supervisor contract + health/readiness** — implemented (Story 3.1+).
  `/` and `/health` report `mesh` as `required: false` with `ready: true` when
  bootstrap is **disabled** (default) or when Headscale URL + API key are set;
  when bootstrap is **enabled** but credentials are missing, `mesh.ready` is
  **false** with an explicit `detail`. `semantic_cache` follows Qdrant
  configuration — the contract stays honest about what's wired vs optional.
- **Anomaly policy probe + quarantine registry** — Story 4.2 (`anomaly_policy`
  readiness entry; optional `DIRIJOR_ANOMALY_POLICY_PATH`; in-process
  `GET /safety/quarantine/{realm_id}`).
- **Mesh bootstrap (Headscale API)** — Story 5.1 *(shipped, operator-gated)*;
  **OpenClaw wrapper egress** — 5.2; **Firecracker lifecycle** — 5.3 (Epic 5).
- **Default-deny egress policy hooks at provision time** — Story 2.3.

Until Epic 5 is complete (wrapper egress, microVMs), "zero-trust by default"
is an *architectural commitment* visible in every doc, diagram, and readiness
probe — mesh enrollment is optional until operators enable it. The
[supervisor API reference](../../reference/supervisor-api.md) is the
single place that tells you what's actually running today.

## Related reading

- [**Realms**](realms.md) — the scope inside which zero-trust is enforced.
- [**Consensus**](consensus.md) — what runs *inside* the trust boundary once the network is locked down.
- [**Architecture overview**](../../architecture/overview.md) — where mesh, sandbox, and policy sit in the system diagram.
