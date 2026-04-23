<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# Dirijor — Private Agent Network OS

**The world's first human-first Private Agent Network Operating System.**

Drag-and-drop canvas + orchestration + multi-agent consensus + verified
semantic cache = **zero hallucination, zero exposure**, on infrastructure
you own.

---

## What is the point of Dirijor?

Three versions of the same answer, pick the one that fits your conversation.

### 10-second pitch

> Zero-trust operating system for LLM agents — **private by default,
> hallucination-proof by design**.

### 60-second pitch

> **Problem.** LLM agents are powerful but unsafe at scale: they hallucinate,
> leak data, and expose private networks to the public internet.
> Existing 1-click hosts (Hostinger, Replit, etc.) solve convenience —
> not safety.
>
> **Tension.** Teams either ship fast and accept risk, or lock everything
> down and ship nothing.
>
> **Insight.** Safety and speed aren't opposites if the control plane is
> private-by-default, consensus-verified, and visually composable.
>
> **Product.** Dirijor is the Private Agent Network OS. Drag agents on a
> canvas → Dirijor provisions a zero-trust mesh on any cloud you own,
> runs every high-stakes output through a multi-agent debate
> (≥95% agreement), and exports a compliance package on demand.
> You get the speed of a 1-click host with the safety posture of a
> regulated enterprise — on infrastructure you own.

### 5-minute pitch

Read [**Why Dirijor**](product/why-dirijor.md) — the long-form problem,
insight, and product narrative. It's the page to send a skeptic, an
investor, or a security reviewer.

---

## Start here

=== "I want to understand Dirijor"

    1. [**Why Dirijor**](product/why-dirijor.md) — the problem we solve and the bet we're making.
    2. [**Realms**](product/concepts/realms.md) — the atomic unit of Dirijor.
    3. [**Consensus**](product/concepts/consensus.md) — how we reach "zero hallucination on high-stakes outputs."
    4. [**Zero-trust by default**](product/concepts/zero-trust.md) — why no public exposure is a *default*, not a feature.

=== "I want to try Dirijor"

    1. [**Tutorial — your first private realm**](guides/tutorials/01-first-realm.md) — **golden path** (10–15 minutes): Core in Docker, canvas via `npm run dev`, `./scripts/verify-golden-path.sh` or `curl /health`, spin to `ready`.
    2. [**Supervisor HTTP API (v0.1)**](reference/supervisor-api.md) — the stable contract the canvas and your tooling bind to.

=== "I want to build on / contribute to Dirijor"

    1. [**Architecture overview**](architecture/overview.md) — a narrated walk through `docs/architecture.mermaid`.
    2. [**Architecture Decision Records**](architecture/adr/README.md) — *why* we chose LangGraph, why consensus is ≥95%, etc.
    3. [**Project context for contributors & agents**](project-context.md) — engineering conventions.
    4. **BMAD workflow** — this repo uses BMAD skills for product + dev; see `AGENTS.md` and `.cursor/rules/dirijor-bmad.mdc` at the repo root.

---

## Non-negotiable promises

These come from the [PRD](DIRIJOR-PRD.md) and drive every page on this site:

- Drag-and-drop Network Canvas with live topology.
- One-click private realm provisioning with Headscale/Tailscale mesh + mTLS + Firecracker sandboxing.
- LangGraph-based supervisor with multi-agent consensus (**≥95% agreement**) + Verified Semantic Cache.
- Safety Fortress: debate loops, anomaly auto-quarantine, human-in-the-loop gates, immutable audit export.
- Cloud-agnostic IaC (Terraform / Pulumi adapters).
- **100% private** — zero public internet exposure by default.

When any page contradicts this list, the PRD wins. File a docs PR.

---

## Current status (v0.1)

- **Supervisor HTTP contract** hardened (Story 3.1) — see [Supervisor API reference](reference/supervisor-api.md).
- **Consensus** — real LangGraph debate loop with configurable rounds and quorum (Story 3.2); optional Qdrant-backed **verified semantic cache** on `POST /consensus` when configured (Story 4.1).
- **Anomaly policy & auto-quarantine** — JSON ruleset, `GET /safety/quarantine/{realm_id}`, gated `POST /safety/signal`, post-consensus hooks + canvas `topology.delta` / `hitl.pending` (Story 4.2, shipped).
- **Canvas ↔ Core WebSocket** — `WS /ws/realm/{realm_id}` with a six-key envelope; v0.1 keeps `_authorize_realm` allow-all — mesh enrollment (Story 5.1) is HTTP/API-driven; scoped WS tokens remain a follow-on. Canvas connects when `NEXT_PUBLIC_DIRIJOR_WS_URL` is set.
- **Canvas shell** operational through Story 1.6 (a11y MVP done).
- **Realm provisioning** — async spin + poll + destroy path with Terraform adapter and default-deny egress hooks (Epic 2, Stories 2.1–2.3).
- **Mesh bootstrap** — Story 5.1 *(shipped, operator-gated)*: Headscale user + tags after `phase == ready`, `realm.mesh.state` events, one-shot `POST /realms/{job_id}/mesh/preauth-key`. **Safety Fortress** **audit export** shipped in Story 4.3; anomaly auto-quarantine in Story 4.2.

The [reference](reference/supervisor-api.md) page is always the truth about what's running *today*.
