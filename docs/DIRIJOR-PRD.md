# Dirijor PRD – Private Agent Network OS
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

## Vision
Cutting-edge platform for safety and security of LLM agents and humans who use them.  
A user-friendly application where anyone can configure private zero-trust network realms for OpenClaw-style agents across unlimited virtual instances on any private cloud (DigitalOcean, Hetzner, Proxmox, self-hosted, etc.).

## Core Non-Negotiable Requirements
- Drag-and-drop Network Canvas (React Flow) with live topology
- One-click Private Realm provisioning with Headscale/Tailscale mesh + mTLS + Firecracker sandboxing
- LangGraph-based Dirijor Core supervisor with multi-agent consensus (≥95% agreement) + Verified Semantic Cache
- Safety Fortress: debate loops, anomaly auto-quarantine, human-in-the-loop gates, immutable audit export
- Cloud-agnostic IaC (Terraform/Pulumi adapters)
- 100% private — zero public internet exposure by default
- Turns raw OpenClaw agents into safe, orchestrated digital employees

## Success Criteria
- Spin a 10-agent secure realm in <60 seconds
- Zero hallucination on high-stakes outputs via consensus + cache
- Exportable compliance package from any realm
- Works for solo humans and enterprise teams

## Current State
We have v0.1 files: canvas, supervisor stub, OpenClaw wrapper, basic Terraform, docker-compose, mermaid architecture.

## Competitive Landscape Update (April 2026)
Hostinger offers 1-click OpenClaw on VPS with basic container isolation.  
This validates demand but does NOT solve:
- Private network configuration canvas
- Multi-agent orchestration & consensus
- Hallucination-proof safety fortress
- Unlimited isolated realms across any private cloud
Dirijor becomes the missing secure control plane.

---

## GTM-Grade Additions (added 2026-04-22 by bmad-correct-course)

> The sections above remain the v0.1 product thesis. The sections below extend the PRD to GTM-grade (v1.0) per Sprint Change Proposal 2026-04-22. They are the authoritative source for FR13–FR18 and NFR10–NFR15; Epics 9–16 in `_bmad-output/planning-artifacts/epics.md` implement these requirements.

### Extended Functional Requirements

**FR13 — Hosted control plane.** The platform provides a publicly reachable hosted control plane (HTTPS + TLS) where users sign up, sign in, manage their tenant, spin realms in their own cloud accounts, and manage their subscription. Hosted control plane runs on fly.io (ADR-0009); tenant realms remain in customer cloud accounts (DO, AWS).

**FR14 — Identity and access.** Authentication is federated via OpenID Connect (ADR-0007) — no first-party password storage. Authorization is role-based across `owner`, `admin`, `operator`, `viewer` × `global`, `tenant:<id>`, `realm:<id>` scopes. Machine-to-service authentication uses scoped, revocable API keys (`dk_live_<prefix>.<secret>` format, argon2id-hashed). WebSocket upgrades validate identity (not a stub).

**FR15 — Tenancy and team collaboration.** The platform supports multi-tenant isolation with query-layer tenant filtering (ADR-0011). Users create or join tenants via email invite (single-use 7-day tokens). All realms, audit events, and API keys are scoped to a tenant; cross-tenant access returns `403 wrong_tenant_context`.

**FR16 — Subscriptions and metered entitlements.** The platform integrates with Stripe for subscription lifecycle (checkout, portal, webhooks). Three plan tiers (Free / Pro $29/mo per seat / Enterprise custom) with a typed entitlement matrix enforced at every quota gate. Gate failures return `402 entitlement_exceeded` with `upgrade_url`.

**FR17 — User data rights.** Users can export all personal data (`GET /api/me/export`) and request deletion (`DELETE /api/me` with 2-step confirmation). Deletion soft-deletes the user (anonymized email via `.invalid` TLD, retained for audit integrity); realms owned by the user must be destroyed by the operator first (`409 owned_realms_exist`).

**FR18 — Incident communication.** The platform maintains a public status page with components (API / Canvas / Realm provisioning per cloud / Mesh control plane / Auth) and states (operational / degraded / partial outage / major outage / maintenance). SLO breaches auto-draft incidents within 15 minutes of detection. Postmortems are public by default under `docs/postmortems/`.

### Extended Non-Functional Requirements

**NFR10 — Durability.** Realm, job, user, session, and audit records survive supervisor restarts and cross-replica deploys via Postgres persistence (ADR-0008). Idempotency keys on `POST /realms/spin` prevent duplicate provisioning on retry (24h retention window).

**NFR11 — Availability SLOs.** The platform operates against four continuously-measured SLOs with 30-day rolling error budgets:
- API availability: 99.5% non-5xx HTTP responses (~3.6h/month allowed downtime)
- Spin success: 95% of valid spin requests reach `ready` phase within 7-day window
- WebSocket connect success: 99% of WS upgrade attempts succeed (auth denials excluded)
- TTL auto-destroy latency: 95% of triggered auto-destroys complete within 60s

Budget consumption gates feature work (50% = review, 80% = freeze, 100% = reliability-only sprint).

**NFR12 — Supply-chain integrity.** The build pipeline scans every PR with Trivy (images), pip-audit (Python), npm audit (Node); CRITICAL findings block merge. SBOMs (CycloneDX format) are generated and attached to every GitHub Release. Dependabot is enabled on all ecosystems with security patch auto-merge on passing CI.

**NFR13 — Privacy posture.** The platform claims GDPR *alignment* (not certified compliance) per Story 15.4: users can access, export, delete, and correct their data; retention windows are documented per table; third-party data processors are enumerated (fly.io, OIDC provider, Grafana Cloud, Stripe). Privacy policy is versioned markdown at `docs/compliance/privacy-policy.md`.

**NFR14 — Cost envelope per realm (MVP).** Developer and pilot realms operate within a strict $20/month hard ceiling enforced by (a) environment variable caps (max agents per realm, max total nodes globally), (b) Terraform `validation` blocks at plan time, (c) TTL auto-destroy on idle (default 2h), (d) downgrade-grace realm destruction (7-day notice on Pro → Free). Cross-cloud shared envelope prevents silent doubling.

**NFR15 — Compliance readiness.** The platform maintains an honest, self-assessed SOC 2 readiness document walking Common Criteria CC1–CC9 with Implemented / Partial / Not Implemented / N/A verdicts and evidence links. Trust Services Categories claimed at MVP: Security + Availability. Certification itself is post-MVP (3–9 month audit engagement, $15–50k, separate project).

### Target Operating Costs

- **Developer (local):** $0
- **CI pipeline:** $0 (GHCR private images on free tier; GitHub Actions free tier sufficient through MVP)
- **Pilot realms (DigitalOcean):** ≤ $20/month hard ceiling, auto-destroy on idle
- **Pilot realms (AWS):** $0 for year 1 on AWS free tier (t3.micro × 750 hrs/month); post-free-tier ≤ $20/month via shared envelope
- **Hosted control plane (fly.io, first 100 users):** ~$15–30/month (fly Postgres shared-cpu-1x + 2 × shared-cpu-1x supervisor instances + canvas app)
- **Observability (Grafana Cloud free tier):** $0 (10k series + 50GB logs + 50GB traces)
- **Status page (statuspage.io free tier):** $0
- **Dependency scanning (Dependabot + GH-native):** $0

### Dependencies and Vendor Inventory (MVP-scope)

| Vendor | Role | Cost at MVP | Escape hatch |
|---|---|---|---|
| DigitalOcean | Tenant realm infra (Epic 9) | Customer-paid; dev ≤ $20/mo | AWS via Epic 10 |
| AWS | Tenant realm infra (Epic 10) | Customer-paid; dev $0 free tier year 1 | DO via Epic 9 |
| fly.io | Hosted control plane (Epic 13) | ~$15–30/mo | Containerized → AWS ECS / Render / self-host per ADR-0009 |
| Postgres 16 | Durable state (Epic 11+12+13) | Included in fly Postgres | Portable (self-host / RDS / Supabase) |
| Headscale | Mesh control plane (Epic 9+10) | $4/mo droplet | Tailscale SaaS (not chosen for MVP) |
| OIDC provider (Google/GitHub/Microsoft/Clerk) | Identity (Epic 11) | Free tier | Swap OIDC issuer; any issuer supported per ADR-0007 |
| Stripe | Subscriptions (Epic 16) | 2.9% + $0.30 per txn | Lemon Squeezy / Paddle (rejected for MVP per ADR-0011) |
| Grafana Cloud | Observability backend (Epic 13) | Free tier | Honeycomb / Datadog documented per Story 13.4 |
| Postmark or Resend | Transactional email (Epic 16) | Free tier 100/mo or 100/day | SES documented as fallback |
| GHCR | Container registry (Epic 13) | Free tier for private images | DockerHub / ECR portable |
| Dependabot / Trivy / pip-audit / npm audit | Supply chain (Epic 15) | Free | Self-hosted equivalents documented |
| statuspage.io | Public status page (Epic 15) | Free tier | Self-host `cstate` / `statusfy` documented |

### Revisit Triggers

The following decisions are explicitly scheduled for re-evaluation at defined signals:

- **fly.io → AWS ECS:** when an enterprise buyer contractually requires it (ADR-0009).
- **Postgres LISTEN/NOTIFY → Redis:** when benchmarks show > 10k events/sec/realm sustained (ADR-0008).
- **Hardened Docker → Firecracker:** when a signed pilot requires microVM attestation, OR when compute costs drop to make Firecracker viable at MVP tier, OR when a security incident surfaces a Docker-escape path not covered by current hardening (ADR-0010).
- **Query-layer tenant filter → Postgres RLS:** when application-layer trust boundary alone is insufficient for a regulated workload (ADR-0011).
- **Stripe → Lemon Squeezy / Paddle:** when international tax handling complexity outweighs Stripe developer ergonomics (ADR-0011).
- **In-app marketing pages → separate marketing site:** when marketing copy iterates materially faster than product (ADR-0011).
- **Self-assessed SOC 2 readiness → Type I/II certification:** when a pilot pipeline of sufficient size (target: ≥ 3 enterprise pilots in parallel negotiation) justifies the $15–50k / 3–9 month investment.

---

*End of PRD extensions (GTM-grade v1.0, added 2026-04-22).*

