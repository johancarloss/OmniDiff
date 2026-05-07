"""Resolve a repository source (URL or local path) into a usable local clone.

This helper is shared between the CLI (`python -m cli index ...`) and the
HTTP endpoint (`POST /api/index`) — both need to take an arbitrary
"repo source" string and produce a local checkout that `IngestService`
can walk.

Behavior:
    - If the argument is an existing local directory, use it as-is.
    - If the argument is a URL with a known scheme (https, http, ssh,
      git, git@, file), clone into `repos_dir/<derived_name>` on first
      run, fetch + hard-reset on subsequent runs.
    - Otherwise raise `InvalidRepoSourceError`.

Cloning strategy: `git clone` for the first run, `git fetch --prune` +
`git reset --hard origin/HEAD` for subsequent runs. The reset on
`origin/HEAD` (the remote's default branch symbolic ref) means we don't
need to know whether upstream uses `main` or `master`, and it handles
force-push transparently.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# Matches the trailing `<owner>/<repo>(.git)?` segment of common Git
# hosting URLs (GitHub, GitLab, Bitbucket, self-hosted via ssh).
_URL_NAME_RE = re.compile(r"[:/]([^/:]+)/([^/:]+?)(?:\.git)?/?$")

_URL_PREFIXES = (
    "https://",
    "http://",
    "ssh://",
    "git://",
    "git@",
    "file://",  # used by tests and by local bare-repo indexing by URL
)


class InvalidRepoSourceError(Exception):
    """Raised when the input is neither a known-scheme URL nor an existing path.

    Both the CLI and the HTTP endpoint translate this into a user-facing
    error: CLI exits with a usage code, the API returns 422.
    """


def looks_like_url(arg: str) -> bool:
    """Return True if `arg` matches a recognized URL scheme."""
    return arg.startswith(_URL_PREFIXES)


def derive_repo_name(url: str) -> str:
    """Extract a stable directory name from a repo URL.

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
    logger.info("refreshing existing clone at %s", target)
    _git("fetch", "--quiet", "--prune", "origin", cwd=target)
    _git("reset", "--quiet", "--hard", "origin/HEAD", cwd=target)


def ensure_local_clone(arg: str, repos_dir: Path) -> tuple[Path, str, str]:
    """Resolve a repo source argument to a local clone.

    Returns:
        (local_path, canonical_url, repo_name)

    Raises:
        InvalidRepoSourceError: argument is neither a URL nor an existing dir.
        subprocess.CalledProcessError: git clone/fetch failed.
        subprocess.TimeoutExpired: git clone/fetch took longer than 10 min.
    """
    candidate_path = Path(arg).resolve()
    if candidate_path.exists() and candidate_path.is_dir():
        url = f"file://{candidate_path}"
        name = candidate_path.name
        return (candidate_path, url, name)

    if not looks_like_url(arg):
        raise InvalidRepoSourceError(
            f"argument is neither a URL with a known scheme nor an existing directory: {arg!r}"
        )

    name = derive_repo_name(arg)
    local_path = (repos_dir / name).resolve()

    if local_path.exists():
        _refresh_existing(local_path)
    else:
        _clone_fresh(arg, local_path)

    return (local_path, arg, name)
