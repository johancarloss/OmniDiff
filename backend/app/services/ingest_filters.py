"""File and commit filters applied during ingestion.

This module is a deliberate Python mirror of `core/src/filters.rs`.
Both must keep the same constants and the same `should_skip_file` /
`should_skip_commit` semantics so that the Phase 2-C Rust port can
swap in without changing observable behavior.

When updating filter rules, **change both files in the same PR** and
add the matching test to both the Python and Rust suites.
"""

from pathlib import PurePosixPath

# File names that are almost never worth indexing semantically.
# Mirror of `core::filters::LOCK_FILES`.
LOCK_FILES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "Gemfile.lock",
        "composer.lock",
        "go.sum",
    }
)

# Path fragments that mark generated/vendored content.
# Mirror of `core::filters::GENERATED_PATH_FRAGMENTS`.
# Kept as a tuple (not frozenset) because matching is substring-based,
# not equality-based.
GENERATED_PATH_FRAGMENTS: tuple[str, ...] = (
    "/node_modules/",
    "/vendor/",
    "/.venv/",
    "/dist/",
    "/build/",
    "/target/",
    "/__pycache__/",
    "/.next/",
    "/.cache/",
)

# File extensions treated as binary regardless of git's own detection.
# Mirror of `core::filters::BINARY_EXTENSIONS`. All entries are lowercase
# — `should_skip_file` lower-cases the file's extension before matching.
BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "ico",
        "bmp",
        "tiff",
        "mp3",
        "mp4",
        "wav",
        "avi",
        "mov",
        "webm",
        "pdf",
        "zip",
        "tar",
        "gz",
        "7z",
        "rar",
        "exe",
        "dll",
        "so",
        "dylib",
        "bin",
        "woff",
        "woff2",
        "ttf",
        "otf",
    }
)


def should_skip_file(path: str, *, is_binary_in_git: bool) -> bool:
    """Return True if this file path should be skipped during indexing.

    Mirror of `core::filters::should_skip_file`. Decision order:
      1. If git detected the file as binary → skip.
      2. If basename matches a known lock file → skip.
      3. If extension (lower-cased) is a known binary type → skip.
      4. If any path fragment matches a generated/vendored marker → skip.
      5. Otherwise: keep.
    """
    if is_binary_in_git:
        return True

    # PurePosixPath because git always emits forward-slash paths, regardless
    # of host OS. Using Path here would be subtly wrong on Windows runners.
    p = PurePosixPath(path)

    if p.name in LOCK_FILES:
        return True

    # PurePosixPath.suffix returns ".png", ".tar.gz" → just ".gz". Strip
    # the dot and lower-case before comparing.
    suffix = p.suffix.lstrip(".").lower()
    if suffix and suffix in BINARY_EXTENSIONS:
        return True

    # Substring match against path fragments. Prepend "/" so a fragment
    # like "/node_modules/" matches "node_modules/foo" at the start of the
    # string as well as deep inside.
    with_leading_slash = f"/{path}"
    return any(frag in with_leading_slash for frag in GENERATED_PATH_FRAGMENTS)


def should_skip_commit(parent_count: int) -> bool:
    """Return True if a commit should be skipped (currently: merge commits).

    Mirror of `core::filters::should_skip_commit`. Merge commits have
    `parent_count > 1`; root has 0; normal has 1.
    """
    return parent_count > 1
