# Git, commits, and BMAD story traceability

This guide prevents **mismatch** between `git log`, BMAD **story files**, and `sprint-status.yaml` (e.g. a commit message that only describes one feature while the diff also contains another story’s work).

## Principles

1. **One story → prefer one commit (or one clearly scoped series).** If you must land multiple stories in one PR, use **one commit per story** on the branch so `git log -- path` is honest.
2. **Subject line must name the work.** Include the BMAD **story key** (e.g. `9-4-supervisor-joins-...` or a short form like `9-4` / `story-9-4`) *or* a conventional scope that unambiguously maps to the story, e.g. `feat(9-4-supervisor-mesh): ...`.
3. **Body lists every major area** touched if the change set is not tiny (Terraform + Core + frontend → three bullets in the body).
4. **Before marking a story `done` or `review`**, run path-scoped history so the message matches the files:
   - `git log -1 --oneline -- path/to/expected/`
   - `git show --stat HEAD`

## BMAD / agent steps

- **`bmad-dev-story`:** Before the **first** `git commit` for this story, run `scripts/git/story-commit-hints.sh --staged` and follow any warnings. When completing Step 7 / closing the story, add the **current commit short hash** (or merge commit) to the story **Change Log** / **Dev Agent Record** *only if your team uses that field*; avoid stale hashes after rebase—prefer `git log -1 --oneline` over pasting a hash that may change.
- **`bmad-code-review` / human merge:** Reject or split commits where the **subject** does not reflect **all** epic-sized areas in `--stat` (unless explicitly squash-merged with a rewritten message that does).
- **`sprint-status.yaml`:** After merge, keep **`development_status`** and the detailed **`stories:`** block in sync (same story keys and statuses). Update `current_story_key` when moving to the next `ready-for-dev` story.

## Optional automation

- **Advisory only (default):**  
  `scripts/git/story-commit-hints.sh --staged`  
  Emits which “areas” (mapped from path prefixes) your staged files touch so you can adjust the message or split the commit.

- **Optional git hook (opt-in):**  
  `git config core.hooksPath scripts/githooks`  
  Then a `prepare-commit-msg` hook can append hints (see `scripts/githooks/README` inside that directory). Do not enable if you use another hooks path globally without composing them.

## Anti-patterns

- **Megacommit, single-slice message** — e.g. subject says `marketplace` only, but the diff also adds `terraform/modules/headscale-control/`. `git log` will mislead every future forensics and BMAD routing.
- **Relying on “last commit on main”** to prove what shipped for a story—always use **path-scoped** `git log` for that story’s tree.

## Related

- Story files: `{project}/_bmad-output/implementation-artifacts/*-*.md` (or promoted paths if you copy artifacts into `docs/`).
- Sprint: `_bmad-output/implementation-artifacts/sprint-status.yaml` (and `current_story_key` at file bottom).
- **Go plan CLI:** [BMAD pipeline (go plan)](bmad-pipeline.md) — `python scripts/bmad_pipeline.py go --epic 9` / `--json`.
