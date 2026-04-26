# BMAD pipeline runner (local “Go”)

This repository includes a **small stdlib Python CLI** that reads `_bmad-output/implementation-artifacts/sprint-status.yaml` and prints a **machine-checkable work plan** for Epic/story work. It does **not** call OpenAI, Cursor, or any LLM; it **orchestrates artifacts** and optional local commands (hints, `pytest`).

## Commands

```bash
# Show full sprint + current_story_* pointers
python scripts/bmad_pipeline.py status

# Epic 9 (GTM wave) only: filter development_status to epic-9 and 9-x keys
python scripts/bmad_pipeline.py status --epic 9

# Print a ordered “go” plan (story review → dev → code review → commit → PR/CI)
python scripts/bmad_pipeline.py go --epic 9

# Machine-readable (CI, or a future wrapper)
python scripts/bmad_pipeline.py --json go --epic 9
python scripts/bmad_pipeline.py --json status

# After go plan: optional local gates (staged area hints, full Core tests)
python scripts/bmad_pipeline.py go --epic 9 --hints --tests
```

`--sprint` overrides the path to `sprint-status.yaml` (default: `_bmad-output/implementation-artifacts/sprint-status.yaml`).

## What “Go” means here

- **Not** a single button that spawns Cursor agents (there is no stable public API for that in-editor).
- **Not** an auto-update to `sprint-status.yaml`, the story file, or git: **nothing “moves”** when you run `go` unless you also run `--hints` / `--tests`, which only run those local commands.
- **Yes** a single **contract**: current story, first `ready-for-dev` in the map, and an ordered `stages[]` you can hand to:
  - a human, or
  - **Cursor chat** (“execute stage 03-dev using `bmad-dev-story` and this story file path”), or
  - **GitHub Actions** later (label → workflow reads `--json` output and posts instructions).

### After `bmad-dev-story`, status is usually `review`

The plan **skips** pre-dev story review (stages 01–02) and dev (03) once the sprint pointer is no longer `ready-for-dev` / `in-progress`. If your story is **`review`**, the printed **suggested next** line points at **code review (04)** — that is the next *manual* Cursor step, not something the terminal script runs for you.

## Human blockers (by design)

Stop and notify a human when the story or CI needs:

- Cloud or LLM **API keys** not in the environment
- **Billing** / spend approval
- **Prod** or destructive **infra** apply
- **Ambiguous** product or architecture choice
- **Failing** checks the agent is not allowed to fix by policy

The runner does not send notifications; add Slack/email in CI if you need that.

## Related

- Commit discipline: [Git, commits & BMAD stories](git-and-story-commits.md)
- Cursor skill: `.cursor/skills/bmad-story-git-traceability/SKILL.md`
- Source: `scripts/bmad_pipeline.py`
