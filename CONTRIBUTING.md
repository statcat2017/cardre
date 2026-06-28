# Contributing to Cardre

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Rust (for Tauri builds)

### Install

```bash
pip install -e ".[sidecar,dev,test]"
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

Before submitting a PR, run all of the following. These are the same checks
CI enforces as blocking quality gates.

```bash
# Python
ruff check --fix
make preflight
```

Auto-fixes: `ruff check --fix` (Python lint), `npm run format` (Prettier).
Regenerate API types after changing the FastAPI app with
`python3 scripts/generate-openapi-types.py`, then commit
`frontend/src/api/schema.d.ts` and `frontend/src/api/openapi.json` together.
Generated API files are excluded from Prettier (see `frontend/.prettierignore`)
and ESLint (see `frontend/eslint.config.js`) and from line-count limits
(see `scripts/check-line-counts.py`); the `check-api-contracts` CI job verifies
they are not stale.

## Pull Request Process

1. Create a feature branch from `main`.
2. Make your changes.
3. Run tests and lint checks.
4. Push your branch and open a PR.
5. Ensure CI passes (Python tests, frontend typecheck, sidecar build).

## Documentation

If your change affects the public API, architecture, or user-facing behaviour, update the relevant docs in `docs/`. See `docs/README.md` for the documentation index.

## Code of Conduct

This project is governed by the [Contributor Covenant](https://www.contributor-covenant.org/). By participating, you agree to maintain a respectful and inclusive environment.
