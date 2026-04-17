<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# Architecture Decision Records (ADRs)

> **Purpose.** Capture the *why* behind significant, hard-to-reverse
> engineering decisions — with enough context that a future contributor
> (human or agent) can understand the decision, evaluate whether its
> forces still hold, and know how to supersede it if not.

This directory follows the
[**MADR**](https://adr.github.io/madr/) template: each record is a small
Markdown file, dated, with an explicit status, the forces in play, the
decision, and the consequences — good and bad.

## Index

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-langgraph-supervisor.md) | LangGraph as the supervisor substrate | Accepted | 2026-04-16 |
| [0002](0002-consensus-threshold-95.md) | Consensus threshold ≥95% (not 100%, not majority) | Accepted | 2026-04-16 |

## Rules of the road

1. **Never delete an ADR.** If a decision is reversed, write a new ADR
   and mark the old one `Superseded by ADR-000N`. The history is the
   value.
2. **One decision per record.** If you find yourself writing two, split them.
3. **Date every ADR.** A decision is only defensible in the context of
   when it was made — model capability in April 2026 is not model
   capability in April 2028.
4. **Record forces, not just the verdict.** "We chose LangGraph" is
   useless. "We chose LangGraph because we needed stateful graphs and
   didn't want to own the scheduler" is evergreen.
5. **Keep ADRs short.** Two pages is plenty. If you need more, the
   decision probably isn't decomposed cleanly.

## When to write an ADR

Write one when the decision meets *any* of these criteria:

- It's hard to reverse (data model, framework choice, cross-service protocol).
- It constrains multiple future stories (e.g. the supervisor's HTTP schema version policy).
- A future contributor would reasonably ask "why did they do it this way?" and the answer is non-obvious.
- It resolves a disagreement among reasonable people.

You do **not** need an ADR for every code change. PRs and stories are
the right granularity for most work.

## Template

New ADRs should follow `0001-langgraph-supervisor.md` as a pattern:

- `# ADR-NNNN: Short verb-first title`
- `Status: Proposed | Accepted | Superseded by ADR-NNNN | Deprecated`
- `Date: YYYY-MM-DD`
- `## Context` — the forces; what problem, what constraints, what alternatives are on the table
- `## Decision` — the verdict, stated plainly
- `## Consequences` — good, bad, and *what this now commits us to*
- `## Alternatives considered` — each alternative + why it lost
- `## References` — PRD sections, stories, external links

Numbering is strictly monotonic; reserve a number by opening the PR.
