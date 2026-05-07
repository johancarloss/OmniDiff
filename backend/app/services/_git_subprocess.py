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

from app.schemas.ingest import ChangeTypeCode, CommitMeta, FileDiff, WalkResult

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


def _parse_record(record: str) -> tuple[CommitMeta | None, bool]:
    """Parse a single `git log -z` record.

    Returns ``(meta, is_merge)``:
      - ``meta`` is None when the record is malformed OR is a merge.
      - ``is_merge`` distinguishes "skipped because merge" from
        "skipped because malformed" so the walker can count merges
        accurately.
    """
    fields = record.split(FIELD_SEP)
    if len(fields) != 6:
        # Malformed record — skip rather than crash.
        return (None, False)

    sha, name, email, date_iso, parents_str, body = fields
    parents = parents_str.split() if parents_str else []

    # Skip merge commits (>1 parent) — Phase 2-A doesn't index them.
    if len(parents) > 1:
        return (None, True)

    try:
        committed_at = datetime.fromisoformat(date_iso)
    except ValueError:
        return (None, False)

    meta = CommitMeta(
        hash=sha,
        author_name=name or None,
        author_email=email or None,
        message=body.strip("\n"),
        committed_at=committed_at,
        parents=parents,
        # Stats are filled in later by get_commit_stats — kept zero here.
    )
    return (meta, False)


def walk_commits(
    repo_path: Path,
    *,
    since: str | None = None,
    branch: str | None = None,
) -> WalkResult:
    """Run `git log` in the given repo and return all (non-merge) commits.

    Args:
        repo_path: filesystem path to a cloned repo (must contain `.git/`).
        since: optional commit hash. When provided, the walker uses
            `git log <since>..<target>` and returns only commits reachable
            from `<target>` but not from `since`. Used by the incremental
            indexing path. If `since` is an unknown/orphaned hash (e.g.
            after a force-push reshaping history), git fails with
            exit 128 and `GitSubprocessError` propagates — the caller
            can fall back to a full walk.
        branch: optional branch / ref name to walk (e.g. `"main"`,
            `"origin/dev"`, or a tag). When None, the walker uses
            whatever HEAD points to in the working tree. An unknown
            branch name produces `GitSubprocessError`.

    Returns a WalkResult with:
        - metas: commits in CHRONOLOGICAL order (oldest first), excluding
          merge commits — that's what Phase 3 wants for incremental
          embedding.
        - skipped_merges: count of merge commits filtered out, surfaced
          via IndexResult so callers can report it.

    Raises `GitSubprocessError` on any git failure (missing repo, no
    permissions, unknown `since` hash, unknown branch, malformed output,
    etc).
    """
    if not repo_path.exists():
        raise GitSubprocessError(f"path does not exist: {repo_path}")

    # Target ref for the walk. Defaults to HEAD (matches `git log` default).
    target = branch if branch is not None else "HEAD"

    args = ["log", "-z", "--reverse", f"--format={GIT_LOG_FORMAT}"]
    if since is not None:
        # `<since>..<target>` syntax: commits reachable from `<target>` but
        # not from `<since>`. Fails with exit 128 if either revision is
        # unknown.
        args.append(f"{since}..{target}")
    elif branch is not None:
        # No `since`, but explicit branch: `git log <branch>` ignores HEAD
        # and walks from the given ref.
        args.append(branch)
    # else: bare `git log` uses HEAD — current working-tree behavior.

    stdout = _run_git(repo_path, args)

    # `git log -z` separates records with `\x00`. There is a trailing
    # null after the last record, producing one empty string after split.
    records = [r for r in stdout.split("\x00") if r]

    metas: list[CommitMeta] = []
    skipped_merges = 0
    for record in records:
        meta, is_merge = _parse_record(record)
        if is_merge:
            skipped_merges += 1
        elif meta is not None:
            metas.append(meta)
    return WalkResult(metas=metas, skipped_merges=skipped_merges)


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


# Diff content above this size triggers a `truncated=True` FileDiff. The
# chunker turns those into stub chunks (no embedding). 10 MiB matches
# `MAX_DIFF_BYTES` in `ingest_chunker.py` — kept duplicated here on
# purpose so each module can be tested independently.
MAX_DIFF_BYTES_PER_FILE = 10 * 1024 * 1024

# Marker emitted by `git show -U3` for binary files in place of content.
# Stable across git versions since 2010+.
BINARY_MARKER = "Binary files "

# Maps the one-letter status from `git show --raw` to the schema enum.
# `git diff` may also emit M/A/D/R/C/T/U; we treat C (copy) as A and
# T (type change) / U (unmerged) as M for now — they're rare in
# real-world history and Slice 2 doesn't need finer granularity.
_STATUS_MAP: dict[str, ChangeTypeCode] = {
    "A": "A",
    "M": "M",
    "D": "D",
    "R": "R",
    "C": "A",
    "T": "M",
    "U": "M",
}


def _parse_raw_status(stdout: str) -> list[tuple[ChangeTypeCode, str, str | None]]:
    """Parse `git show --raw` output.

    Returns list of (change_type, path, old_path). For non-renames,
    old_path is None.

    Sample line (tab-separated after the metadata prefix):
        :100644 100644 hashA hashB M\tbackend/app/main.py
        :100644 100644 hashC hashD R087\told/path.py\tnew/path.py
    """
    out: list[tuple[ChangeTypeCode, str, str | None]] = []
    for line in stdout.splitlines():
        if not line.startswith(":"):
            continue
        # Split on tab — paths come after the metadata block.
        parts = line.split("\t")
        if len(parts) < 2:
            continue

        # Metadata block ends with the status code (M, A, R087, etc).
        meta_fields = parts[0].split()
        if not meta_fields:
            continue
        status_token = meta_fields[-1]
        # Renames/copies look like "R087" (similarity score). First letter
        # is the status; we ignore the score for now.
        status_letter = status_token[0].upper()
        change = _STATUS_MAP.get(status_letter)
        if change is None:
            continue

        if change == "R" and len(parts) >= 3:
            out.append((change, parts[2], parts[1]))  # (R, new_path, old_path)
        else:
            out.append((change, parts[1], None))
    return out


def _split_show_output_by_file(stdout: str) -> dict[str, str]:
    """Split `git show -U3` output into per-file diff blocks.

    Keys are the `b/` (target) path from each `diff --git` header; values
    are the diff content for that file (header included so chunker has
    context).

    For binary files, the content includes the `Binary files ... differ`
    marker — caller checks for that to set `is_binary`.
    """
    blocks: dict[str, str] = {}
    current_path: str | None = None
    current_lines: list[str] = []

    for line in stdout.splitlines(keepends=True):
        if line.startswith("diff --git "):
            # Flush previous block.
            if current_path is not None:
                blocks[current_path] = "".join(current_lines)
            current_lines = [line]
            # Header format: `diff --git a/<path> b/<path>` (paths quoted
            # if they contain special chars). Take the b/ path as key.
            header = line.rstrip("\n")
            try:
                b_part = header.rsplit(" b/", 1)[1]
                current_path = b_part.strip().strip('"')
            except IndexError:
                current_path = None
        else:
            if current_path is not None:
                current_lines.append(line)

    if current_path is not None:
        blocks[current_path] = "".join(current_lines)

    return blocks


def extract_file_diffs(repo_path: Path, commit_hash: str) -> list[FileDiff]:
    """Extract per-file diffs for a single commit.

    Two-pass strategy:
      1. `git show --raw` is authoritative for file metadata
         (change_type, old_path on rename). Reliable parser, stable format.
      2. `git show -U3 --no-color` produces the diff content. Match each
         entry in the raw list to the corresponding diff block.

    Files marked binary by git get `is_binary=True` and empty content.
    Files where diff_content > MAX_DIFF_BYTES_PER_FILE get
    `truncated=True` — the chunker emits a stub chunk for those.

    Root commits (no parent) are handled by `git show --root --raw` /
    `git show --root -U3`, which forces a diff against the empty tree.
    """
    # --root makes both calls work for the very first commit too.
    raw_args = ["show", "--root", "--raw", "--no-color", "--format=", commit_hash]
    show_args = ["show", "--root", "-U3", "--no-color", "--format=", commit_hash]

    raw_stdout = _run_git(repo_path, raw_args)
    show_stdout = _run_git(repo_path, show_args)

    raw_entries = _parse_raw_status(raw_stdout)
    diff_blocks = _split_show_output_by_file(show_stdout)

    file_diffs: list[FileDiff] = []
    for change_type, path, old_path in raw_entries:
        diff_content = diff_blocks.get(path, "")

        # Truncate ahead of the binary check so we don't pay UTF-8 work
        # on a 50MB blob just to decide it's binary.
        truncated = len(diff_content.encode("utf-8")) > MAX_DIFF_BYTES_PER_FILE
        if truncated:
            diff_content = ""

        is_binary = BINARY_MARKER in diff_content
        if is_binary:
            diff_content = ""

        file_diffs.append(
            FileDiff(
                file_path=path,
                old_path=old_path,
                change_type=change_type,
                diff_content=diff_content,
                is_binary=is_binary,
                truncated=truncated,
            )
        )

    return file_diffs
