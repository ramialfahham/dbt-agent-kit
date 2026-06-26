#!/usr/bin/env python
"""PreToolUse(Bash) — block a commit until the change has been reviewed.

Plugin version of the blinded review gate. When you run `git commit`, this:
  1. hashes the staged diff,
  2. works out which reviewers are required for the staged files
     (.claude/review_routing.json in the project, else the plugin default),
  3. reads .claude/task/review.md and BLOCKS the commit unless:
       - the recorded diff_sha256 matches the staged diff (so the review covers
         exactly what you are committing),
       - every required reviewer has a verdict and none is FAIL,
       - every ESCALATE has a recorded "CPO ANSWER:".
Commits that touch only bookkeeping files (.claude/task/**, active_work.md) are
exempt. Fails OPEN on any error — a gate bug must never block your workflow.

Wired in hooks.json as:
  python "${CLAUDE_PLUGIN_ROOT}/hooks/commit_review_gate.py" "${CLAUDE_PLUGIN_ROOT}"
Run with a trailing --staged-hash to print the staged-diff hash for review.md.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _command_utils import (  # noqa: E402
    bash_command,
    emit_deny,
    read_event,
    simple_commands,
)

ROUTING_REL = os.path.join(".claude", "review_routing.json")
REVIEW_REL = os.path.join(".claude", "task", "review.md")


def _repo_root() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _plugin_root() -> str:
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            return arg
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _staged_diff(root: str) -> bytes:
    # --no-renames + --no-abbrev pin the bytes so the local hash and a CI
    # recompute over `git diff base...HEAD` match for identical content.
    return subprocess.run(
        ["git", "diff", "--staged", "--no-renames", "--no-abbrev"],
        cwd=root, capture_output=True, timeout=30,
    ).stdout


def _staged_paths(root: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--staged", "--name-only", "-z"],
        cwd=root, capture_output=True, text=True, timeout=30,
    ).stdout
    return [p.replace("\\", "/") for p in out.split("\0") if p]


def _load_routing(root: str, plugin_root: str) -> dict | None:
    for path in (os.path.join(root, ROUTING_REL),
                 os.path.join(plugin_root, "review_routing.json")):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None


def _required_reviewers(paths: list[str], routing: dict) -> set[str]:
    required = set(routing.get("always") or [])
    for path in paths:
        for pattern, reviewers in (routing.get("paths") or {}).items():
            if fnmatch.fnmatch(path, pattern):
                required.update(reviewers)
    return required


def _artifact_only(paths: list[str], routing: dict) -> bool:
    never = routing.get("artifact_only_never") or []
    if any(fnmatch.fnmatch(p, pat) for p in paths for pat in never):
        return False
    pats = routing.get("artifact_only") or []
    return bool(paths) and all(
        any(fnmatch.fnmatch(p, pat) for pat in pats) for p in paths
    )


def _sections(text: str) -> dict[str, str]:
    """Map '## name' -> body. Text before the first header is '_preamble'."""
    sections, name, buf = {}, "_preamble", []
    for line in text.splitlines():
        m = re.match(r"^##\s+(\S+)", line)
        if m:
            sections[name] = "\n".join(buf)
            name, buf = m.group(1), []
        else:
            buf.append(line)
    sections[name] = "\n".join(buf)
    return sections


def _is_commit(cmd: str) -> bool:
    for part in simple_commands(cmd):
        toks = part.split()
        if (len(toks) >= 2 and toks[0] == "git"
                and "commit" in toks[1:] and "--dry-run" not in toks):
            return True
    return False


def _gate(root: str, plugin_root: str) -> str | None:
    paths = _staged_paths(root)
    if not paths:
        return None  # nothing staged: let git complain
    routing = _load_routing(root, plugin_root)
    if routing is None:
        return None  # no routing anywhere: gate inactive (fail open)
    if _artifact_only(paths, routing):
        return None  # bookkeeping-only commit: exempt
    review_path = os.path.join(root, REVIEW_REL)
    if not os.path.isfile(review_path):
        return ("REVIEW GATE: no review found. Stage the change, run the required "
                "reviewers, and write .claude/task/review.md (see the plugin's "
                "task/REVIEW_TEMPLATE.md), then commit.")
    text = open(review_path, encoding="utf-8", errors="replace").read()
    live = hashlib.sha256(_staged_diff(root)).hexdigest()
    m = re.search(r"diff_sha256:\s*([0-9a-fA-F]{64})", text)
    if not m or m.group(1).lower() != live:
        return ("REVIEW GATE: the staged change does not match the reviewed one "
                "(hash mismatch) — re-run the reviewers against the current "
                f"staged diff and update review.md. Current staged hash: {live}")
    if "VERDICT: FAIL" in text:
        return "REVIEW GATE: a reviewer verdict is FAIL. Fix the findings and re-review."
    if text.count("VERDICT: ESCALATE") > text.count("CPO ANSWER:"):
        return ("REVIEW GATE: an ESCALATE has no recorded 'CPO ANSWER:'. Get the "
                "owner's decision, write it under the question, then commit.")
    sections = _sections(text)
    for reviewer in sorted(_required_reviewers(paths, routing)):
        if "VERDICT:" not in sections.get(reviewer, ""):
            return (f"REVIEW GATE: required reviewer '{reviewer}' has no verdict for "
                    "the staged files (see review_routing.json). Run it and record "
                    "its section in review.md.")
    return None


def main() -> int:
    plugin_root = _plugin_root()
    if "--staged-hash" in sys.argv:
        print(hashlib.sha256(_staged_diff(_repo_root())).hexdigest())
        return 0
    cmd = bash_command(read_event())
    if not cmd or not _is_commit(cmd):
        return 0
    try:
        reason = _gate(_repo_root(), plugin_root)
    except Exception:
        return 0  # fail open
    if reason:
        emit_deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
