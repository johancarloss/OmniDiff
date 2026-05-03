//! Criterion benchmarks for the Rust ingestion path.
//!
//! These benchmarks are the source-of-truth numbers for the
//! "before vs after" claim in the portfolio. They run against fixture
//! repos in `core/fixtures/` so results are reproducible.
//!
//! Run with:
//!     cargo bench --bench ingest_bench
//! HTML report:
//!     core/target/criterion/report/index.html

use criterion::{criterion_group, criterion_main, Criterion};

fn bench_walk_small_repo(_c: &mut Criterion) {
    // PHASE 2-C IMPL:
    // c.bench_function("walk_commits / small repo (~50 commits)", |b| {
    //     b.iter(|| {
    //         let _ = omnidiff_core::walker::walk(
    //             "fixtures/small-repo",
    //             None,
    //         );
    //     })
    // });
}

fn bench_extract_chunks_typical_commit(_c: &mut Criterion) {
    // PHASE 2-C IMPL:
    // c.bench_function("extract_chunks / typical commit (~10 files)", |b| {
    //     b.iter(|| {
    //         let _ = omnidiff_core::diff::extract(
    //             "fixtures/small-repo",
    //             "<known-hash>",
    //         );
    //     })
    // });
}

fn bench_extract_chunks_batch(_c: &mut Criterion) {
    // PHASE 2-C IMPL:
    // Compare serial vs rayon-parallel paths on the same set of commits.
    // Expected speedup on a 4-core box: ~3x (Amdahl + libgit2 overhead).
}

criterion_group!(
    benches,
    bench_walk_small_repo,
    bench_extract_chunks_typical_commit,
    bench_extract_chunks_batch,
);
criterion_main!(benches);
