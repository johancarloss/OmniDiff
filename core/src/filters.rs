//! Filters — decide which files / commits should be skipped before chunking.
//!
//! Skipping early matters: every file that reaches the chunker eventually
//! costs us a Voyage embedding call. Filtering aggressively here saves
//! both money (free-tier tokens) and indexing time.

use std::path::Path;

/// File names that are almost never worth indexing semantically.
pub const LOCK_FILES: &[&str] = &[
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
];

/// Path fragments that mark generated/vendored content.
pub const GENERATED_PATH_FRAGMENTS: &[&str] = &[
    "/node_modules/",
    "/vendor/",
    "/.venv/",
    "/dist/",
    "/build/",
    "/target/",
    "/__pycache__/",
    "/.next/",
    "/.cache/",
];

/// File extensions treated as binary regardless of git's own detection.
pub const BINARY_EXTENSIONS: &[&str] = &[
    "png", "jpg", "jpeg", "gif", "webp", "ico", "bmp", "tiff",
    "mp3", "mp4", "wav", "avi", "mov", "webm",
    "pdf", "zip", "tar", "gz", "7z", "rar",
    "exe", "dll", "so", "dylib", "bin",
    "woff", "woff2", "ttf", "otf",
];

/// Return true if this file path should be skipped during indexing.
pub fn should_skip_file(path: &str, is_binary_in_git: bool) -> bool {
    if is_binary_in_git {
        return true;
    }
    let p = Path::new(path);
    if let Some(name) = p.file_name().and_then(|n| n.to_str()) {
        if LOCK_FILES.contains(&name) {
            return true;
        }
    }
    if let Some(ext) = p.extension().and_then(|e| e.to_str()) {
        if BINARY_EXTENSIONS.contains(&ext.to_lowercase().as_str()) {
            return true;
        }
    }
    let with_slashes = format!("/{}", path);
    GENERATED_PATH_FRAGMENTS
        .iter()
        .any(|frag| with_slashes.contains(frag))
}

/// Return true if a commit should be skipped (currently: merge commits).
pub fn should_skip_commit(parent_count: usize) -> bool {
    parent_count > 1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lock_files_are_skipped() {
        assert!(should_skip_file("package-lock.json", false));
        assert!(should_skip_file("backend/uv.lock", false));
    }

    #[test]
    fn generated_paths_are_skipped() {
        assert!(should_skip_file("frontend/node_modules/foo/index.js", false));
        assert!(should_skip_file("backend/.venv/lib/site-packages/x.py", false));
    }

    #[test]
    fn binary_extensions_are_skipped() {
        assert!(should_skip_file("docs/screenshot.png", false));
        assert!(should_skip_file("logo.SVG.PNG", false)); // case-insensitive on ext
    }

    #[test]
    fn source_files_are_not_skipped() {
        assert!(!should_skip_file("backend/app/main.py", false));
        assert!(!should_skip_file("frontend/src/App.tsx", false));
    }

    #[test]
    fn merge_commits_are_skipped() {
        assert!(!should_skip_commit(0)); // root
        assert!(!should_skip_commit(1)); // normal
        assert!(should_skip_commit(2));  // merge
    }
}
