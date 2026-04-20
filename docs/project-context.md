# Dirijor — project context

Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

BMAD and other agents: use this file with `docs/DIRIJOR-PRD.md` and `docs/architecture.mermaid` as the baseline for decisions and docs.

## Product

Private Agent Network OS: zero-trust realms, canvas-driven topology, Dirijor Core (LangGraph supervisor), Safety Fortress, cloud-agnostic IaC, OpenClaw-oriented runtimes. See PRD for non-negotiables and success metrics.

## Repository layout (high level)

- `docs/` — PRD, architecture (Mermaid), this file
- `backend/dirijor-core/` — FastAPI + LangGraph supervisor (v0.1; real consensus loop + optional semantic cache + Story 4.2 anomaly/quarantine hooks; see `docs/reference/supervisor-api.md`)
- `backend/openclaw-wrapper/` — agent runtime wrapper
- Terraform / docker-compose at repo root for early provisioning
- `_bmad/` — BMAD BMM skills and workflows (version in `_bmad/_config/manifest.yaml`)
- `_bmad-output/` — generated BMAD artifacts (gitignored)

## Engineering conventions

- Match existing file headers and copyright lines in new code.
- Prefer small, focused changes; extend existing modules before adding parallel stacks.
- Python: FastAPI + LangGraph in `dirijor-core`; keep API contracts stable when iterating.

## Language

- User-facing and agent communication: English unless config specifies otherwise (`_bmad/_memory/config.yaml`).
