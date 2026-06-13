# Phase 4 Exit Checklist

## Tag: `v0.4.0-alpha`

Phase 4 delivered constrained branching, champion/challenger comparison, immutable snapshots, and selected-branch export for the Cardre scorecard workspace.

---

## Complete

| Area | Status | Notes |
|---|---|---|
| StepSpec branch fields | Done | `canonical_step_id`, `branch_id` with backwards-compatible `__post_init__` backfill |
| Branch SQLite schema | Done | 5 tables: `plan_branches`, `branch_step_map`, `branch_comparisons`, `branch_comparison_snapshots`, `champion_assignments` |
| Project store migration | Done | `run_migrations()` adds columns/tables; baseline migration service creates baseline branch per plan |
| Branch read model | Done | `GET /projects/{project_id}/branches`, `GET /branches/{branch_id}` |
| Branch creation | Done | `POST /plans/{plan_id}/branches` with 6 permitted branch points, descendant closure, step ID generation, atomic transaction |
| Branch-aware param editing | Done | Branch-owned edits update `head_plan_version_id` and copy `branch_step_map` atomically |
| Branch-scoped execution | Done | `POST /runs` with `run_scope=branch`; shared-upstream stale blocking; short-circuits on no-op |
| Branch-aware manual binning | Done | Editor/preview accept any step ID; canonical-step-id ancestor resolver per Section 15.4 |
| Segment challenger branches | Done | Creation from `sample-definition` with filter-spec validation |
| Comparison engine | Done | Intent creation, readiness checks, immutable JSON snapshots with WOE/IV, model, validation, cutoff |
| Champion assignment | Done | Comparison-snapshot requirement, rationale, atomic supersession |
| Selected branch export | Done | Branch-scoped evidence, full lineage, row-level data filter |
| Tests | 153 | 126 existing + 26 Batch 0 unit + 1 comprehensive E2E |
| Frontend types/client | Done | TypeScript interfaces and API client methods for all new endpoints |
| Backend test coverage | 26 + 1 | StepSpec compatibility, schema migration, branch CRUD, baseline migration, E2E flow |
| Baseline comparison content | Done | Uses full-plan evidence (`branch_id=NULL`) |
| No-op branch run prevention | Done | Short-circuits when all branch-owned steps current, returns existing run |
| Branch-staleness shared-upstream seed | Done | `compute_staleness(branch_id)` seeds full-plan records into `rs_by_step` |

---

## Deliberately Deferred

| Area | Rationale | When |
|---|---|---|
| **Frontend Branch Manager UI** | API/types exist; full React component (wizard, lane view, champion badges) is Phase 4 surface that was scoped for follow-on | Phase 5+ or separate frontend pass |
| **Frontend Comparison View** | Same — API/client ready, no React rendering of comparison tables | Phase 5+ |
| **Frontend Champion Modal / Export Flow** | Champion and export endpoints work via API; UI wiring is pending | Phase 5+ |
| **Freeform DAG editing** | Out of scope for Phase 4 by design | Phase 6 |
| **Branch merging** | Explicitly deferred in spec | Post-Phase 6 |
| **Multi-user review / approval** | Deferred | Future |
| **PMML/ONNX export** | Deferred | Future |
| **Hosted execution** | Deferred | Future |
| **Reject inference** | Deferred | Future |
| **Governance narrative report** | This is Phase 5 | Phase 5 |
| **Custom Python plugin nodes** | Deferred | Phase 6 |

---

## Verification

```bash
pytest tests/                          # 153 passed
cd frontend && npx tsc --noEmit        # TypeScript clean
cd frontend && npm run build            # Vite production build
git log v0.4.0-alpha..HEAD --oneline    # No commits after tag
```
