"""Entrypoint for `python -m omnidiff`.

Wires argparse to the command implementations.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from cli.index_command import EXIT_USAGE, run_index


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m omnidiff",
        description="OmniDiff CLI — semantic search for Git commits",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="logging verbosity (default: INFO)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    idx = sub.add_parser("index", help="Index a Git repository")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "index":
        return asyncio.run(run_index(args.repo, args.repos_dir))

    # argparse with required=True on subparsers makes this unreachable,
    # but keep a defensive fallback to avoid silent zero-exit on bugs.
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
