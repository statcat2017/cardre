# 05 — API and Frontend Boundary

## Proposed endpoints

Clean redesign. No `X-Project-Path`. Project identity via path param `{project_id}` + `X-Project-Id` header (kept for the FastAPI dependency resolver; both must match — or just path param; header is redundant once the dependency resolves from path).

Decision: **drop `X-Project-Id` header too** — `{project_id}` path param is authoritative. The dependency resolves the project from the path param via `ProjectRegistryPort`. This removes the dual-header confusion. (Deviation from proposal: header removed entirely, not just `X-Project-Path`.)

| Method | Path | Handler | Request | Response | Errors | Idempotency | Frontend consumer | Polling |
|--------|------|---------|---------|----------|--------|------------|-------------------|---------|
| GET | `/health` | `GetHealth` | — | `HealthResponse` | — | — | startup | no |
| POST | `/projects` | `CreateProject` | `ProjectCreateRequest{name, path}` | `201 ProjectResponse` | `INVALID_PROJECT_PATH`, `STORE_ALREADY_EXISTS` | creating same path twice → `STORE_ALREADY_EXISTS` | `WelcomeScreen` create form | no |
| GET | `/projects` | `ListProjects` | — | `200 ProjectListResponse` | — | — | `WelcomeScreen` list | no |
| GET | `/projects/{project_id}` | `GetProject` | — | `200 ProjectResponse` | `PROJECT_NOT_FOUND` | — | `ProjectView` header | no |
| POST | `/projects/{project_id}/plans` | `CreatePlan` | `PlanCreateRequest{name}` | `201 PlanResponse` | `PROJECT_NOT_FOUND` | — | `PlanSidebar` create | no |
| GET | `/projects/{project_id}/plans` | `ListPlans` | — | `200 PlanListResponse` | — | — | `PlanSidebar` list | no |
| GET | `/projects/{project_id}/plans/{plan_id}` | `GetPlan` | — | `200 PlanResponse` | `PLAN_NOT_FOUND` | — | (future) | no |
| GET | `/projects/{project_id}/plans/{plan_id}/versions` | `ListPlanVersions` | — | `200 PlanVersionListResponse` | `PLAN_NOT_FOUND` | — | `VersionPanel` | no |
| GET | `/projects/{project_id}/plan-versions/{version_id}` | `GetPlanVersion` | — | `200 PlanVersionDetailResponse` (includes steps) | `PLAN_VERSION_NOT_FOUND` | — | (future plan editor) | no |
| PATCH | `/projects/{project_id}/plan-versions/{version_id}` | `UpdatePlanVersion` | `PlanVersionUpdate{description}` | `200 PlanVersionResponse` | `PLAN_VERSION_NOT_FOUND`, `PLAN_VERSION_IMMUTABLE` | — | (future) | no |
| POST | `/projects/{project_id}/plan-versions/{version_id}/commit` | `CommitPlanVersion` | — | `200 PlanVersionResponse` | `PLAN_VERSION_NOT_FOUND`, `PLAN_VERSION_ALREADY_COMMITTED`, `GRAPH_VALIDATION_ERROR` | — | `VersionPanel` commit button | no |
| POST | `/projects/{project_id}/runs` | `SubmitRun` | `RunCreateRequest{plan_version_id, run_scope?, branch_id?, force?}` (sync defaults false) | `201 RunResponse` (status running) | `PLAN_VERSION_NOT_FOUND`, `PLAN_VERSION_NOT_COMMITTED`, `GOVERNANCE_NOT_ENABLED`, `CONCURRENT_RUN`, `EVIDENCE_POLICY_CURRENT` | re-submit same version while running → `CONCURRENT_RUN` (unless force) | `VersionPanel` run button | yes — frontend polls `GET /runs/{run_id}` while non-terminal |
| GET | `/projects/{project_id}/runs` | `ListRuns` | — | `200 RunListResponse` | — | — | `PlanSidebar` runs list | yes — polls while any run active |
| GET | `/projects/{project_id}/runs/{run_id}` | `GetRun` | — | `200 RunResponse` | `RUN_NOT_FOUND` | — | `RunDetailsPanel` | yes — polls while non-terminal |
| GET | `/projects/{project_id}/runs/{run_id}/steps` | `GetRunSteps` | — | `200 list[RunStepResponse]` | `RUN_NOT_FOUND` | — | `RunDetailsPanel` steps | yes |
| GET | `/projects/{project_id}/runs/{run_id}/evidence` | `GetRunEvidence` | — | `200 list[RunEvidenceEdgeResponse]` | `RUN_NOT_FOUND` | — | `RunDetailsPanel` evidence | yes |
| POST | `/projects/{project_id}/runs/{run_id}/cancel` | `CancelRun` | — | `200 RunResponse` (status still running, `cancel_requested=true`) | `RUN_NOT_FOUND`, `RUN_NOT_RUNNING` | — | (future) cancel button | no |
| GET | `/projects/{project_id}/steps/{step_id}/evidence` | `ExplainStaleness` | `?plan_version_id=...&branch_id=...` | `200 StalenessExplanationResponse` | `STEP_NOT_FOUND`, `PLAN_VERSION_NOT_FOUND` | — | (future staleness UI) | no |
| GET | `/projects/{project_id}/artifacts/{artifact_id}` | `GetArtifact` | — | `200 ArtifactResponse` | `ARTIFACT_NOT_FOUND` | — | (future artifact viewer) | no |
| GET | `/projects/{project_id}/node-types` | `ListNodeTypes` | — | `200 NodeTypeListResponse` | — | — | (future node palette) | no |
| GET | `/projects/{project_id}/exports` | `ListExports` | — | `200 ExportListResponse` | — | — | (future export panel) | no |
| GET | `/projects/{project_id}/reports` | `ListReports` | — | `200 ReportListResponse` | — | — | (future report panel) | no |
| GET | `/projects/{project_id}/runs/{run_id}/reports` | `ListRunReports` | — | `200 ReportListResponse` | `RUN_NOT_FOUND` | — | `RunDetailsPanel` reports | no |
| POST | `/projects/{project_id}/governance/branches` | `CreateBranch` | `BranchCreateRequest{...}` | `201 BranchResponse` | `GOVERNANCE_NOT_ENABLED`, `BRANCH_VALIDATION_ERROR`, `PLAN_NOT_FOUND`, `PLAN_VERSION_NOT_FOUND` | — | (future BranchView) | no |
| GET | `/projects/{project_id}/governance/branches` | `ListBranches` | `?plan_id=&status=` | `200 BranchListResponse` | — | — | (future) | no |
| GET | `/projects/{project_id}/governance/branches/{branch_id}` | `GetBranch` | — | `200 BranchResponse` | `BRANCH_NOT_FOUND` | — | (future) | no |
| POST | `/projects/{project_id}/governance/comparisons` | `CreateComparison` | `ComparisonCreateRequest{...}` | `201 ComparisonResponse` | `GOVERNANCE_NOT_ENABLED`, `BRANCH_NOT_FOUND` | — | (future) | no |
| POST | `/projects/{project_id}/governance/comparisons/{comparison_id}/refresh` | `RefreshComparison` | — | `200 ComparisonResponse` | `COMPARISON_NOT_FOUND`, `BRANCH_NOT_READY` | — | (future) | no |
| GET | `/projects/{project_id}/governance/comparisons` | `ListComparisons` | — | `200 ComparisonListResponse` | — | — | (future) | no |
| GET | `/projects/{project_id}/governance/comparisons/{comparison_id}` | `GetComparison` | — | `200 ComparisonResponse` | `COMPARISON_NOT_FOUND` | — | (future) | no |
| GET | `/projects/{project_id}/governance/champion` | `GetChampion` | `?plan_id=&scope_type=&scope_key=` | `200 ChampionResponse` | — | — | (future) | no |
| POST | `/projects/{project_id}/governance/champion/assign` | `AssignChampion` | `ChampionAssignRequest{...}` | `200 ChampionAssignmentResponse` | `GOVERNANCE_NOT_ENABLED`, `BRANCH_NOT_FOUND`, `STALE_SNAPSHOT` | — | (future) | no |
| GET | `/projects/{project_id}/governance/manual-binning/reviews` | `ListManualBinningReviews` | `?plan_version_id=&step_id=` | `200 list[ManualBinningReviewResponse]` | — | — | (future ManualBinningEditor) | no |
| GET | `/projects/{project_id}/governance/manual-binning/reviews/{review_id}` | `GetManualBinningReview` | — | `200 ManualBinningReviewResponse` | `REVIEW_NOT_FOUND` | — | (future) | no |
| PATCH | `/projects/{project_id}/governance/manual-binning/reviews/{review_id}` | `UpdateManualBinningReview` | `ManualBinningReviewUpdate{status, reviewer_notes}` | `200 ManualBinningReviewResponse` | `REVIEW_NOT_FOUND` | — | (future) | no |
| POST | `/projects/{project_id}/governance/manual-binning/edit` | `ApplyManualBinningEdit` | `ManualBinningEditRequest{...}` | `201 ManualBinningEditResponse` | `GOVERNANCE_NOT_ENABLED`, `PLAN_VERSION_NOT_FOUND`, `PLAN_VERSION_NOT_COMMITTED`, `MANUAL_BINNING_INVALID` | — | (future) | no |
| POST | `/projects/{project_id}/governance/manual-binning/preview` | `PreviewManualBinning` | `ManualBinningPreviewRequest{variable_data}` | `200 ManualBinningPreviewResponse` | — | — | (future) | no |

Governance routes registered only when `settings.governance_enabled` (preserved behaviour). Routers grouped: `governance` router contains branches + comparisons + champion + manual-binning.

## Application handler mapping

Every route is a thin async function:
```python
@router.post("/runs", response_model=RunResponse, status_code=201)
async def create_run(
    project_id: str,
    body: RunCreateRequest,
    submit_run: SubmitRun = Depends(get_submit_run),
) -> RunResponse:
    run = submit_run(SubmitRunCommand(
        project_id=project_id,
        plan_version_id=body.plan_version_id,
        run_scope=body.run_scope or "full_plan",
        branch_id=body.branch_id,
        force=body.force or False,
    ))
    return run_to_response(run)
```

`Depends(get_submit_run)` resolves from `request.app.state.container` — a `Container` built once in bootstrap. No repo construction in routes. No ownership checks in routes (use cases enforce `project_id` scoping via the UoW). No transactions in routes.

## Error mapping

Preserved from `cardre/api/errors.py` + `cardre/domain/errors.py`. `CardreError` → `cardre_error_handler` → `{detail:{code, message, context}}`. `CardreApiError` → `cardre_api_error_handler`. HTTP status from `CardreError.status_code`.

New codes added per 02-domain-and-use-cases.md. `test_error_code_sync.py` keeps frontend `errorCodes.ts` in sync.

## Project identity

- Path param `{project_id}` is authoritative.
- `get_project_dependency(project_id) -> ProjectRoot` resolves via `Container.project_registry.resolve_root(project_id)` → raises `PROJECT_NOT_FOUND` (404) if missing.
- Use cases take `project_id` and use `UnitOfWorkFactory.for_project(project_id)` to open the UoW. The factory resolves root via registry internally.
- **No `X-Project-Id` header, no `X-Project-Path` header.** Frontend sends `{project_id}` in path only.

## Generated client strategy

- `scripts/generate-openapi-types.py` (preserved) regenerates `frontend/src/api/openapi.json` from `cardre.api.app.app.openapi()` and `frontend/src/api/schema.d.ts` via `openapi-typescript`.
- `frontend/src/api/client.ts` (preserved transport: `ApiError`, `fetchResponse`, `fetchJson`, `typedTransport`, `requireData`, `getBaseUrl`) uses `openapi-fetch` with generated `paths`/`components`.
- `projectHeaders(projectId)` removed — project id is in the path.
- `api.forProject(projectId)` returns an object whose methods call `paths['/projects/{project_id}/...']` with `params: { path: { project_id } }`.
- Regenerate once after Batch 01 (API skeleton) and again after Batch 07 (full API). `check-api-contracts` CI job (preserved) catches drift.

## Frontend migration areas

- `frontend/src/api/client.ts` — remove `projectHeaders`, `X-Project-Id`; update `api.forProject` to use path param only. Regenerate `schema.d.ts`.
- `frontend/src/api/errorCodes.ts` — add new codes (`RUN_CANCELLED`, `OUTPUT_CONTRACT_VIOLATION`, etc.); `test_error_code_sync.py` enforces.
- `frontend/src/hooks/useProjectWorkspace.ts` — update query paths/methods to new endpoints; add `cancelRun` mutation; polling unchanged (1s interval, terminal stop).
- `frontend/src/components/ProjectView.tsx`, `PlanSidebar.tsx`, `VersionPanel.tsx`, `RunDetailsPanel.tsx`, `WelcomeScreen.tsx` — update to new response shapes (minimal changes if response shapes are kept similar).
- `frontend/src/App.tsx` — `projectId` state unchanged.
- `frontend/src-tauri/src/main.rs` — unchanged (sidecar lifecycle already correct post-PR3).
- `tests/test_error_code_sync.py` — preserved, updated for new codes.

## When to regenerate OpenAPI

- After Batch 02 (API skeleton + new schemas): regenerate to lock the new contract.
- After Batch 07 (full API + all endpoints): regenerate again.
- `make preflight` regenerates + `git diff --exit-code` catches drift (preserved).

## Deviations from proposal

- **Removed `X-Project-Id` header entirely** — proposal said "remove `X-Project-Path`"; we go further and remove both, using only the path param. Cleaner; no dual-source-of-truth.
- **Governance routes under `/governance/` prefix** — proposal listed branches/comparisons/champion under `/projects/{project_id}/...` flat; we group them under `governance/` for clarity and to match the governance-gated router registration.
- **Added `POST /comparisons/{id}/refresh`** — proposal implied refresh via POST to the comparison; explicit endpoint is clearer.
- **Added `POST /champion/assign`** — proposal said "assign champion"; explicit endpoint.
- **`POST /runs/{run_id}/cancel`** — new per D14.