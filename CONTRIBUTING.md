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

The canonical commands that CI enforces are `make test-python-ci` (backend)
and `npm run test:coverage` (frontend). Use `npm test` for focused local
frontend runs; it does not enforce coverage thresholds over unrun files.

## Test Architecture

The suite is organized around a small set of deliberate patterns recorded in
[ADR 0018](docs/adr/0018-test-architecture-layered-suite.md). Canonical
locations and commands:

- **Backend**
  - `make test-python-ci` — full suite + global 60% statement floor +
    global 60% branch floor + per-package statement floors (via
    `scripts/check-coverage-thresholds.py`).
  - `tests/domain/` — pure invariant tests (no I/O). See `test_invariants.py`.
  - `tests/ports/` — port contract tests parametrized over the real adapter
    and an in-memory fake. See `test_artifact_store_contract.py`.
  - `tests/test_golden_fixtures_roundtrip.py` and `tests/test_golden_report_bundle.py`
    — golden round-trip / structural comparator tests against fixtures in
    `tests/fixtures/`.
- **Frontend**
  - Unit tests are colocated with source under `frontend/src/components/__tests__/`
    and `frontend/src/hooks/__tests__/`, plus `frontend/src/App.test.tsx`.
  - `npm run test:coverage` — full-suite 60/60/60/50 (lines/statements/
    functions/branches) coverage gate used by CI and `make preflight`.

### Coverage Policy

- Python coverage must not decrease.
- The global statement coverage floor is **60%** (enforced via `make
  test-python-ci`, `make preflight`, and CI). Per-package statement floors are
  enforced by `scripts/check-coverage-thresholds.py`.
- Branch coverage is measured on the backend via `--cov-branch`, with a
  **global 60% branch floor** enforced by `scripts/check-coverage-thresholds.py`
  in `make test-python-ci` and `make preflight`. Per-package branch floors are
  explicitly deferred this sprint (see ADR 0018).
- Frontend coverage must meet the 60/60/60/50 gate in CI and `make preflight`.
- New or materially changed execution, evidence, network, API, and model-node
  code must include behavior tests — not just trivial getter or import tests.
- Coverage increases should prioritize launch-relevant behavior over trivial
  line coverage.
- The deferred next-sprint target is 65–70%.

### Code Style

- Python: follow existing patterns in `cardre/` and `sidecar/`. Use type hints.
- TypeScript: follow existing patterns in `frontend/src/`. The project uses strict TypeScript.
- Rust: follow existing patterns in `frontend/src-tauri/`.

### Pre-commit Checks

Before submitting a PR, run the local checks below. CI also adds packaged sidecar and Tauri jobs.

```bash
# Python
ruff check --fix
make preflight
```

Auto-fixes: `ruff check --fix` (Python lint), `npm run format` (Prettier).
`make preflight` covers the local Python and frontend checks plus governance-mode pytest and generated OpenAPI freshness. The PR gate still waits for the full GitHub CI run.
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
