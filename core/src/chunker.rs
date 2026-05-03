//! Chunker — splits a `FileDiff` into embedding-sized pieces.
//!
//! Strategy (per blueprint § 4.8):
//!   - diff   <  500 tokens  →  1 chunk per file (chunk_type = "file")
//!   - diff   500-2000 tokens →  split by hunk (`@@ ... @@` markers)
//!   - diff   > 2000 tokens   →  subdivide hunks with 10-20% overlap
//!   - binary / lock / generated → skipped before reaching this module
//!
//! The output `Chunk` is what the Python side eventually turns into a row
//! in `commit_chunks` and feeds to the embedding provider.

use crate::diff::{ChangeType, FileDiff};
use crate::errors::CoreError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChunkType {
    File,
    Hunk,
}

impl ChunkType {
    pub fn as_str(self) -> &'static str {
        match self {
            ChunkType::File => "file",
            ChunkType::Hunk => "hunk",
        }
    }
}

#[derive(Debug, Clone)]
pub struct Chunk {
    pub file_path: String,
    pub change_type: ChangeType,
    pub chunk_type: ChunkType,
    pub diff_content: String,
    pub tokens_used: usize,
}

/// Token thresholds — exposed as constants to keep them grep-able and
/// trivially adjustable without spelunking through code.
pub const SMALL_CHUNK_LIMIT: usize = 500;
pub const LARGE_CHUNK_LIMIT: usize = 2000;
pub const HUNK_OVERLAP_PCT: f32 = 0.15;

/// Split a single `FileDiff` into one or more chunks.
pub fn chunk_file(_file_diff: &FileDiff, _max_tokens: usize) -> Result<Vec<Chunk>, CoreError> {
    // PHASE 2-C IMPL — sketch:
    //
    // 1. Count tokens of the full diff_content via tokens::count().
    // 2. If total <= SMALL_CHUNK_LIMIT → emit one ChunkType::File and return.
    // 3. Else: split by hunk boundary (lines starting with "@@").
    //    For each hunk:
    //      - Count its tokens.
    //      - If <= max_tokens → emit ChunkType::Hunk.
    //      - Else → subdivide with HUNK_OVERLAP_PCT overlap of trailing lines
    //               from the previous sub-chunk to preserve context.
    todo!("implement after Fase 2-A baseline is established")
}

#[cfg(test)]
mod tests {
    // Cover: small diff (1 file chunk), medium diff (N hunk chunks),
    // huge diff (subdivided with overlap), diff with no hunks (rename-only).
}
