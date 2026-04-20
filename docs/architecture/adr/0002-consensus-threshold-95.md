<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# ADR-0002: Consensus threshold ≥95% (not 100%, not majority)

- **Status:** Accepted
- **Date:** 2026-04-16
- **Deciders:** Ramin Allazov (JavaAZE)
- **Related PRD clause:** *"LangGraph-based Dirijor Core supervisor with multi-agent consensus (≥95% agreement) + Verified Semantic Cache."* — [DIRIJOR-PRD.md](../../DIRIJOR-PRD.md)
- **Related stories:** Story 3.2 (consensus debate loop), Story 4.1 (verified semantic cache), Story 4.2 (anomaly policy / auto-quarantine — shipped).

## Context

Dirijor's core safety claim is:

> *"Zero hallucination on high-stakes outputs via consensus + cache."*
> — PRD success criterion

Delivering that claim requires a multi-agent debate loop whose
termination rule answers a pointed question: *when is the group's
agreement sufficient to act?*

The options span a spectrum:

- **Simple majority (>50%).** Low bar, high false-approval rate; two
  agents can outvote one even when the one is right.
- **Supermajority (e.g. 2/3, 3/4).** Better, but still permits a tight
  minority of dissent on actions with real-world consequences.
- **Near-unanimous (≥95%).** Routine disagreement fails the quorum;
  high-confidence agreement passes.
- **Strict unanimity (100%).** Brittle. A single stuck, confused, or
  rate-limited agent can wedge the whole realm.

The **forces** pulling on the decision:

- **Safety force** — false approvals are the loss event we're most
  worried about. We'd rather return "no decision" than approve a
  hallucination.
- **Liveness force** — the system must actually make decisions. A
  threshold that's never met is a denial of service we inflicted on
  ourselves.
- **Pragmatics of agent failure** — agents hang, providers rate-limit,
  prompts vary. Any threshold must tolerate *some* non-agreement that
  isn't "the group actually disagrees."
- **PRD explicit requirement** — the ≥95% number is baked into the
  non-negotiables and the success criteria. Any ADR here has to
  justify that number, not rewrite it.

## Decision

**Adopt ≥95% agreement as the default consensus threshold for
high-stakes outputs. Below threshold → return a structured
"no-decision" outcome with votes and termination reason, never a
silent pass-through.**

Operational specifics:

- **Default threshold = 0.95**, configurable per *action class*:
  destructive actions may raise it; low-stakes reads may lower it or
  skip consensus entirely (the classifier is the supervisor's job).
- **Below-threshold = no decision, not the majority opinion.** The
  response shape carries `consensus_score`, `verified_facts`, and
  `messages`; callers that would have acted treat sub-threshold as a
  hard stop (Story 3.2 AC).
- **Verified semantic cache breaks ties.** Per
  [Consensus](../../product/concepts/consensus.md), agreement on a
  claim the cache contradicts is *not* consensus — the cache lookup
  happens inside the graph, not after it (Story 4.1).
- **Every outcome is audit-streamed.** Votes, per-agent opinions, cache
  hits, termination reason. Compliance exports reconstruct the
  decision (PRD NFR3).

## Consequences

### Positive

- **Hallucination-proof by construction on high-stakes outputs.**
  Routine phrasing-level disagreement fails the quorum; you'd need
  ≥95% of agents to hallucinate the *same* thing — a dramatically less
  likely failure mode than a single agent hallucinating.
- **Liveness is preserved.** 95% tolerates one stuck or rate-limited
  agent in a 20-agent debate, and one disagreeing agent in a 20-agent
  debate where 19 agree. Both of those are realistic.
- **Honest outputs.** "No decision" is a valid, first-class response.
  A hallucination-proof system must be willing to *not answer* — that's
  the point.
- **Audit posture.** Every debate leaves a reconstructable record —
  exactly what compliance exports need (NFR3).

### Negative / costs we accept

- **Latency.** N-agent debates cost N× a single inference plus
  coordination. We mitigate by (a) classifying low-stakes calls out of
  the debate path, and (b) caching agreed-upon claims via the verified
  semantic cache.
- **Cost.** N× inference tokens. Same mitigations as latency.
- **Tuning surface.** The threshold is *per action class* — which is
  powerful but requires disciplined policy authorship. The v0 JSON anomaly
  policy + rule matchers ship in Story 4.2; richer per-action-class tuning
  continues across the Safety Fortress, not in ad hoc config.
- **Correlated hallucination is still possible.** Agents using the same
  model and prompt will correlate. We break correlation with (a)
  heterogeneous agent configurations in the debate, and (b) the
  verified semantic cache grounding.

### What this now commits us to

- **`consensus_score` is a first-class field** in the supervisor's
  `POST /consensus` response. It is already part of the v0.1 contract
  hardened in Story 3.1 — AC 4 forbids removing it without a major
  `schema_version` bump.
- **"No decision" is part of the public contract**, not an exception
  class. Callers must handle it as a non-error outcome.
- **Debate metadata is auditable.** Votes, rounds, termination reason
  must be retained and exportable by Story 4.3 (immutable audit
  export).

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Simple majority (>50%)** | Too permissive. Two confidently-wrong agents outvote one correct one; false approvals are exactly the failure we refuse to ship. |
| **Supermajority (2/3, 3/4)** | Better than majority, but still lets a meaningful minority disagree on real-world-consequential actions. For high-stakes outputs, ≥95% is the right side of the safety/liveness trade. |
| **Strict unanimity (100%)** | Brittle: one stuck or rate-limited agent wedges the realm. Empirically, ≥95% delivers effectively unanimous agreement while tolerating operational reality. |
| **Confidence-weighted voting** (weight by self-reported confidence) | Self-reported LLM confidence is known to be poorly calibrated; making the vote more sophisticated on top of an unreliable signal adds complexity without adding safety. Revisit if calibration improves. |
| **Fixed threshold with no per-action-class override** | Simpler, but wrong: "approve a refund" and "summarize this doc" do not deserve the same threshold. The per-action-class policy is worth the tuning surface. |
| **Replace consensus with a single "judge" agent** | Concentrates hallucination risk into one point of failure. Moves the problem, doesn't solve it. |

## References

- PRD non-negotiable + success criterion: [DIRIJOR-PRD.md](../../DIRIJOR-PRD.md)
- Concept page: [Consensus](../../product/concepts/consensus.md)
- Supervisor API reference (v0.1 `POST /consensus` contract): [`../../reference/supervisor-api.md`](../../reference/supervisor-api.md)
- ADR-0001 (why LangGraph hosts the debate loop): [0001-langgraph-supervisor.md](0001-langgraph-supervisor.md)
- Story 3.2 (consensus beyond placeholder): `_bmad-output/planning-artifacts/epics.md` (in the repo)
- Story 4.1 (verified semantic cache — Qdrant): same planning artifact.
- Story 4.2 (anomaly policy & quarantine): same planning artifact.
