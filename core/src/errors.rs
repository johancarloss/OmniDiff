//! Typed errors used throughout the crate.
//!
//! Mapped to Python exceptions at the PyO3 boundary so callers see real
//! `ValueError` / `IOError` instead of opaque "RuntimeError: <something>".

use pyo3::exceptions::{PyIOError, PyRuntimeError, PyValueError};
use pyo3::PyErr;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoreError {
    #[error("git error: {0}")]
    Git(#[from] git2::Error),

    #[error("invalid argument: {0}")]
    Invalid(String),

    #[error("tokenizer error: {0}")]
    Tokenizer(String),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

impl From<CoreError> for PyErr {
    fn from(err: CoreError) -> PyErr {
        match err {
            CoreError::Invalid(msg) => PyValueError::new_err(msg),
            CoreError::Io(e) => PyIOError::new_err(e.to_string()),
            CoreError::Git(e) => PyRuntimeError::new_err(format!("git: {e}")),
            CoreError::Tokenizer(msg) => PyRuntimeError::new_err(format!("tokenizer: {msg}")),
        }
    }
}
