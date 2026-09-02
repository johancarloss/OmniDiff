"""OmniDiff CLI.

Entrypoint: `omnidiff <command> [args]` (console script), or
`python -m cli <command> [args]` from a source checkout.

Commands:
    index <url-or-path>   Index a Git repository.

The CLI is intentionally a thin adapter over `app.services.IngestService`.
All business logic lives in the service layer; the CLI only handles
argument parsing, async lifecycle, and exit codes.
"""
