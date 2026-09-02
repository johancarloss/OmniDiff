//! Criterion benchmarks for the Rust diff-extraction path.
//!
//! These are the source-of-truth numbers for the "before vs after"
//! claim of Phase 2-C. They run against fixture repos built in
//! `core/tests/common/` so results are reproducible.
//!
//! Run with:
//!     cargo bench --bench ingest_bench
//! HTML report:
//!     core/target/criterion/report/index.html
//!
//! Currently a registered but empty harness: `diff::extract` lands in
//! Slice 2-C.2, and there is nothing honest to measure before it does.
//! Walking and chunking are deliberately absent — Phase 2-B measured
//! both as not worth porting.

use criterion::{criterion_group, criterion_main, Criterion};

fn bench_extract_commit(_c: &mut Criterion) {
    // SLICE 2-C.2:
    // c.bench_function("extract / typical commit", |b| {
    //     b.iter(|| omnidiff_core::diff::extract(repo_path, commit_hash))
    // });
}

criterion_group!(benches, bench_extract_commit);
criterion_main!(benches);
