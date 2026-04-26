# Optional git hooks (Dirijor)

**Not enabled by default.** To use the `prepare-commit-msg` hook that appends **commented** `story-commit-hints` output to your commit template:

```bash
git config core.hooksPath scripts/githooks
```

- Hints are `#` lines; git strips them from the final message when you save in the editor (same as other commented template lines).
- If you already use a global `core.hooksPath`, either skip this or compose hooks yourself—do not overwrite without checking.

See `docs/guides/git-and-story-commits.md` for the full policy and `scripts/git/story-commit-hints.sh` for path mapping.
