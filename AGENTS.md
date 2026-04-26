# Agent instructions (Dirijor)

- **Product:** `docs/DIRIJOR-PRD.md`, `docs/architecture.mermaid`, `docs/project-context.md`
- **BMAD:** `_bmad/` (BMM) with Cursor skills generated in `.cursor/skills/`. Load the relevant `.cursor/skills/bmad-*/SKILL.md` before running a BMAD workflow; config in `_bmad/_memory/config.yaml`. Outputs go to `_bmad-output/` (gitignored).

Cursor applies `.cursor/rules/dirijor-bmad.mdc` for full BMAD + doc discipline.

## Git vs BMAD stories

- **Policy:** `docs/guides/git-and-story-commits.md`
- **Advisory (run before commit):** `scripts/git/story-commit-hints.sh --staged`
- **Cursor skill:** `.cursor/skills/bmad-story-git-traceability/SKILL.md`
- **Optional hook:** `scripts/githooks/README.md` (`core.hooksPath=scripts/githooks`)
- **Pipeline runner:** `docs/guides/bmad-pipeline.md` — `python scripts/bmad_pipeline.py go --epic 9` (or omit `--epic`); `--json` for machine output; `--hints` / `--tests` with `go` for local gates.
