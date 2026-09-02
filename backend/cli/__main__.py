"""Entrypoint for the `omnidiff` console script.

Wires argparse to the command implementations.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import NoReturn

from cli.index_command import EXIT_USAGE, run_index


class _Parser(argparse.ArgumentParser):
    """Argparse exits 2 on a usage error, which this CLI reserves for
    git failures (EXIT_GIT). Remap it onto the documented contract."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _log_level_flag(default: str) -> _Parser:
    """A fresh carrier for `--log-level`, so it works on either side of
    the subcommand.

    Returns a new parser per call on purpose: `parents=` shares Action
    objects by reference, and the subcommand's copy must keep its own
    default. The subcommand passes SUPPRESS so that omitting the flag
    leaves untouched whatever was given before the subcommand.
    """
    carrier = _Parser(add_help=False)
    carrier.add_argument(
        "--log-level",
        default=default,
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="logging verbosity (default: INFO)",
    )
    return carrier


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="omnidiff",
        description="OmniDiff CLI — semantic search for Git commits",
        parents=[_log_level_flag("INFO")],
    )

    sub = parser.add_subparsers(dest="command", required=True)

    idx = sub.add_parser(
        "index",
        help="Index a Git repository",
        parents=[_log_level_flag(argparse.SUPPRESS)],
    )
    idx.add_argument(
        "repo",
        help=(
            "URL of the repository (https://, ssh://, git@, file://) "
            "OR path to an existing local clone"
        ),
    )
    idx.add_argument(
        "--repos-dir",
        type=Path,
        default=Path("repos"),
        help="where to clone remote repos (default: ./repos)",
    )
    idx.add_argument(
        "--branch",
        default=None,
        help=(
            "branch or ref to index (e.g. main, origin/dev, v1.0.0). "
            "Defaults to whatever HEAD points to in the working tree."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "index":
        return asyncio.run(run_index(args.repo, args.repos_dir, branch=args.branch))

    # argparse with required=True on subparsers makes this unreachable,
    # but keep a defensive fallback to avoid silent zero-exit on bugs.
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
