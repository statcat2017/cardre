# Contributing to Cardre

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Rust (for Tauri builds)

### Install

```bash
pip install -e ".[sidecar,test]"
cd frontend && npm install
```

### Run Tests

```bash
python3 -m pytest tests/ -q
cd frontend && npm test
```

### Code Style

- Python: follow existing patterns in `cardre/` and `sidecar/`. Use type hints.
- TypeScript: follow existing patterns in `frontend/src/`. The project uses strict TypeScript.
- Rust: follow existing patterns in `frontend/src-tauri/`.

### Pre-commit Checks

Before submitting a PR, run:

```bash
python3 -m pytest tests/ -q
python3 scripts/check-line-counts.py
python3 scripts/check_doc_references.py
cd frontend && npx tsc --noEmit
```

## Pull Request Process

1. Create a feature branch from `main`.
2. Make your changes.
3. Run tests and lint checks.
4. Push your branch and open a PR.
5. Ensure CI passes (Python tests, frontend typecheck, sidecar build, doc references).

## Documentation

If your change affects the public API, architecture, or user-facing behaviour, update the relevant docs in `docs/`. See `docs/README.md` for the documentation index.

## Code of Conduct

This project is governed by the [Contributor Covenant](https://www.contributor-covenant.org/). By participating, you agree to maintain a respectful and inclusive environment.
