"""Argument parsing contract for the CLI.

Pure parser tests: no Postgres, no git, no indexing.
"""

from __future__ import annotations

import pytest

from cli.__main__ import _build_parser
from cli.index_command import EXIT_USAGE


def test_prog_name_is_an_invocation_that_exists() -> None:
    """`python -m omnidiff` is not importable; the console script is."""
    assert _build_parser().prog == "omnidiff"


def test_log_level_accepted_before_subcommand() -> None:
    args = _build_parser().parse_args(["--log-level", "DEBUG", "index", "repo"])
    assert args.log_level == "DEBUG"


def test_log_level_accepted_after_subcommand() -> None:
    args = _build_parser().parse_args(["index", "repo", "--log-level", "DEBUG"])
    assert args.log_level == "DEBUG"


def test_log_level_defaults_to_info() -> None:
    args = _build_parser().parse_args(["index", "repo"])
    assert args.log_level == "INFO"


def test_innermost_log_level_wins_when_given_twice() -> None:
    args = _build_parser().parse_args(
        ["--log-level", "WARNING", "index", "repo", "--log-level", "DEBUG"]
    )
    assert args.log_level == "DEBUG"


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["index"], id="missing-required-repo"),
        pytest.param(["index", "repo", "--nope"], id="unknown-flag"),
        pytest.param(["bogus-command"], id="unknown-subcommand"),
        pytest.param([], id="no-subcommand"),
    ],
)
def test_usage_errors_exit_with_the_documented_code(argv: list[str]) -> None:
    """argparse defaults to exit 2, which the CLI contract assigns to EXIT_GIT."""
    with pytest.raises(SystemExit) as exc:
        _build_parser().parse_args(argv)
    assert exc.value.code == EXIT_USAGE
