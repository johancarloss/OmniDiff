"""Pure-Python wrappers around `git` subprocess calls.

This module deliberately has zero dependencies on database, async, or
FastAPI — it is unit-testable by giving it a real Git repo via tempfile.

We use `subprocess + git log -z` rather than GitPython or pygit2 because:
  1. The Phase 2-C Rust port (via git2-rs) needs a baseline that does NOT
     already use libgit2; otherwise the speedup is masked.
  2. Any machine with `git` installed can run this — no Python C extension
     dependency.
  3. The decision is documented in PHASE-2A § 3.1.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from app.schemas.ingest import CommitMeta

# Field separator: ASCII Unit Separator (0x1F). Virtually never appears
# in commit metadata, so it's safe to use as a delimiter inside one
# `--format` block — unlike pipes or commas, which DO appear naturally.
FIELD_SEP = "\x1f"

# Per-record format. Order: hash, author name, email, ISO date, parents
# (space-sep), subject + body. The `\x00` between records comes from
# `git log -z` (NOT from the format string itself).
GIT_LOG_FORMAT = "%H%x1f%an%x1f%ae%x1f%aI%x1f%P%x1f%B"

# Regex for `git show --shortstat`. Examples it must match:
#   " 3 files changed, 27 insertions(+), 5 deletions(-)"
#   " 1 file changed, 1 insertion(+)"
#   " 2 files changed, 4 deletions(-)"
SHORTSTAT_RE = re.compile(
    r"\s*(?P<files>\d+)\s+files?\s+changed"
    r"(?:,\s+(?P<ins>\d+)\s+insertions?\(\+\))?"
    r"(?:,\s+(?P<dels>\d+)\s+deletions?\(-\))?"
)

# Hard cap on how long a single git invocation may run (seconds).
# Repos with hundreds of thousands of commits can take a few minutes
# on `git log`; this is a guard rail, not a tight bound.
SUBPROCESS_TIMEOUT = 300


class GitSubprocessError(Exception):
    """Raised when a git command fails or returns unparseable output."""


def _run_git(repo_path: Path, args: list[str]) -> str:
    """Run `git -C <repo_path> <args>` and return decoded stdout.

    Decodes with `errors="replace"` so non-UTF8 commit messages don't
    crash the parser (rare but real, especially in older Linux repos).
    """
    cmd = ["git", "-C", str(repo_path), *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        raise GitSubprocessError(
            f"git {' '.join(args)} failed (exit {exc.returncode}): {stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitSubprocessError(
            f"git {' '.join(args)} timed out after {SUBPROCESS_TIMEOUT}s"
        ) from exc
    except FileNotFoundError as exc:
        raise GitSubprocessError(
            "`git` executable not found — install git in this environment"
        ) from exc

    return result.stdout.decode("utf-8", errors="replace")


def _parse_record(record: str) -> CommitMeta | None:
    """Parse a single `git log -z` record into a CommitMeta.

    Returns None for merge commits (parents.split() returns >1 hash) so
    callers can filter them out cleanly.
    """
    fields = record.split(FIELD_SEP)
    if len(fields) != 6:
        # Malformed record — skip rather than crash.
        return None

    sha, name, email, date_iso, parents_str, body = fields
    parents = parents_str.split() if parents_str else []

    # Skip merge commits (>1 parent) — Phase 2-A doesn't index them.
    if len(parents) > 1:
        return None

    try:
        committed_at = datetime.fromisoformat(date_iso)
    except ValueError:
        return None

    return CommitMeta(
        hash=sha,
        author_name=name or None,
        author_email=email or None,
        message=body.strip("\n"),
        committed_at=committed_at,
        parents=parents,
        # Stats are filled in later by get_commit_stats — kept zero here.
    )


def walk_commits(repo_path: Path) -> list[CommitMeta]:
    """Run `git log` in the given repo and return all (non-merge) commits.

    Commits are returned in CHRONOLOGICAL order (oldest first), which
    matches what Phase 3 wants for incremental embedding.

    Raises `GitSubprocessError` on any git failure (missing repo, no
    permissions, malformed output, etc).
    """
    if not repo_path.exists():
        raise GitSubprocessError(f"path does not exist: {repo_path}")

    stdout = _run_git(
        repo_path,
        ["log", "-z", "--reverse", f"--format={GIT_LOG_FORMAT}"],
    )

    # `git log -z` separates records with `\x00`. There is a trailing
    # null after the last record, producing one empty string after split.
    records = [r for r in stdout.split("\x00") if r]

    metas: list[CommitMeta] = []
    for record in records:
        meta = _parse_record(record)
        if meta is not None:
            metas.append(meta)
    return metas


def get_commit_stats(repo_path: Path, commit_hash: str) -> tuple[int, int, int]:
    """Return `(files_changed, insertions, deletions)` for a commit.

    Returns (0, 0, 0) gracefully for root commits or any unexpected
    output — this is a "nice to have" enrichment, not a correctness
    requirement, so we degrade rather than fail.
    """
    try:
        stdout = _run_git(
            repo_path,
            ["show", "--shortstat", "--format=", commit_hash],
        )
    except GitSubprocessError:
        return (0, 0, 0)

    for line in stdout.splitlines():
        match = SHORTSTAT_RE.match(line)
        if match is None:
            continue
        files = int(match.group("files") or 0)
        ins = int(match.group("ins") or 0)
        dels = int(match.group("dels") or 0)
        return (files, ins, dels)
    return (0, 0, 0)
