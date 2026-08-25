# Cardre

Cardre is an open-source, auditable credit scorecard builder. A scorecard is not just a final model — it is an input dataset plus a traceable build pathway: profiling, binning, WOE/IV, model fitting, score scaling, validation, and export. Every step is reproducible and explainable.

## Quick Start

```bash
pip install -e ".[sidecar]"
cardre-api &
cd frontend && npm install && npm run dev
```

## Architecture (v2)

```
┌─────────────────────────────────────────────────────────┐
│                    cardre/ (engine)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ domain/  │  │  nodes/  │  │     services/         │  │
│  │ kernel   │  │ plugins  │  │ business logic        │  │
│  └────┬─────┘  └────┬─────┘  └──────────┬───────────┘  │
│       │             │                   │               │
│  ┌────▼─────────────▼───────────────────▼───────────┐  │
│  │                  store/                           │  │
│  │  SQLite metadata + filesystem artifacts           │  │
│  │  - evidence_edges / evidence_artifacts (2-level)  │  │
│  │  - relational join tables (no JSON arrays)        │  │
│  │  - plan_step_edges and evidence relationships      │  │
│  └─────────────────────┬─────────────────────────────┘  │
│                        │                                │
│  ┌─────────────────────▼─────────────────────────────┐  │
│  │              execution/                           │  │
│  │  RunCoordinator, PlanExecutor, evidence resolver  │  │
│  │  staleness checks, RunLifecycle, Worker            │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                    sidecar/ (FastAPI)                     │
│  ├── /api/projects — project-scoped API                  │
│  ├── /api/plans — plan CRUD + mutation commands          │
│  ├── /api/runs — run lifecycle (sync/async)              │
│  ├── /api/nodes — node type registry + parameter schema  │
│  └── /api/plans — manual-binning preview and review      │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│              frontend/ (React + Tauri)                   │
│  TypeScript types generated from OpenAPI schema          │
│  Hooks: useRunWatch, usePlanMutation, etc.              │
│  Components: PlanEditor, RunProgress, ManualBinningEditor│
└─────────────────────────────────────────────────────────┘
```

### Core Packages

- **`cardre/`** — pure-Python scorecard engine (no GUI dependency)
  - `cardre/domain/` — domain kernel: Project, Plan, PlanVersion, Run, Artifact, StepSpec, evidence models, errors
  - `cardre/nodes/` — canonical scorecard node registry and implementations
  - `cardre/application/` — port-driven use cases: runs, plans, reporting, projects
  - `cardre/adapters/` — SQLite persistence, filesystem artifact store, dispatch, evidence readers, reporting
  - `cardre/api/` — FastAPI route definitions (project-scoped)
  - `cardre/bootstrap/` — composition root: container, settings, node catalogue
  - `cardre/domain/evidence/` and `cardre/adapters/evidence/` — evidence kinds, models, reader, schemas
- **`sidecar/`** — FastAPI local API server (bundled as sidecar binary via PyInstaller)
- **`frontend/`** — React + TypeScript UI (Vite)
- **`frontend/src-tauri/`** — Tauri v2 Rust desktop shell

### Canonical Node Catalogue

The production node catalogue is exactly the set of node types required by
`_CANONICAL_SCORECARD_STEPS`. There are no deferred registrations or alternate
launch tiers.

### Two-Level Evidence Model

v2 introduces a proper two-level evidence model replacing v1's JSON-array-on-run_steps:

- `evidence_edges` — one row per parent→child edge at run time, tracking resolution policy, reuse, and staleness
- `evidence_artifacts` — one row per artifact attached to an evidence edge

This is the **only** lineage source. Staleness is computed from these tables, not written onto historical rows.

### Current State

The v2 refactor is complete. The engine supports:
- Full scorecard build pathway (import → profiling → binning → WOE/IV → variable selection → logistic regression → score scaling → validation → cutoff analysis → reporting)
- Two-level evidence model (`evidence_edges` + `evidence_artifacts`)
- Relational join tables (no JSON relationship arrays)
- Plan mutation (draft/committed, atomic commands)
- Run coordination (sync/async, stale-run recovery, cancellation)
- Manual binning with atomic review commands
- Evidence lookup centralized in the evidence resolver
- Audit export (evidence trail as the product)

## Roadmap

### Near-term

- **First real deployment** — when Cardre has its first deployed user, revisit the pre-release persistence policy in [ADR 0015](docs/adr/0015-no-compatibility-policy.md).
- **Coverage floor to 65–70%** — raise the enforced coverage floor from 60% toward the deferred target (see [CONTRIBUTING.md](CONTRIBUTING.md)).

### Medium-term

- **Performance at scale** — chunked processing and lazy evaluation for multi-million-row datasets, which credit scorecards routinely use.

### Long-term

- **Review workflow** — improve the manual-binning review and approval experience around the canonical pathway.

## Documentation

See `docs/README.md` for the full documentation index.

## Development

### Prerequisites

**Python** (3.11+):
```bash
pip install -e .
pip install -e ".[sidecar]"   # for the FastAPI sidecar
```

**Frontend** (Node 20+):
```bash
cd frontend && npm install
```

**Tauri Desktop** (for `npm run tauri dev`):
- Linux: `sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev`
- macOS: Xcode CLI tools
- Windows: WebView2 (included in Windows 10+)

### Build Sidecar Binary

```bash
pip install pyinstaller
./scripts/build-sidecar.sh
```

Produces `frontend/src-tauri/binaries/cardre-api-{target-triple}` for Tauri bundling.
The target triple is embedded at Rust compile time by `tauri-build`. In dev,
`main.rs` falls back to `cardre-api` on PATH (from `pip install -e ".[sidecar]"`).
See [docs/release/sidecar-packaging.md](docs/release/sidecar-packaging.md) for details.

### Run Tests

```bash
python3 -m pytest tests/ -q
cd frontend && npm test
```

### CI

See `.github/workflows/ci.yml` — runs Python tests, frontend typecheck, and sidecar build on push/PR to `main`.
