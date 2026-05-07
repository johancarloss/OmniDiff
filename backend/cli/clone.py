"""Helper module: detect whether a CLI argument is a URL or a local path
and ensure a usable local clone exists.

Behavior:
    - If `arg` is a URL (https://, ssh://, git@, git://): clone into
      `repos_dir/<derived_name>` if missing, otherwise fetch + reset.
    - If `arg` is an existing local path: use it as-is.
    - Otherwise: raise CLIError.

The cloning strategy uses `git clone` for first run and `git fetch` +
`git reset --hard origin/HEAD` for subsequent runs. This handles
force-push on the remote without needing special detection.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# Regex for "name part" of a URL — matches GitHub / GitLab / Bitbucket-style
# `<owner>/<repo>(.git)?` paths. Falls back to raw basename otherwise.
_URL_NAME_RE = re.compile(r"[:/]([^/:]+)/([^/:]+?)(?:\.git)?/?$")

_URL_PREFIXES = (
    "https://",
    "http://",
    "ssh://",
    "git://",
    "git@",
    "file://",  # used by tests and by users who want to index a local
    # bare repo by URL rather than by path
)


class CLIError(Exception):
    """Raised when the CLI argument is invalid (not a URL, not a path)."""


def looks_like_url(arg: str) -> bool:
    """Return True if `arg` matches a recognized URL scheme."""
    return arg.startswith(_URL_PREFIXES)


def derive_repo_name(url: str) -> str:
    """Extract a stable directory name from a URL.

    Examples:
        https://github.com/johancarloss/OmniDiff       → johancarloss__OmniDiff
        https://github.com/johancarloss/OmniDiff.git   → johancarloss__OmniDiff
        git@github.com:johancarloss/OmniDiff.git       → johancarloss__OmniDiff
        ssh://git@example.com/team/repo.git            → team__repo

    Falls back to the trailing path segment if the regex fails (rare).
    """
    match = _URL_NAME_RE.search(url)
    if match is not None:
        owner, name = match.group(1), match.group(2)
        return f"{owner}__{name}"
    # Fallback: last path segment, stripped of .git.
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")


def _git(*args: str, cwd: Path | None = None) -> None:
    """Run a git command with a sane timeout. Raises CalledProcessError
    on non-zero exit so callers can decide whether to translate."""
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        timeout=600,  # 10 min — clone of large repos can be slow
    )


def _clone_fresh(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    logger.info("cloning %s into %s", url, target)
    _git("clone", "--quiet", url, str(target))


def _refresh_existing(target: Path) -> None:
    """Fetch + hard reset to origin's default branch.

    `reset --hard` on `origin/HEAD` (the symbolic ref of the remote's
    default branch) means we don't need to know whether the project
    uses `main` or `master` — we follow whatever the remote declares.
    """
    logger.info("refreshing existing clone at %s", target)
    _git("fetch", "--quiet", "--prune", "origin", cwd=target)
    _git("reset", "--quiet", "--hard", "origin/HEAD", cwd=target)


def ensure_local_clone(arg: str, repos_dir: Path) -> tuple[Path, str, str]:
    """Resolve a CLI argument to a local clone.

    Returns:
        (local_path, canonical_url, repo_name)

    Raises:
        CLIError: if `arg` is neither a known-scheme URL nor an existing path.
        subprocess.CalledProcessError: if git clone/fetch fails.
    """
    # Local path takes precedence: if the user passed `.` or an existing
    # directory, use it directly without trying to interpret as URL.
    candidate_path = Path(arg).resolve()
    if candidate_path.exists() and candidate_path.is_dir():
        url = f"file://{candidate_path}"
        name = candidate_path.name
        return (candidate_path, url, name)

    if not looks_like_url(arg):
        raise CLIError(
            f"argument is neither a URL with a known scheme nor an existing directory: {arg!r}"
        )

    name = derive_repo_name(arg)
    local_path = (repos_dir / name).resolve()

    if local_path.exists():
        _refresh_existing(local_path)
    else:
        _clone_fresh(arg, local_path)

    return (local_path, arg, name)
