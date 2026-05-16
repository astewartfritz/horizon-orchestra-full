//! # Orchestra Core
//!
//! High-performance Rust library providing:
//! - **Tokenizer**: Fast BPE tokenization compatible with tiktoken (cl100k_base, o200k_base)
//! - **Embedding Index**: HNSW approximate nearest neighbor search
//! - **JSON Parser**: Streaming JSON parser with field extraction and schema validation
//! - **Seccomp Compiler**: Compile seccomp-BPF filter programs from Orchestra profiles
//!
//! This crate exposes a Python module via PyO3 for seamless integration with the
//! Orchestra Python runtime.

pub mod tokenizer;
pub mod embedding_index;
pub mod json_parser;
pub mod seccomp_compiler;

use pyo3::prelude::*;

/// Register all submodules into the `orchestra_core` Python module.
#[pymodule]
fn orchestra_core(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Tokenizer submodule
    let tok_module = PyModule::new(py, "tokenizer")?;
    tokenizer::register_python_module(&tok_module)?;
    m.add_submodule(&tok_module)?;

    // Embedding index submodule
    let emb_module = PyModule::new(py, "embedding_index")?;
    embedding_index::register_python_module(&emb_module)?;
    m.add_submodule(&emb_module)?;

    // JSON parser submodule
    let json_module = PyModule::new(py, "json_parser")?;
    json_parser::register_python_module(&json_module)?;
    m.add_submodule(&json_module)?;

    // Seccomp compiler submodule
    let sec_module = PyModule::new(py, "seccomp_compiler")?;
    seccomp_compiler::register_python_module(&sec_module)?;
    m.add_submodule(&sec_module)?;

    // Top-level version info
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("__description__", env!("CARGO_PKG_DESCRIPTION"))?;

    Ok(())
}

/// Common error type used across orchestra-core modules.
#[derive(Debug, thiserror::Error)]
pub enum OrchestraError {
    #[error("tokenizer error: {0}")]
    Tokenizer(String),

    #[error("embedding index error: {0}")]
    EmbeddingIndex(String),

    #[error("JSON parser error: {0}")]
    JsonParser(String),

    #[error("seccomp error: {0}")]
    Seccomp(String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("serialization error: {0}")]
    Serde(#[from] serde_json::Error),
}

impl From<OrchestraError> for PyErr {
    fn from(err: OrchestraError) -> PyErr {
        pyo3::exceptions::PyRuntimeError::new_err(err.to_string())
    }
}

/// Result type alias for orchestra-core operations.
pub type OrchestraResult<T> = Result<T, OrchestraError>;
