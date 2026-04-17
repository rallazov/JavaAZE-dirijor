<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# Map of the docs

This site is organized by **what you're trying to do**, not by feature.
It follows the [Diátaxis](https://diataxis.fr/) framework, which splits
documentation into four quadrants so readers never have to guess which
kind of page they're on.

| If you want to… | Go to | Why this split exists |
|---|---|---|
| **Understand what Dirijor is and why it exists** | [Product → Why Dirijor](product/why-dirijor.md) | Explanation docs tell you *why*, with trade-offs. They're the page to send a skeptic. |
| **Learn the core ideas** (realms, consensus, zero-trust) | [Product → Concepts](product/concepts/realms.md) | Concept pages stay stable across releases — they're vocabulary. |
| **Get your first realm running** | [Guides → Tutorials](guides/tutorials/01-first-realm.md) | Tutorials are hand-held and guaranteed to succeed. Learning, not problem-solving. |
| **Solve a specific task** (add a cloud, configure a gate) | Guides → How-to *(coming as epics ship)* | How-to guides are recipes. They assume you already know the concepts. |
| **Look up an exact API / schema / flag** | [Reference → Supervisor API](reference/supervisor-api.md) | Reference is dry, complete, authoritative. No opinions. |
| **Understand how the system is built and why** | [Architecture → Overview](architecture/overview.md) | Internal-facing; mirrors `docs/architecture.mermaid` in prose. |
| **See why a major engineering bet was made** | [Architecture → Decision Records](architecture/adr/README.md) | ADRs are dated, immutable decisions. Superseded, never deleted. |

## Audience map

- **External / product-curious readers** live in `product/` and `guides/`.
- **Operators and engineers integrating with Dirijor** live in `reference/` and `guides/`.
- **Contributors and BMAD agents** live in `architecture/`,
  [`project-context.md`](project-context.md), and `AGENTS.md` at the repo root.

## Source-of-truth docs (unchanged, referenced from elsewhere)

- [`DIRIJOR-PRD.md`](DIRIJOR-PRD.md) — product requirements, non-negotiables, success criteria.
- [`architecture.mermaid`](architecture.mermaid) — canonical system diagram.
- [`project-context.md`](project-context.md) — agent + contributor conventions.

The narrative docs in `product/` and `architecture/` **link to** these canonical
sources rather than duplicating them. When the PRD or the diagram changes,
those pages remain the single source of truth.

## Editing discipline

- Docs PRs live next to code PRs. A feature is not "done" until its doc
  section is updated.
- ADRs are never deleted. Supersede them instead (`Status: Superseded by ADR-000N`).
- Tutorials carry a `Last verified:` line with date + commit SHA. If the
  line is stale, treat the tutorial as untrusted until a maintainer re-runs it.
- Prose voice is English, direct, and explains the *why* before the *what* —
  matching `docs/project-context.md` and the PRD's non-negotiables.

## Running the site locally

```bash
pip install -r docs/requirements.txt
mkdocs serve     # http://127.0.0.1:8000
```

Build static HTML for hosting:

```bash
mkdocs build     # outputs ./site/ (gitignored)
```
