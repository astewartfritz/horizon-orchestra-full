from __future__ import annotations

from pathlib import Path

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec

CARGO_TOML = '''[package]
name = "{name}"
version = "0.1.0"
edition = "2021"
description = "{description}"

[dependencies]
clap = {{ version = "4", features = ["derive"] }}
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
anyhow = "1"
thiserror = "1"
tokio = {{ version = "1", features = ["full"] }}
reqwest = {{ version = "0.12", features = ["json"] }}
tracing = "0.1"
tracing-subscriber = {{ version = "0.3", features = ["env-filter"] }}

[dev-dependencies]
criterion = "0.5"
assert_cmd = "2"
predicates = "3"
tempfile = "3"

[[bench]]
name = "benchmark"
harness = false

[profile.release]
opt-level = 3
lto = true
'''

MAIN_RS = '''use clap::Parser;

#[derive(Parser)]
#[command(name = "{name}", version, about = "{description}")]
struct Cli {{
    #[arg(short, long)]
    verbose: bool,
}}

#[tokio::main]
async fn main() -> anyhow::Result<()> {{
    let _cli = Cli::parse();
    tracing_subscriber::fmt::init();
    println!("Hello from {name}");
    Ok(())
}}
'''

LIB_RS = '''pub mod types;
pub mod utils;

pub fn version() -> &'static str {{
    env!("CARGO_PKG_VERSION")
}}
'''

TYPES_RS = '''use serde::{{Deserialize, Serialize}};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {{
    pub name: String,
    pub verbose: bool,
}}

impl Default for Config {{
    fn default() -> Self {{
        Self {{ name: "{name}".into(), verbose: false }}
    }}
}}
'''

UTILS_RS = '''use anyhow::Result;

pub fn setup_logging(verbose: bool) {{
    let filter = if verbose {{ "debug" }} else {{ "info" }};
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .init();
}}

pub async fn fetch_json(url: &str) -> Result<serde_json::Value> {{
    let resp = reqwest::get(url).await?;
    Ok(resp.json().await?)
}}
'''

INTEGRATION_TEST = '''use assert_cmd::Command;

#[test]
fn test_cli_version() {{
    let mut cmd = Command::cargo_bin("{name}").unwrap();
    cmd.arg("--version").assert().success();
}}

#[test]
fn test_cli_help() {{
    let mut cmd = Command::cargo_bin("{name}").unwrap();
    cmd.arg("--help").assert().success();
}}
'''

BENCHMARK_RS = '''use criterion::{{criterion_group, criterion_main, Criterion}};

fn benchmark(c: &mut Criterion) {{
    c.bench_function("example", |b| b.iter(|| {{
        2 + 2
    }}));
}}

criterion_group!(benches, benchmark);
criterion_main!(benches);
'''

RUSTFMT_TOML = '''max_width = 100
hard_tabs = false
tab_spaces = 4
edition = "2021"
'''

CLIPPY_TOML = '''[clippy]
warn_on_all = true

[clippy.flags]
deny = ["clippy::unwrap_used", "clippy::expect_used"]
'''

GITIGNORE_RUST = '''/target/
Cargo.lock
*.pyc
__pycache__/
.idea/
*.swp
*.swo
'''

CI_YML = '''name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: actions-rust-lang/setup-rust-toolchain@v1
    - run: cargo check
    - run: cargo clippy -- -D warnings
    - run: cargo fmt --check
    - run: cargo test
'''

README_RUST = '''# {name}

{description}

## Quick Start

```bash
cargo run -- --help
cargo test
cargo clippy
```

## License

MIT
'''


RUST_TEMPLATES: dict[str, dict[str, str]] = {
    "rust-package": {
        "Cargo.toml": CARGO_TOML,
        "src/main.rs": MAIN_RS,
        "src/lib.rs": LIB_RS,
        "src/types.rs": TYPES_RS,
        "src/utils.rs": UTILS_RS,
        "tests/integration.rs": INTEGRATION_TEST,
        "benches/benchmark.rs": BENCHMARK_RS,
        ".rustfmt.toml": RUSTFMT_TOML,
        ".clippy.toml": CLIPPY_TOML,
        ".github/workflows/ci.yml": CI_YML,
        ".gitignore": GITIGNORE_RUST,
        "README.md": README_RUST,
    },
}


class RustScaffold(Tool):
    spec = ToolSpec(
        name="scaffold_rust",
        description="Generate a Rust project with Cargo workspace, CLI (clap), async runtime (tokio), HTTP client (reqwest), serde, tests (criterion + assert_cmd), CI, and linting config.",
        parameters={
            "name": {"type": "string", "description": "Project name"},
            "description": {"type": "string", "description": "Short description", "default": ""},
            "output_dir": {"type": "string", "description": "Output directory"},
        },
    )

    async def __call__(self, name: str, description: str = "", output_dir: str | None = None) -> ToolResult:
        out = Path(output_dir or name).resolve()
        out.mkdir(parents=True, exist_ok=True)
        created = []
        for relpath, content in RUST_TEMPLATES["rust-package"].items():
            fpath = out / relpath
            fpath.parent.mkdir(parents=True, exist_ok=True)
            formatted = content.format(name=name, description=description or f"A Rust project")
            fpath.write_text(formatted, "utf-8")
            created.append(str(fpath.relative_to(out.parent)))
        summary = "\n".join(f"  + {p}" for p in created)
        return ToolResult(output=f"Scaffolded Rust project '{name}' at {out}\n{summary}")
