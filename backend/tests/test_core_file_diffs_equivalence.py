"""Rust `extract_file_diffs` must agree with the `git show` path.

Metadata must match exactly. Patch text is compared by the lines that
actually changed: git and libgit2 frame hunks slightly differently (git
has applied an indent heuristic by default since 2.14 and the two
implementations still disagree on some boundaries), while the `+`/`-`
lines themselves are identical. Framing is cosmetic; changed lines are
not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services._git_subprocess import extract_file_diffs

core = pytest.importorskip(
    "omnidiff_core",
    reason="Rust extension not built — run `maturin develop` from core/",
)

_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@e.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@e.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=_ENV
    ).stdout


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _changed_lines(patch: str) -> list[str]:
    """The `+`/`-` lines, without the `---`/`+++` file headers."""
    return [
        line
        for line in patch.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """One commit per kind of change the extractor has to describe."""
    path = tmp_path / "corpus"
    path.mkdir()
    _git(path, "init", "-q", "--initial-branch=main")
    _git(path, "config", "--local", "commit.gpgsign", "false")

    body = "".join(f"line {i}\n" for i in range(40))

    (path / "a.py").write_text(body)
    _commit(path, "root")

    (path / "a.py").write_text(body.replace("line 12\n", "line 12 edited\n"))
    _commit(path, "modify")

    (path / "b.py").write_text("print('b')\n")
    _commit(path, "add")

    (path / "b.py").unlink()
    _commit(path, "delete")

    (path / "a.py").rename(path / "c.py")
    _commit(path, "pure rename")

    (path / "c.py").rename(path / "d.py")
    (path / "d.py").write_text(body.replace("line 30\n", "line 30 edited\n"))
    _commit(path, "rename with edit")

    (path / "blob.bin").write_bytes(bytes(range(256)) * 16)
    _commit(path, "add binary")

    (path / "blob.bin").write_bytes(bytes(reversed(range(256))) * 16)
    _commit(path, "modify binary")

    (path / "e.py").write_text("x = 1\n")
    (path / "d.py").unlink()
    _commit(path, "add and delete together")

    return path


def _hashes(repo: Path) -> list[str]:
    return _git(repo, "rev-list", "--reverse", "HEAD").split()


@pytest.mark.parametrize(
    "field", ["file_path", "old_path", "change_type", "is_binary", "truncated"]
)
def test_metadata_matches_git(repo: Path, field: str) -> None:
    for commit_hash in _hashes(repo):
        subject = _git(repo, "show", "-s", "--format=%s", commit_hash).strip()
        py = extract_file_diffs(repo, commit_hash)
        rust = core.extract_file_diffs(str(repo), commit_hash)
        assert [getattr(f, field) for f in py] == [f[field] for f in rust], (
            f"{field} diverged on {subject!r}"
        )


def test_changed_lines_match_git(repo: Path) -> None:
    for commit_hash in _hashes(repo):
        subject = _git(repo, "show", "-s", "--format=%s", commit_hash).strip()
        py = extract_file_diffs(repo, commit_hash)
        rust = core.extract_file_diffs(str(repo), commit_hash)
        for expected, actual in zip(py, rust, strict=True):
            assert _changed_lines(expected.diff_content) == _changed_lines(
                actual["diff_content"]
            ), f"changed lines diverged on {expected.file_path} in {subject!r}"


def test_batch_matches_one_by_one(repo: Path) -> None:
    hashes = _hashes(repo)
    assert core.extract_file_diffs_batch(str(repo), hashes) == [
        core.extract_file_diffs(str(repo), h) for h in hashes
    ]


def test_rename_carries_the_old_path(repo: Path) -> None:
    rename_commit = next(
        h
        for h in _hashes(repo)
        if _git(repo, "show", "-s", "--format=%s", h).strip() == "pure rename"
    )
    (entry,) = core.extract_file_diffs(str(repo), rename_commit)
    assert entry["change_type"] == "R"
    assert entry["old_path"] == "a.py"
    assert entry["file_path"] == "c.py"


def test_changed_binary_reports_no_content(repo: Path) -> None:
    modify_commit = next(
        h
        for h in _hashes(repo)
        if _git(repo, "show", "-s", "--format=%s", h).strip() == "modify binary"
    )
    (entry,) = core.extract_file_diffs(str(repo), modify_commit)
    assert entry["is_binary"] is True
    assert entry["diff_content"] == ""


def test_pure_rename_of_a_binary_file_is_a_known_divergence(repo: Path) -> None:
    """git prints the rename header, libgit2 prints the binary marker.

    Codified rather than hidden: the two libraries render this case
    differently and neither is wrong. Files like this carry binary
    extensions, so `should_skip_file` drops them before the chunker —
    the divergence never reaches the pipeline. See
    `docs/private/benchmarks/rust-vs-python.md`.
    """
    (repo / "blob.bin").rename(repo / "renamed.bin")
    _commit(repo, "pure rename of binary")
    commit_hash = _git(repo, "rev-parse", "HEAD").strip()

    (py_entry,) = extract_file_diffs(repo, commit_hash)
    (rust_entry,) = core.extract_file_diffs(str(repo), commit_hash)

    assert py_entry.change_type == rust_entry["change_type"] == "R"
    assert py_entry.is_binary is False
    assert "rename to" in py_entry.diff_content
    assert rust_entry["is_binary"] is True
    assert rust_entry["diff_content"] == ""
