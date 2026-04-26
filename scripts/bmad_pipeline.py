#!/usr/bin/env python3
# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
#
# Local BMAD pipeline helper: read sprint-status.yaml, show Epic progress, emit a
# "go plan" of agent handoffs (orchestrates artifacts; does not call cloud LLM APIs).
#
# Usage:
#   python scripts/bmad_pipeline.py status [--epic 9]
#   python scripts/bmad_pipeline.py go [--epic 9] [--hints] [--tests]
#   python scripts/bmad_pipeline.py --json status

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_sprint_path(root: Path, data: str) -> str:
    """Resolve {project-root} in sprint paths."""
    t = data.strip().strip('"')
    return t.replace("{project-root}/", f"{root}/").replace("{project-root}", str(root))


def _parse_sprint_pointers_line(out: dict[str, Any], line: str) -> None:
    m = re.match(r'^current_story_key:\s*"(?P<q>[^"]*)"\s*$', line) or re.match(
        r"^current_story_key:\s*(?P<q>[^\s#]+)\s*$", line
    )
    if m:
        out["current_story_key"] = m.group("q")
    m = re.match(r'^current_story_status:\s*"(?P<q>[^"]*)"\s*$', line) or re.match(
        r"^current_story_status:\s*(?P<q>[\w-]+)\s*$", line
    )
    if m:
        out["current_story_status"] = m.group("q")
    m = re.match(r'^current_story_file:\s*"(?P<q>[^"]*)"\s*$', line)
    if m:
        out["current_story_file"] = m.group("q")
    m = re.match(r'^next_ready_story_key:\s*"(?P<q>[^"]*)"\s*$', line) or re.match(
        r"^next_ready_story_key:\s*(?P<q>[^\s#]+)\s*$", line
    )
    if m:
        out["next_ready_story_key"] = m.group("q")
    m = re.match(r'^next_ready_story_file:\s*"(?P<q>[^"]*)"\s*$', line)
    if m:
        out["next_ready_story_file"] = m.group("q")


def load_sprint_file(path: Path) -> dict[str, Any]:
    """Load sprint-status.yaml: `development_status` (2-space keys) and later sprint pointers.

    Stays stdlib-only (no PyYAML). The repo places `current_story_key` *after* `development_status`.
    """
    text = path.read_text(encoding="utf-8")
    out: dict[str, Any] = {
        "development_status": {},
        "current_story_key": None,
        "current_story_status": None,
        "current_story_file": None,
        "next_ready_story_key": None,
        "next_ready_story_file": None,
    }
    phase = "pre"
    for line in text.splitlines():
        if phase == "pre":
            if line.rstrip() == "development_status:" or re.match(r"^development_status:\s*$", line):
                phase = "dev"
            continue
        if phase == "dev":
            if line.startswith("  "):
                raw = line.rstrip()
                st = raw[2:].lstrip()
                if not st or st.startswith("#"):
                    continue
                if ":" not in st:
                    continue
                k, v = st.split(":", 1)
                k, v = k.strip(), v.strip()
                if k.startswith("#"):
                    continue
                v = re.sub(r"\s*#.*$", "", v)
                v = v.strip().strip('"')
                out["development_status"][k] = v
                continue
            if not line.strip():
                continue
            phase = "post"
        if phase == "post":
            _parse_sprint_pointers_line(out, line)
    return out


def _story_sort_key(sid: str) -> tuple:
    m = re.match(r"^(\d+)-(\d+)-", sid)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (999, 999)


def filter_epic(dev: dict[str, str], epic_num: int) -> dict[str, str]:
    prefix = f"{epic_num}-"
    ekey = f"epic-{epic_num}"
    st: dict[str, str] = {}
    for k, v in dev.items():
        if k == ekey or (k.startswith(prefix) and re.match(r"^\d+-\d+-", k)):
            st[k] = v
    return st


def print_status(root: Path, data: dict[str, Any], epic: int | None) -> None:
    dev = data["development_status"]
    if epic is not None:
        dev = filter_epic(dev, epic)
        print(f"=== Epic {epic} (development_status filter) ===")
    else:
        print("=== development_status (full) ===")
    for k in sorted(dev.keys(), key=_story_sort_key):
        print(f"  {k:55} {dev[k]}")

    print()
    print("=== sprint pointer ===")
    cs = _parse_sprint_path(root, str(data.get("current_story_file") or "")) if data.get("current_story_file") else ""
    print(f"  current_story_key:     {data.get('current_story_key')}")
    print(f"  current_story_status:  {data.get('current_story_status')}")
    print(f"  current_story_file:    {cs or data.get('current_story_file')}")
    print(f"  next_ready_story_key:  {data.get('next_ready_story_key')}")


def first_ready_story(dev: dict[str, str]) -> str | None:
    """First story key (by numeric id) in ready-for-dev."""
    cands = [k for k, v in dev.items() if v == "ready-for-dev" and re.match(r"^\d+-\d+-", k)]
    cands.sort(key=_story_sort_key)
    return cands[0] if cands else None


def go_plan(
    _root: Path,
    data: dict[str, Any],
    epic: int | None,
) -> list[dict[str, str]]:
    """Ordered machine-readable stages for a human/CI to drive agents (not auto-spawned)."""
    key = data.get("current_story_key")
    status = (data.get("current_story_status") or "").lower()
    stages: list[dict[str, str]] = []
    fpath = f"_bmad-output/implementation-artifacts/{key}.md" if key else ""
    # Pre-dev story hardening: only when work has not left "ready for implementation".
    if key and status == "ready-for-dev":
        stages.append(
            {
                "stage": "01-story-review-1",
                "action": "Fresh context. Load bmad-create-story checklist / validate story file.",
                "skill": "bmad-create-story (checklist) or bmad-validate (if you add it)",
                "artifact": fpath,
            }
        )
        stages.append(
            {
                "stage": "02-story-review-2",
                "action": "Optional second pass: re-read only story + epics diff; patch story file.",
                "skill": "Same as above or manual",
                "artifact": fpath,
            }
        )
    if key and status in ("ready-for-dev", "in-progress"):
        stages.append(
            {
                "stage": "03-dev",
                "action": "Run bmad-dev-story on the story file; implement ACs; tests green.",
                "skill": "bmad-dev-story",
                "artifact": fpath,
            }
        )
    if key and status in ("ready-for-dev", "in-progress", "review"):
        stages.append(
            {
                "stage": "04-code-review-1",
                "action": "Fresh context, different model. bmad-code-review (adversarial).",
                "skill": "bmad-code-review",
                "artifact": "git diff against main + story file",
            }
        )
        stages.append(
            {
                "stage": "05-code-review-2",
                "action": "Verifier: re-run tests, sanity-check only story-scoped diffs.",
                "skill": "Optional bmad-qa or pytest only",
                "artifact": "CI / local tests",
            }
        )
    stages.append(
        {
            "stage": "06-commit",
            "action": f"git add, scripts/git/story-commit-hints.sh --staged, commit with story id ({key or 'N/A'}) in subject.",
            "skill": "git",
            "artifact": "commit",
        }
    )
    stages.append(
        {
            "stage": "07-pr-ci",
            "action": "push branch, open PR, wait for required checks; human if secrets/approval needed.",
            "skill": "gh / GitHub",
            "artifact": "PR + CI",
        }
    )
    if epic is not None:
        stages.append(
            {
                "stage": f"epic-{epic}-note",
                "action": f"Keep this Epic {epic} running serial (recommended_implementation_order in sprint-status) unless you split file ownership.",
                "skill": "n/a",
                "artifact": f"epic-{epic}",
            }
        )
    return stages


def _next_suggested_line(status: str | None) -> str:
    s = (status or "").lower()
    if s == "ready-for-dev":
        return "Suggested next: stage 01–02 (optional story hardening) or start 03 (bmad-dev-story)."
    if s == "in-progress":
        return "Suggested next: finish 03 (bmad-dev-story), then 04 (code review)."
    if s == "review":
        return "Suggested next: stage 04 (bmad-code-review), then 05 (verify tests), then commit/PR if not already merged."
    if s == "done":
        return "This story is marked done in sprint pointer — run `status` to pick the next backlog story or create-story."
    return "Check sprint pointer and development_status in sprint-status.yaml."


def print_go(root: Path, data: dict[str, Any], epic: int | None) -> None:
    key = data.get("current_story_key")
    path = _parse_sprint_path(root, str(data.get("current_story_file") or "")) if data.get("current_story_file") else ""
    fr = first_ready_story(data["development_status"])
    print("=== BMAD pipeline — go plan (orchestrates artifacts; you still invoke Cursor/LLM per stage) ===")
    print()
    print(">>> This command does NOT modify git, the story file, or sprint-status.yaml. It only prints a checklist.")
    print()
    print(f"Focus story: {key}  (status: {data.get('current_story_status')})")
    print(_next_suggested_line(data.get("current_story_status")))
    print()
    if fr and fr != key:
        print(f"Note: first ready-for-dev in map is {fr} — align current_story_key if intentional.")
    print(f"Story file:  {path if path and Path(path).exists() else (path or '(resolve path)')}")
    print()
    for s in go_plan(root, data, epic):
        print(f"**{s['stage']}**  [{s.get('skill', '')}]")
        print(f"  {s['action']}")
        print(f"  → {s.get('artifact', '')}")
        print()


def run_shell(cmd: list[str], cwd: Path) -> int:
    print(f"[run] {' '.join(cmd)}", file=sys.stderr)
    return subprocess.call(cmd, cwd=cwd)


def main() -> int:
    root = _repo_root()
    default_sprint = root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
    ap = argparse.ArgumentParser(
        description="BMAD local pipeline helper (sprint-status + go plan; optional test/hint steps)."
    )
    ap.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=("status", "go"),
        help="status: print sprint; go: print handoff plan",
    )
    ap.add_argument("--sprint", type=Path, default=default_sprint, help="Path to sprint-status.yaml")
    ap.add_argument("--epic", type=int, default=None, help="Limit status display / epic note in go plan (e.g. 9).")
    ap.add_argument("--json", action="store_true", help="Emit status as JSON (command status only).")
    ap.add_argument("--hints", action="store_true", help="With go: run scripts/git/story-commit-hints.sh --staged")
    ap.add_argument(
        "--tests",
        action="store_true",
        help="With go: run backend pytest (full dirijor-core tests)",
    )
    args = ap.parse_args()

    if not args.sprint.is_file():
        print(f"Missing sprint file: {args.sprint}", file=sys.stderr)
        print("Create or sync sprint-status, or pass --sprint", file=sys.stderr)
        return 1

    data = load_sprint_file(args.sprint)
    if data["current_story_key"] is None and data["development_status"]:
        pass
    if args.json and args.command == "status":
        out: dict[str, Any]
        if args.epic is not None:
            out = {
                "epic": args.epic,
                "stories": filter_epic(data["development_status"], args.epic),
            }
        else:
            out = {k: v for k, v in data.items() if not str(k).startswith("_")}
        print(json.dumps(out, indent=2))
        return 0

    if args.json and args.command == "go":
        print(
            json.dumps(
                {
                    "disclaimer": "This script does not modify git, story files, or sprint-status; it only emits a plan.",
                    "next_suggested": _next_suggested_line(data.get("current_story_status")),
                    "current_story_key": data.get("current_story_key"),
                    "current_story_status": data.get("current_story_status"),
                    "first_ready_for_dev": first_ready_story(data["development_status"]),
                    "stages": go_plan(root, data, args.epic),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "status":
        print_status(root, data, args.epic)
        return 0

    if args.command == "go":
        print_go(root, data, args.epic)
        rc = 0
        if args.hints:
            hint = root / "scripts" / "git" / "story-commit-hints.sh"
            if hint.is_file() and os_access_x(hint):
                r = run_shell([str(hint), "--staged"], root)
                rc = r if r != 0 else rc
            else:
                print("Skip --hints: story-commit-hints.sh missing or not executable", file=sys.stderr)
        if args.tests:
            r = run_shell(
                [sys.executable, "-m", "pytest", "backend/dirijor-core/tests"],
                root,
            )
            rc = r if r != 0 else rc
        return rc
    return 0


def os_access_x(path: Path) -> bool:
    import os

    return os.path.isfile(path) and os.access(path, os.X_OK)


if __name__ == "__main__":
    raise SystemExit(main())
