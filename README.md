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
│  │  - plan_step_edges, comparison_*_branches, etc.   │  │
│  └─────────────────────┬─────────────────────────────┘  │
│                        │                                │
│  ┌─────────────────────▼─────────────────────────────┐  │
│  │              execution/                           │  │
│  │  RunCoordinator, PlanExecutor, EvidenceLocator    │  │
│  │  StalenessService, RunLifecycle, Worker           │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                    sidecar/ (FastAPI)                     │
│  ├── /api/projects — project-scoped API                  │
│  ├── /api/plans — plan CRUD + mutation commands          │
│  ├── /api/runs — run lifecycle (sync/async)              │
│  ├── /api/nodes — node type registry + parameter schema  │
│  └── /api/admin — governance: branches, comparisons,     │
│                   champion assignments, manual binning   │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│              frontend/ (React + Tauri)                   │
│  TypeScript types generated from OpenAPI schema          │
│  Hooks: useRunWatch, usePlanMutation, etc.              │
│  Components: PlanEditor, RunProgress, BranchView,       │
│  ComparisonView, ChampionView, ManualBinningEditor      │
└─────────────────────────────────────────────────────────┘
```

### Core Packages

- **`cardre/`** — pure-Python scorecard engine (no GUI dependency)
  - `cardre/domain/` — domain kernel: Project, Plan, PlanVersion, Run, Artifact, StepSpec, evidence models, errors
  - `cardre/nodes/` — node registry + plugin implementations (launch and deferred tiers)
  - `cardre/services/` — stateless business logic: RunCoordinator, StalenessService, PlanMutationService, BranchService, ComparisonService, ChampionService, ManualBinningService, ExportService
  - `cardre/store/` — SQLite-backed ProjectStore with per-table repositories (PlanRepository, BranchRepository, ComparisonRepository, etc.)
  - `cardre/execution/` — execution engine: PlanExecutor, RunLifecycle, Worker
  - `cardre/api/` — FastAPI route definitions (project-scoped)
  - `cardre/reporting/` — report rendering and collector
  - `cardre/_evidence/` — evidence kinds, models, reader, schemas
- **`sidecar/`** — FastAPI local API server (bundled as sidecar binary via PyInstaller)
- **`frontend/`** — React + TypeScript UI (Vite)
- **`frontend/src-tauri/`** — Tauri v2 Rust desktop shell

### Node Tiers

Cardre v2 uses node tiers to control feature availability:

| Tier | Description |
|------|-------------|
| `launch` | Nodes executable in the default scorecard journey. All canonical scorecard steps. |
| `deferred` | Registered as schemas for UI display but not executable in launch mode (boosting, ensembles, fairness, reject inference, tuning, explainability). Instantiation raises `NodeNotAvailableForLaunch`. |

Launch mode is controlled by `CardreConfig` (defaults to `launch_mode=True`). Set `CARDRE_LAUNCH_MODE=0` to enable all nodes. See `docs/launch-mode.md`.

### Governance (Enterprise)

Governance features (branching, comparison, champion assignment) are gated behind `CARDRE_GOVERNANCE=1`:

- **Branching**: Create challenger branches from permitted branch points in a plan. Each branch creates a new plan version with duplicated downstream steps and shared upstream steps.
- **Comparison**: Compare baseline vs challenger branches on WOE/IV, model coefficients, validation metrics, and cutoff analysis. Produces immutable comparison snapshots.
- **Champion**: Designate the best-performing branch for a scope. Supersedes previous champions automatically.

### Two-Level Evidence Model

v2 introduces a proper two-level evidence model replacing v1's JSON-array-on-run_steps:

- `evidence_edges` — one row per parent→child edge at run time, tracking resolution policy, reuse, and staleness
- `evidence_artifacts` — one row per artifact attached to an evidence edge

This is the **only** lineage source. Staleness is computed from these tables, not written onto historical rows.

### Current State

The v2 refactor is complete. The engine supports:
- Full scorecard build pathway (import → profiling → binning → WOE/IV → variable selection → logistic regression → score scaling → validation → cutoff analysis → reporting)
- Launch/deferred node tier enforcement
- Two-level evidence model (`evidence_edges` + `evidence_artifacts`)
- Relational join tables (no JSON relationship arrays)
- Governance: branching, comparison, champion assignment
- Plan mutation (draft/committed, atomic commands)
- Run coordination (sync/async, stale-run recovery, cancellation)
- Manual binning with atomic review commands
- Evidence lookup centralized in `EvidenceLocator`, with branch-current short-circuit checks at launch time
- Audit export (evidence trail as the product)

## Roadmap

### Near-term

- **Productionise deferred nodes** — promote the most mature deferred nodes (decision tree, probability calibration, reject inference) from schema-only to executable in launch mode.
- **First real deployment** — when Cardre has its first deployed user, revisit [ADR 0003](docs/adr/0003-no-legacy-plan-accommodation.md) and establish a persisted-plan compatibility / migration strategy.
- **Coverage floor to 65–70%** — raise the enforced coverage floor from 60% toward the deferred target (see [CONTRIBUTING.md](CONTRIBUTING.md)).

### Medium-term

- **Deferred node graduation** — bring boosting models (XGBoost, LightGBM, CatBoost), fairness, explainability, and hyperparameter tuning to executable status.
- **Governance graduation** — move governance (branch/comparison/champion) from opt-in (`CARDRE_GOVERNANCE=1`) to default-on once the workflow is proven in real use.
- **Performance at scale** — chunked processing and lazy evaluation for multi-million-row datasets, which credit scorecards routinely use.

### Long-term

- **Approval workflow** — 4-eyes sign-off pattern (modeller builds, validator reviews, approver signs) for model risk governance.
- **Reject inference as a first-class phase** — not just a node, but a named phase in the pathway with its own evidence and review surface.

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
