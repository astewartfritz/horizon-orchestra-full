# Contributing to Horizon Orchestra

## Development Setup

```bash
git clone https://github.com/astewartfritz/horizon-orchestra
cd horizon-orchestra
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
```

## Code Standards

- **Python**: type hints, docstrings, `__all__` on every module. Ruff for linting.
- **TypeScript**: strict mode, no `any`, JSDoc on public methods.
- **Go**: standard `gofmt` formatting.
- **Rust**: `cargo fmt`, `cargo clippy`.
- **Shell**: `set -euo pipefail`, `shellcheck`.

## Branching

- `main` — stable releases
- `dev` — active development
- Feature branches: `feature/short-description`

## Commit Messages

```
<type>: <short description>

type: feat | fix | refactor | docs | test | chore
```
