#!/usr/bin/env bash
# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
#
# Advisory: map changed paths to BMAD / epic areas so commit messages and
# story boundaries stay aligned. See docs/guides/git-and-story-commits.md
#
# Usage:
#   scripts/git/story-commit-hints.sh          # working tree + index (unmerged unique paths)
#   scripts/git/story-commit-hints.sh --staged  # index only (e.g. before commit)

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "story-commit-hints: not inside a git repository" >&2
  exit 1
}
cd "$REPO_ROOT"

collect_files() {
  if [[ "${MODE:-}" == "staged" ]]; then
    git diff --cached --name-only --diff-filter=ACDMRT 2>/dev/null || true
  else
    {
      git diff --name-only --diff-filter=ACDMRT 2>/dev/null || true
      git diff --cached --name-only --diff-filter=ACDMRT 2>/dev/null || true
    } | sort -u
  fi
}

MODE="all"
if [[ "${1:-}" == "--staged" ]]; then
  MODE="staged"
fi

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: story-commit-hints.sh [--staged]

  --staged   Only look at the git index (after git add). Recommended before commit.

Prints which high-level "areas" your changes touch. If multiple unrelated areas
appear, consider splitting commits or writing a subject/body that names all of them.
EOF
  exit 0
fi

FILES=()
while IFS= read -r _line; do
  [[ -n "$_line" ]] && FILES+=("$_line")
done < <(collect_files)
if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "story-commit-hints: no matching changed files (try: git add … ; then: $0 --staged)"
  exit 0
fi

TAGS=()
add_tag() {
  local t="$1"
  local x
  for x in "${TAGS[@]:-}"; do
    [[ "$x" == "$t" ]] && return
  done
  TAGS+=("$t")
}

for f in "${FILES[@]}"; do
  [[ -z "$f" ]] && continue
  case "$f" in
  terraform/modules/headscale-control/*)
    add_tag "9.3 / Headscale control plane (terraform/modules/headscale-control)"
    ;;
  docker-compose.headscale.yml|ops/headscale/*)
    add_tag "9.3 / Headscale local ops (ops/headscale or docker-compose.headscale)"
    ;;
  backend/dirijor-core/tests/test_headscale_control_module.py)
    add_tag "9.3 / headscale hermetic tests"
    ;;
  terraform/modules/private-realm/*|backend/dirijor-core/tests/test_private_realm_module.py|backend/dirijor-core/tests/test_cloud_init_render.py)
    add_tag "Private realm / DO droplets (Epic 2 + 9.1/9.2)"
    ;;
  *marketplace*)
    add_tag "Marketplace / import draft (e.g. Story 7.2 — confirm active story)"
    ;;
  *Marketplace*)
    add_tag "Marketplace / import draft (e.g. Story 7.2 — confirm active story)"
    ;;
  backend/dirijor-core/mesh_bootstrap.py|backend/dirijor-core/tests/test_mesh_bootstrap.py)
    add_tag "Mesh / Headscale API client (mesh_bootstrap; scope to current story)"
    ;;
  _bmad-output/implementation-artifacts/sprint-status.yaml)
    add_tag "sprint-status.yaml (sync development_status + stories: block)"
    ;;
  *supervisor.py|*/supervisor.py)
    add_tag "Supervisor surface (can span stories — name them in the commit body)"
    ;;
  esac
done

echo "=== story-commit-hints (mode: ${MODE}) ==="
if [[ ${#TAGS[@]} -eq 0 ]]; then
  echo "No mapped epic/story area for these paths (extend scripts/git/story-commit-hints.sh if this commit is story-scoped):"
  printf '  %s\n' "${FILES[@]}"
  exit 0
fi

for t in "${TAGS[@]}"; do
  echo "• $t"
done

if [[ ${#TAGS[@]} -gt 1 ]]; then
  echo ""
  echo "WARNING: Multiple story/epic areas in one change set."
  echo "  Prefer: split commits, OR one subject with the primary story and a body that lists every area."
  echo "  See: docs/guides/git-and-story-commits.md"
fi

exit 0
