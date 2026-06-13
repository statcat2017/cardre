# Phase 4 — Starting Point

## State of the codebase after Phase 3

Phase 3 delivered a fixed-pathway desktop GUI with a real backend, manual binning, stale detection, and artefact inspection. The architecture has been hardened:

- **Backend plan logic** lives in `PlanService` (not in route handlers).
- **Fingerprints** are built by a single `make_fingerprint()` helper in `artifacts.py`.
- **Pathway/status endpoints** are stable and tested (126 tests).
- **Scorecard Pathway E2E** is covered end-to-end.
- **Adaptor layer** (`_get_store_for_project`) is consolidated in `projects.py`.
- **StepSpec construction** is unified via `replace_step_params()` in `audit.py`.

## Branch

All Phase 4 work should branch from `main` (after the Phase 3 closing PR is merged).

```bash
git checkout main
git pull
git checkout -b phase-4-branching
```

## What Phase 4 could explore

The obvious next direction is **branching, comparison, and champion/challenger** — enabling a user to fork a plan, try different parameter configurations, and compare results side by side. Specific ideas:

1. **Plan branching** — fork a plan version, modify params independently, run both, compare outputs.
2. **Champion/challenger** — designate one branch as champion, track challenger metrics against it.
3. **DAG-ish UI** — visualise the step graph (not just linear pathway) with collapsible detail.
4. **Compare view** — side-by-side artefact diff for two runs of the same step.
5. **Export improvements** — ZIP download from the UI, not just a manifest JSON.

## What Phase 4 should not do

- Do **not** mutate the Phase 3 API contract (see `phase-3-acceptance.md` for the frozen list).
- Do **not** get drawn into packaging/distribution (Tauri bundling, installers, cross-platform builds).
- Do **not** add async execution without a clear bottleneck measurement first.
- Do **not** rewrite the manual binning editor unless the override model changes fundamentally.

## Rough edges to address early in Phase 4

The issues logged at Phase 3 close are good candidates for the first few Phase 4 PRs:

1. Reject manual-binning overrides for non-selected variables.
2. Project-registry diagnostics for moved/deleted folders.
3. Explicit carried-forward status metadata.
4. Better unsupported/large artefact previews.
5. Loading/progress feedback for long synchronous runs.
6. First-run/help copy for plan-vs-import evidence.
7. Tauri packaging: system deps, sidecar binary, Cargo features.

## Architecture that stays

| Module | Role |
|--------|------|
| `cardre/services/plan_service.py` | Plan query + mutation logic |
| `cardre/artifacts.py` | Artifact writing helpers + fingerpints |
| `cardre/audit.py` | Data classes + `replace_step_params()` |
| `cardre/executor.py` | Topological step execution |
| `cardre/nodes.py` | Node implementations (one class per step) |
| `cardre/store.py` | SQLite persistence (only file with `_connect()`) |
| `sidecar/routes/` | Thin HTTP delegation (no business logic) |
| `sidecar/models.py` | Pydantic request/response models |
| `frontend/src/api/client.ts` | Typed API client |

## Verification before each Phase 4 PR

```bash
pytest                           # 126 tests
cd frontend && npx tsc --noEmit  # TypeScript
cd frontend && npm run build     # Vite production build
```
