---
name: bmad-story-git-traceability
description: >-
  Align git commits and BMAD story files: run story-commit-hints, split commits,
  sync sprint-status. Use when the user asks about story/git alignment, commit
  messages per story, or avoiding megacommit confusion.
---

## When to use

- Before or after a big change: **does `git log` match the BMAD story** you think you shipped?
- User wants **automation** or **habits** for story keys in commit subjects, or to fix **sprint-status** / **stories:** drift.

## Steps (agents and humans)

1. Read **`docs/guides/git-and-story-commits.md`** (principles + BMAD steps).
1b. For a one-shot “what’s next for this epic?” run **`python scripts/bmad_pipeline.py go --epic 9`** (or your epic); use **`--json`** for scripts/CI. See **`docs/guides/bmad-pipeline.md`**.
2. Run **`scripts/git/story-commit-hints.sh --staged`** after `git add` and before `git commit`.
3. If the script prints **WARNING: Multiple story/epic areas**, either **split commits** (one per story) or write a **subject + body** that names every area; never a one-line body that omits a second epic.
4. When updating **`sprint-status.yaml`**, update **both** `development_status` and the verbose **`stories:`** block for the same keys.
5. Optional: **`git config core.hooksPath scripts/githooks`** to get commented hints in the commit template (`scripts/githooks/README.md`).

## Related BMAD workflows

- **`bmad-dev-story`:** workflow step 7 includes a commit / traceability action (see `.cursor/skills/bmad-dev-story/workflow.md`).

Do not add new path rules here; extend **`scripts/git/story-commit-hints.sh`** so the script stays the single mapping table.
