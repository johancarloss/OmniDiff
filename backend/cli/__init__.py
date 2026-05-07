"""OmniDiff CLI.

Entrypoint: `python -m omnidiff <command> [args]`.

Commands:
    index <url-or-path>   Index a Git repository.

The CLI is intentionally a thin adapter over `app.services.IngestService`.
All business logic lives in the service layer; the CLI only handles
argument parsing, async lifecycle, and exit codes.
"""
