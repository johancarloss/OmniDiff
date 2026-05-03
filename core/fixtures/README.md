# Test Fixtures

Small synthetic Git repositories used by `cargo test` and `cargo bench`.

These are **not committed** as bare directories — instead, fixture builders
in `core/tests/common/mod.rs` (to be created in Phase 2-C.3) use the
`tempfile` + `git2` crates to construct repos in-memory at test time.

This keeps the repository clean and avoids the "binary blob in git" smell.
