//! Token counting — used by the chunker to size diffs against the embedding
//! model's context window.
//!
//! We use `tiktoken-rs` (same BPE tokenizer family as OpenAI / Voyage) as a
//! good-enough approximation. Voyage's exact tokenizer isn't public, but
//! cl100k_base is a conservative upper bound for our chunking decisions —
//! and chunking decisions only need to be approximately right.

use crate::errors::CoreError;

/// Count tokens in `text` using cl100k_base (ChatGPT/GPT-4 tokenizer).
///
/// Returns 0 for empty input. Errors only if tokenizer initialization fails.
pub fn count(_text: &str) -> Result<usize, CoreError> {
    // PHASE 2-C IMPL — sketch:
    //
    // use tiktoken_rs::cl100k_base;
    // let bpe = cl100k_base()?;
    // Ok(bpe.encode_with_special_tokens(text).len())
    todo!("implement after Fase 2-A baseline is established")
}

#[cfg(test)]
mod tests {
    // Cover: empty string → 0, ASCII text, UTF-8 multi-byte (emoji),
    // huge input doesn't panic.
}
