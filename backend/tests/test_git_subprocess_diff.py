"""Unit tests for `extract_file_diffs`.

These build small real Git repos via `subprocess` + `tempfile` so the
parser is validated against the real git output format (not mocks).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.services._git_subprocess import extract_file_diffs

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=_GIT_ENV,
    )


def _init_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "--local", "commit.gpgsign", "false")
    return repo


def _head_hash(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
        env=_GIT_ENV,
    ).stdout.strip()


def test_extract_simple_modification(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, "mod_repo")
    (repo / "foo.py").write_text("hello\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")

    (repo / "foo.py").write_text("hello\nworld\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "modify")

    fds = extract_file_diffs(repo, _head_hash(repo))
    assert len(fds) == 1
    assert fds[0].file_path == "foo.py"
    assert fds[0].change_type == "M"
    assert fds[0].is_binary is False
    assert fds[0].old_path is None
    assert "+world" in fds[0].diff_content


def test_extract_added_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, "add_repo")
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "seed")

    (repo / "new.py").write_text("brand new\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add new")

    fds = extract_file_diffs(repo, _head_hash(repo))
    assert len(fds) == 1
    assert fds[0].file_path == "new.py"
    assert fds[0].change_type == "A"


def test_extract_deleted_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, "del_repo")
    (repo / "doomed.txt").write_text("bye\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "create")

    (repo / "doomed.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "delete")

    fds = extract_file_diffs(repo, _head_hash(repo))
    assert len(fds) == 1
    assert fds[0].file_path == "doomed.txt"
    assert fds[0].change_type == "D"


def test_extract_renamed_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, "rename_repo")
    (repo / "old_name.py").write_text("content\n" * 20)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "create")

    _git(repo, "mv", "old_name.py", "new_name.py")
    _git(repo, "commit", "-q", "-m", "rename")

    fds = extract_file_diffs(repo, _head_hash(repo))
    assert len(fds) == 1
    assert fds[0].change_type == "R"
    assert fds[0].file_path == "new_name.py"
    assert fds[0].old_path == "old_name.py"


def test_extract_binary_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, "bin_repo")
    # Write actual binary content (PNG signature + random-ish payload).
    (repo / "tiny.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add binary")

    fds = extract_file_diffs(repo, _head_hash(repo))
    assert len(fds) == 1
    assert fds[0].file_path == "tiny.png"
    assert fds[0].is_binary is True
    assert fds[0].diff_content == ""


def test_extract_root_commit(tmp_path: Path) -> None:
    """Root commit (no parent): `git show --root` must still emit diffs
    against the empty tree without raising."""
    repo = _init_repo(tmp_path, "root_repo")
    (repo / "first.py").write_text("just born\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "root")

    fds = extract_file_diffs(repo, _head_hash(repo))
    assert len(fds) == 1
    assert fds[0].file_path == "first.py"
    assert fds[0].change_type == "A"


def test_extract_multiple_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, "multi_repo")
    for i in range(3):
        (repo / f"file_{i}.py").write_text(f"content {i}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "three files")

    fds = extract_file_diffs(repo, _head_hash(repo))
    assert len(fds) == 3
    paths = {fd.file_path for fd in fds}
    assert paths == {"file_0.py", "file_1.py", "file_2.py"}
    assert all(fd.change_type == "A" for fd in fds)
