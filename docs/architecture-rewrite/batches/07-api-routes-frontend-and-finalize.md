# Batch 07 — API Routes + Frontend Regeneration + Delete Old Architecture + Finalize Enforcement

```text
You are implementing one bounded batch of the Cardre architecture rewrite.

Do not redesign the wider system.

Do not broaden the scope.

Inspect the current repository before editing because earlier batches may already have changed the paths referenced here.

Preserve validated mathematical and product behaviour, but do not preserve obsolete internal APIs or compatibility layers.

Complete this batch fully, including tests and deletion of code superseded within its scope.
```

## 1. Task objective

Rewrite all remaining API routes as thin handlers calling use cases; write the full `api/schemas.py`; wire governance router; regenerate OpenAPI + `schema.d.ts`; update the frontend client (remove `projectHeaders`/`X-Project-Id`), `useProjectWorkspace` (new endpoints, `cancelRun` mutation, terminal statuses), and components. **Then delete all remaining old architecture code (`cardre/store/`, `cardre/config.py`, `cardre/artifacts.py`, `cardre/capabilities.py`; `cardre/engine/` and `cardre/workflows/` were already moved/deleted in Batch 03 per D19), tighten `importlinter` + un-xfail forbidden-symbol tests to be globally blocking, and run the full product acceptance pathway.** This batch merges the original "API routes + frontend" batch with the original "delete old + finalize enforcement" batch — the cleanup is small once the API is live, and merging saves a PR cycle. The acceptance pathway test is the gate that confirms the clean cut is complete.

## 2. Repository context

Read `docs/architecture-rewrite/05-api-and-frontend-boundary.md` (all endpoints, handler mapping, error mapping, frontend migration), `06-sprint-plan.md` (code-deletion milestones, acceptance pathway allocation), `08-acceptance-and-test-strategy.md` (product acceptance pathway). Batches 01 (health+projects routes + enforcement skeleton), 05 (runs use cases), 06 (plans/evidence/governance/reporting use cases) are in place. Batch 03 already moved `cardre/engine/binning/` → `domain/binning/` and `cardre/workflows/scorecard.py` → `domain/plans/scorecard_pathway.py` (D19), and deleted those old packages. Existing: `cardre/api/app.py:create_app(container)` (from 01), `api/dependencies.py` (use-case deps from 01), `api/routes/health.py` + `projects.py` (from 01), `api/schemas.py` (subset from 01), old `api/routes/plans.py`, `runs.py`, `evidence.py`, `artifacts.py`, `branches.py`, `comparisons.py`, `champion.py`, `manual_binning.py`, `exports.py`, `reports.py`, `node_types.py`, `_project_scope.py`, `_run_mappings.py`. Frontend: `client.ts` (openapi-fetch + transport), `useProjectWorkspace.ts`, components. Dormant old code: `cardre/store/`, `cardre/config.py`, `cardre/artifacts.py`, `cardre/capabilities.py`. `tests/test_canonical_contract.py::test_forbidden_imports_outside_adapters` is `xfail` (from Batch 01). `.importlinter` is permissive (`ignore_unmatched`).

## 3. Why the batch exists

This is the consumer-facing layer. After this batch, the full API works through the new architecture and the frontend is regenerated against it.

## 4. Current relevant architecture

Old routes construct repositories, do ownership checks (`_project_scope.py`), receive `ProjectStore` via `Depends(get_project_store)`. Batch 01 removed `get_project_store`; only health+projects routes are live. Other routes either don't exist (new) or are the old ones (not registered). `_run_mappings.py` maps domain to Pydantic responses. Frontend `client.ts` sends `X-Project-Id` header; `useProjectWorkspace` polls runs.

## 5. Target architecture after the batch

- `api/routes/plans.py`, `runs.py`, `evidence.py`, `artifacts.py`, `node_types.py`, `exports.py`, `reports.py` — thin handlers calling use cases via `Depends(get_<use_case>)`. No repo construction, no ownership checks (use cases enforce `project_id` scoping), no `store`.
- `api/routes/governance.py` — combined router for branches + comparisons + champion + manual-binning; registered only when `settings.governance_enabled`.
- `api/routes/_project_scope.py` — deleted (ownership in use cases).
- `api/routes/_run_mappings.py` — rewritten as `api/mappers.py` (domain → Pydantic response mappers, pure functions).
- `api/schemas.py` — full set per 05-api-and-frontend-boundary.md.
- `api/dependencies.py` — all use-case deps (`get_create_plan`, `get_submit_run`, `get_cancel_run`, etc.).
- `api/app.py:create_app(container)` — registers all routers; governance router conditional on `settings.governance_enabled`.
- `frontend/src/api/openapi.json` + `schema.d.ts` — regenerated.
- `frontend/src/api/client.ts` — `projectHeaders` removed; `api.forProject(projectId)` uses path param `{project_id}` only; add `cancelRun` method.
- `frontend/src/api/errorCodes.ts` — add new codes (`RUN_CANCELLED`, `OUTPUT_CONTRACT_VIOLATION`, `ARTIFACT_STAGING_FAILED`, `ARTIFACT_PUBLISH_FAILED`); `test_error_code_sync.py` enforces.
- `frontend/src/hooks/useProjectWorkspace.ts` — update query paths to new endpoints; add `cancelRun` mutation; terminal statuses include `cancelled`; polling unchanged.
- `frontend/src/components/*` — update to new response shapes (minimal if shapes preserved).
- `tests/test_api_*.py` (20 files) — rewritten against `build_app` TestClient; assert new shapes, error codes, governance 403.

## 6. Exact scope

**API routes + frontend:**
- Write/rewrite all route files listed in §5.
- Write full `api/schemas.py`.
- Write `api/mappers.py` (from `_run_mappings.py`).
- Delete `api/routes/_project_scope.py`.
- Update `api/dependencies.py` with all use-case deps.
- Update `api/app.py:create_app` to register all routers + conditional governance.
- Regenerate OpenAPI.
- Update `frontend/src/api/client.ts` (remove `projectHeaders`, add `cancelRun`).
- Update `frontend/src/api/errorCodes.ts`.
- Update `frontend/src/hooks/useProjectWorkspace.ts`.
- Update `frontend/src/components/*` as needed.
- Rewrite `tests/test_api_*.py`.

**Delete old architecture + finalize enforcement (absorbed from old Batch 09):**
- Grep for any remaining imports of `cardre.store`, `cardre.config`, `cardre.artifacts`, `cardre.capabilities`, `cardre.engine`, `cardre.workflows`, `cardre._evidence`, `ProjectStore`, `CardreConfig`, `ArtifactEvidenceReader`, old repo classes. Fix any remaining imports (move used logic to new packages). Note: `cardre/engine/` and `cardre/workflows/` were already moved/deleted in Batch 03 per D19 — verify they're gone.
- Delete `cardre/store/` (entire package), `cardre/config.py`, `cardre/artifacts.py`, `cardre/capabilities.py`, `cardre/_evidence/` (if empty), `cardre/services/__init__.py` (if empty).
- Delete dead `_lifecycle` forwarders on `BinDefinition` if present (grep — D20 confirmed already gone, but verify).
- Tighten `.importlinter`: set `ignore_unmatched: false`; add `forbidden` sections banning imports of deleted packages from anywhere; ban `cardre.adapters` imports from `cardre.application`/`cardre.api`/`cardre.nodes`; ban `cardre.api` imports from `cardre.adapters`/`cardre.nodes`/`cardre.bootstrap`.
- Un-xfail `tests/test_canonical_contract.py::test_forbidden_imports_outside_adapters` — remove `@pytest.mark.xfail(...)`. Update banned-identifier list to final state.
- Verify `tests/test_store_schema_no_queryable_json.py` reflects new schema.
- Write `tests/acceptance/test_launch_pathway.py` (rewrite of `test_launch_pathway.py` + `test_api_scorecard_launch_pathway.py` using `TestClient(build_app()[0])`; covers the 20 acceptance items from 08-acceptance-and-test-strategy.md).
- Delete old `test_launch_pathway.py`, `test_api_scorecard_launch_pathway.py` (replaced).
- Update `docs/README.md`: remove "Architecture Rewrite (in progress)" section; the rewrite is complete.

## 7. Files to inspect first

- `cardre/api/routes/plans.py`, `runs.py`, `evidence.py`, `artifacts.py`, `branches.py`, `comparisons.py`, `champion.py`, `manual_binning.py`, `exports.py`, `reports.py`, `node_types.py` (old routes — port logic to use cases).
- `cardre/api/routes/_project_scope.py` (ownership — delete).
- `cardre/api/routes/_run_mappings.py` (mappers — port to `api/mappers.py`).
- `cardre/api/schemas.py` (current schemas — redesign per 05).
- `cardre/api/dependencies.py` (from 01 — extend).
- `cardre/api/app.py` (from 01 — extend router registration).
- `frontend/src/api/client.ts` (transport — preserve, update `forProject`).
- `frontend/src/hooks/useProjectWorkspace.ts` (queries — update paths).
- `frontend/src/components/ProjectView.tsx`, `RunDetailsPanel.tsx`, `VersionPanel.tsx`, `PlanSidebar.tsx` (response shapes).
- `tests/test_api_*.py` (rewrite).
- Grep results for old imports (run before deleting): `rg "from cardre\.store|from cardre\.config|from cardre\.artifacts|from cardre\.capabilities|from cardre\.engine|from cardre\.workflows|from cardre\._evidence|import ProjectStore|CardreConfig|ArtifactEvidenceReader" cardre/`. (Note: `cardre/engine/` + `cardre/workflows/` were moved/deleted in Batch 03 — verify zero references.)
- `.importlinter` (from Batch 01 — tighten).
- `tests/test_canonical_contract.py` (from Batch 01 — tighten).
- `tests/test_launch_pathway.py`, `test_api_scorecard_launch_pathway.py` (rewrite basis).
- `cardre/_evidence/__init__.py` (empty?).

## 8. Files likely to change

- `cardre/api/routes/plans.py`, `runs.py`, `evidence.py`, `artifacts.py`, `node_types.py`, `exports.py`, `reports.py`, `governance.py` (new — replaces branches/comparisons/champion/manual_binning).
- `cardre/api/schemas.py` (full rewrite).
- `cardre/api/dependencies.py` (extend).
- `cardre/api/app.py` (extend).
- `cardre/api/mappers.py` (new — from `_run_mappings.py`).
- `frontend/src/api/openapi.json`, `schema.d.ts` (regenerated).
- `frontend/src/api/client.ts` (update `forProject`, add `cancelRun`).
- `frontend/src/api/errorCodes.ts` (add codes).
- `frontend/src/hooks/useProjectWorkspace.ts` (update).
- `frontend/src/components/*` (update if shapes changed).
- `tests/test_api_*.py` (rewrite).
- `tests/test_error_code_sync.py` (update for new codes).
- `.importlinter` (tighten — strict, `ignore_unmatched: false`, `forbidden` sections).
- `tests/test_canonical_contract.py` (un-xfail `test_forbidden_imports_outside_adapters`, update ban list).
- `tests/test_store_schema_no_queryable_json.py` (verify new schema tables).
- `tests/acceptance/test_launch_pathway.py` (new).
- `docs/README.md` (remove "in progress" section).

## 9. Files likely to create

- `cardre/api/routes/governance.py`.
- `cardre/api/mappers.py`.
- `tests/acceptance/__init__.py`, `test_launch_pathway.py`.

## 10. Files likely to delete

- `cardre/api/routes/_project_scope.py`.
- `cardre/api/routes/_run_mappings.py` (moved to `mappers.py`).
- Old `cardre/api/routes/branches.py`, `comparisons.py`, `champion.py`, `manual_binning.py` (folded into `governance.py`).
- `cardre/store/` (entire package).
- `cardre/config.py`.
- `cardre/artifacts.py`.
- `cardre/capabilities.py`.
- `cardre/_evidence/` (if empty).
- `cardre/services/__init__.py` (if empty).
- Old `tests/test_launch_pathway.py`, `tests/test_api_scorecard_launch_pathway.py` (replaced by `tests/acceptance/test_launch_pathway.py`).

## 11. Required implementation sequence

1. Write `api/schemas.py` full set per 05-api-and-frontend-boundary.md (all request/response models). Preserve field names where possible to minimize frontend churn; rename where the proposal requires (e.g. `RunResponse` adds `cancel_requested`).
2. Write `api/mappers.py` — pure functions mapping domain dataclasses to Pydantic responses. Port from `_run_mappings.py`.
3. Extend `api/dependencies.py` with `get_<use_case>` for every use case (CreatePlan, GetPlan, ListPlans, GetPlanVersion, ListPlanVersions, UpdatePlanVersion, CommitPlanVersion, ApplyManualBinningEdit, SubmitRun, ExecuteRun (internal, not a route dep), CancelRun, GetRun, ListRuns, GetRunSteps, GetRunEvidence, ExplainStaleness, CreateBranch, CreateComparison, RefreshComparison, AssignChampion, GenerateReport, ExportAuditPack, PreviewManualBinning, ListManualBinningReviews, GetManualBinningReview, UpdateManualBinningReview, ListNodeTypes, ListExports, ListReports, ListRunReports, GetArtifact). Each pulls from `request.app.state.container`.
4. Write `api/routes/plans.py` — `GET /plans`, `POST /plans`, `GET /plans/{plan_id}`, `GET /plans/{plan_id}/versions`, `GET /plan-versions/{version_id}`, `PATCH /plan-versions/{version_id}`, `POST /plan-versions/{version_id}/commit`. Thin handlers: call use case, map response.
5. Write `api/routes/runs.py` — `POST /runs`, `GET /runs`, `GET /runs/{run_id}`, `GET /runs/{run_id}/steps`, `GET /runs/{run_id}/evidence`, `POST /runs/{run_id}/cancel`.
6. Write `api/routes/evidence.py` — `GET /steps/{step_id}/evidence?plan_version_id=&branch_id=`.
7. Write `api/routes/artifacts.py` — `GET /artifacts/{artifact_id}`.
8. Write `api/routes/node_types.py` — `GET /node-types`.
9. Write `api/routes/exports.py` — `GET /exports`.
10. Write `api/routes/reports.py` — `GET /reports`, `GET /runs/{run_id}/reports`.
11. Write `api/routes/governance.py` — all branch/comparison/champion/manual-binning endpoints. `router = APIRouter(prefix="/projects/{project_id}/governance", tags=["governance"], dependencies=[Depends(require_governance)])`.
12. Update `api/app.py:create_app(container)` — register all routers; `if container.settings.governance_enabled: app.include_router(governance.router)`.
13. Delete `api/routes/_project_scope.py`, `_run_mappings.py`, old `branches.py`, `comparisons.py`, `champion.py`, `manual_binning.py`.
14. Regenerate OpenAPI: `python3 scripts/generate-openapi-types.py`.
15. Update `frontend/src/api/client.ts`: remove `projectHeaders`; `api.forProject(projectId)` returns object with methods calling `paths["/projects/{project_id}/..."]` with `params: { path: { project_id } }`. Add `cancelRun: (runId) => scoped.POST("/projects/{project_id}/runs/{run_id}/cancel", ...)`.
16. Update `frontend/src/api/errorCodes.ts`: add new codes. Run `test_error_code_sync.py`.
17. Update `frontend/src/hooks/useProjectWorkspace.ts`: update query keys + fetchers to new paths; add `cancelRunMutation`; terminal statuses `{succeeded, failed, cancelled, interrupted}`.
18. Update `frontend/src/components/*` if response shapes changed.
19. Rewrite `tests/test_api_*.py` against `TestClient(build_app()[0])`; assert shapes, error codes, governance 403.
20. Run `make preflight` + frontend tests.

**Delete old architecture + finalize enforcement (absorbed from old Batch 09):**

21. `rg "from cardre\.store|from cardre\.config|from cardre\.artifacts|from cardre\.capabilities|from cardre\.engine|from cardre\.workflows|from cardre\._evidence|import ProjectStore|CardreConfig|ArtifactEvidenceReader" cardre/` — list all remaining references. Fix each (move used logic or delete the importer). Note: `cardre/engine/` + `cardre/workflows/` were moved/deleted in Batch 03 (D19) — verify zero references remain.
22. Delete `cardre/store/`, `cardre/config.py`, `cardre/artifacts.py`, `cardre/capabilities.py`, `cardre/_evidence/` (if empty), `cardre/services/__init__.py` (if empty).
23. Grep for dead `_lifecycle` forwarders on `BinDefinition`: `rg "_lifecycle" cardre/`. D20 confirmed already gone — verify and proceed.
24. Tighten `.importlinter`: set `ignore_unmatched: false`; add `forbidden` sections banning imports of deleted packages from anywhere; ban `cardre.adapters` imports from `cardre.application`/`cardre.api`/`cardre.nodes`; ban `cardre.api` imports from `cardre.adapters`/`cardre.nodes`/`cardre.bootstrap`.
25. Un-xfail `tests/test_canonical_contract.py::test_forbidden_imports_outside_adapters` — remove `@pytest.mark.xfail(...)`. Update banned-identifier list to final state.
26. Verify `tests/test_store_schema_no_queryable_json.py` reflects new schema (table names, `storage_key` column).
27. Write `tests/acceptance/test_launch_pathway.py` — rewrite of `test_launch_pathway.py` + `test_api_scorecard_launch_pathway.py` using `TestClient(build_app()[0])`. Covers the 20 acceptance items from 08-acceptance-and-test-strategy.md: create project, import dataset, profile, create plan, construct 13-step build graph, commit, submit run, execute, produce artifacts, binning+WOE, logistic, score scaling, apply model, validation metrics, export scoring code, audit pack, replay, scoring parity, artifact hashes (recompute + compare DB), manifest consistency (recompute hash + compare). Use a fixture dataset (generated CSV or `tests/fixtures/german_credit.csv` if present).
28. Delete old `tests/test_launch_pathway.py`, `tests/test_api_scorecard_launch_pathway.py` (replaced).
29. Update `docs/README.md`: remove "Architecture Rewrite (in progress)" section; the rewrite is complete.
30. Run `make preflight` + `make arch-check` (strict now) + full test suite + frontend tests + tauri fmt/clippy.

## 12. Interfaces and invariants

- Routes are thin: parse request → call use case → map response. No repo construction, no ownership checks, no transactions.
- `project_id` from path param; no headers.
- Governance router registered only when `settings.governance_enabled`.
- OpenAPI regenerated; `check-api-contracts` CI job passes.
- Frontend `errorCodes.ts` synced with `ErrorCode` (enforced by `test_error_code_sync.py`).

## 13. Behaviour to preserve

- All endpoint response semantics (list/get/create/commit/run/cancel).
- Governance 403 when disabled.
- Error envelope `{detail:{code,message,context}}`.
- `useProjectWorkspace` polling (1s, terminal stop).
- `test_api_*.py` behavioural assertions (rewrite for new client).

## 14. Intentional breaking changes

- `X-Project-Id`/`X-Project-Path` headers removed.
- Governance routes under `/governance/` prefix (was flat).
- `POST /comparisons/{id}/refresh` explicit (was implicit).
- `POST /champion/assign` explicit.
- `POST /runs/{run_id}/cancel` new.
- `RunResponse` adds `cancel_requested` field.

## 15. Tests to add or update

- Rewrite `tests/test_api_*.py` (20 files) against `build_app` TestClient.
- `tests/test_error_code_sync.py` updated for new codes.
- `frontend/src/api/__tests__/client.test.ts` updated (no `projectHeaders`).
- `frontend/src/hooks/__tests__/useProjectWorkspace.test.tsx` updated (new paths, `cancelRun`, terminal statuses).
- `tests/acceptance/test_launch_pathway.py` (new — 20 acceptance items).
- `tests/test_canonical_contract.py::test_forbidden_imports_outside_adapters` (un-xfail, strict).
- `.importlinter` (strict).
- Delete old `tests/test_launch_pathway.py`, `tests/test_api_scorecard_launch_pathway.py`.

## 16. Commands to run

```bash
. .venv/bin/activate
ruff check --fix
python3 -m importlinter --config .importlinter   # strict now
make arch-check
make preflight   # includes openapi regen + drift check
python3 -m pytest tests/test_api_*.py tests/test_error_code_sync.py -q
python3 -m pytest tests/acceptance/test_launch_pathway.py -q
python3 -m pytest tests/test_scoring_export_parity.py tests/test_logistic_regression_known_input.py tests/test_score_scaling_known_input.py tests/test_golden_fixtures_roundtrip.py tests/test_golden_report_bundle.py tests/test_run_audit_integrity.py -q
python3 -m pytest tests/ -q
cd frontend && npm test && npx tsc --noEmit && npm run build
cd frontend/src-tauri && cargo fmt --check && cargo clippy --all-targets -- -D warnings
```

## 17. Acceptance criteria

- All endpoints work via `TestClient(build_app()[0])`.
- Governance 403 when disabled; governance routes registered when enabled.
- `test_error_code_sync.py` passes (frontend ↔ backend codes).
- OpenAPI regenerated; `git diff --exit-code` clean.
- Frontend `npm test` passes; `tsc --noEmit` passes; `npm run build` passes.
- `make arch-check` passes (strict, no `ignore_unmatched`).
- `make preflight` passes (coverage ≥60%).
- No `ProjectStore` in `api/`.
- `rg "ProjectStore|CardreConfig|ArtifactEvidenceReader|cardre\.store|cardre\.config|cardre\.artifacts|cardre\.capabilities|cardre\.engine|cardre\.workflows|cardre\._evidence" cardre/` returns zero matches.
- `tests/test_canonical_contract.py::test_forbidden_imports_outside_adapters` passes (strict, not xfail).
- `tests/acceptance/test_launch_pathway.py` passes (all 20 items).
- All parity tests pass.
- Tauri fmt + clippy pass.
- `docs/README.md` no longer references "in progress".
- Old packages deleted; `cardre/` contains only: `domain/`, `application/`, `nodes/`, `adapters/`, `api/`, `bootstrap/` (+ `modeling/` if kept as a sub-package of `nodes/` or `adapters/`).

## 18. Architecture rules

- `api/**` imports only `application/`, `domain/`, `api/*`, FastAPI, Pydantic.
- No repo construction in routes.
- No `os.environ` in `api/`.
- No `X-Project-Id`/`X-Project-Path` header strings.
- All rules from Batches 01–06 now strictly enforced.
- No deleted package may be imported.
- `sqlite3` only in `adapters/sqlite/`.
- `os.environ` only in `bootstrap/settings.py`.
- `ProjectStore`, `CardreConfig`, `ArtifactEvidenceReader` banned everywhere.

## 19. Prohibited shortcuts

- Do not re-introduce ownership checks in routes.
- Do not construct repositories in routes.
- Do not skip OpenAPI regeneration.
- Do not skip the governance 403 test.
- Do not leave `frontend/src/api/errorCodes.ts` out of sync.
- Do not leave any old package as an empty re-export shim.
- Do not keep `xfail` on the forbidden-symbol test.
- Do not keep `ignore_unmatched` in `.importlinter`.
- Do not skip the product acceptance pathway.
- Verify `cardre/engine/` + `cardre/workflows/` are already gone (Batch 03 moved them per D19); if any residue, delete it.

## 20. Explicit out-of-scope work

- New features (beyond preserving validated behaviour).
- Artifact gc implementation (document as follow-up).
- Schema versioning/migration runner (post-launch).
- Deferred node graduation (post-launch roadmap).

## 21. Expected final report format

1. Endpoint list (all live).
2. Governance 403 + enabled test results.
3. OpenAPI regen diff summary.
4. `test_error_code_sync.py` result.
5. Frontend test + typecheck + build results.
6. Grep results confirming zero old-package references.
7. `importlinter` strict pass.
8. `test_forbidden_imports_outside_adapters` strict pass.
9. Product acceptance pathway result (20 items pass/fail).
10. Parity test results.
11. `make preflight` + `make arch-check` + tauri summary.
12. Final `cardre/` package listing (only the 6 target packages).
13. Files created/deleted.

## Identity

- Sequence: 07
- Title: API Routes + Frontend Regeneration + Delete Old Architecture + Finalize Enforcement
- Architectural objective: full API through new architecture; frontend regenerated; old architecture deleted; strict enforcement; acceptance pathway green
- Reason for position: last batch; cleanup is small once API is live; merges old API batch with old cleanup batch to save a cycle
- Difficulty: high — many routes + frontend + test rewrites + deletion + enforcement tightening + acceptance test

## Scope summary

- Created: `api/routes/governance.py`, `api/mappers.py`, full `api/schemas.py`, `tests/acceptance/test_launch_pathway.py`.
- Changed: all `api/routes/*`, `api/dependencies.py`, `api/app.py`, `frontend/src/api/client.ts`, `errorCodes.ts`, `useProjectWorkspace.ts`, components, `tests/test_api_*`, `test_error_code_sync.py`, `.importlinter`, `tests/test_canonical_contract.py`, `tests/test_store_schema_no_queryable_json.py`, `docs/README.md`.
- Deleted: `api/routes/_project_scope.py`, `_run_mappings.py`, old branches/comparisons/champion/manual_binning routes, `cardre/store/`, `cardre/config.py`, `cardre/artifacts.py`, `cardre/capabilities.py`, `cardre/_evidence/` (if empty), `cardre/services/__init__.py` (if empty), old `test_launch_pathway.py` + `test_api_scorecard_launch_pathway.py`.
- Behaviour preserved: all endpoint semantics, governance 403, polling, all parity + acceptance.
- Behaviour changed: headers removed, governance prefix, cancel endpoint, response shapes (minimal), enforcement strict.
- Exclusions: new features, gc, migrations, deferred graduation.

## Design decisions

- D11 (no headers), D12 (generated client), D16 (governance opt-in), D1 (clean cut complete), D13 (strict enforcement), D17 (coverage maintained), D2 (preserve parity).

## Tests

See §15.

## Acceptance criteria

See §17.

## Risks

- R9 (openapi drift), R15 (tauri sidecar — main.rs unchanged), R5/R6 (enforcement too strict/loose), R2/R3 (parity after final deletion), R24 (canonical contract ban list conflicts).

## Agent boundaries

Do not modify: `cardre/application/`, `cardre/nodes/**`, `cardre/adapters/**`, `cardre/bootstrap/**`, `cardre/domain/` (settled in previous batches — `domain/binning/` and `domain/plans/scorecard_pathway.py` moved in Batch 03) — all settled in previous batches. This batch only rewrites `api/**`, updates frontend, deletes old code, tightens enforcement, writes the acceptance test.

## Dependencies

- Required earlier: Batch 06 (all use cases).
- Optional parallel: none (routes need all use cases; cleanup needs routes done).
- Open PRs: none.

## Estimated reasoning difficulty

high.