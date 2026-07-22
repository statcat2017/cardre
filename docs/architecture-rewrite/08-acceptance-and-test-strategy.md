# 08 — Acceptance and Test Strategy

## Architecture tests

### Import-boundary tests (introduced in Batch 01, tightened in Batch 07)

- **`importlinter`** (new `dev` dep) configured in `.importlinter`:
  - Layer `domain` imports only stdlib.
  - Layer `application` imports only `domain`, `application.ports`.
  - Layer `nodes` imports only `domain`, `nodes.contracts`, `nodes.parameters`, third-party numerical.
  - Layer `adapters` imports only `application.ports`, `domain`.
  - Layer `api` imports only `application`, `domain`, `api.*`.
  - Layer `bootstrap` imports everything.
- Run via `lint` target + CI `lint` job. Blocking from Batch 01.

### Forbidden-symbol tests (extend `tests/test_canonical_contract.py` in Batches 01 + 09)

AST-walk `cardre/**/*.py` banning:
- `ProjectStore` (outside `adapters/sqlite/` during migration; globally after Batch 07).
- `context.store` / `.store` attribute access on `NodeContext`.
- `store.root` (path access on a store object).
- `CardreConfig.from_env` / `from_env()` outside `bootstrap/settings.py`.
- `os.environ` / `os.getenv` outside `bootstrap/settings.py` and `adapters/system/project_registry.py` (which reads `CARDRE_REGISTRY_PATH` only in bootstrap).
- `sqlite3` imports outside `adapters/sqlite/`.
- `ArtifactEvidenceReader` outside `adapters/evidence/` + `application/` (via port).
- `ArtifactRepository`, `EvidenceRepository`, `PlanRepository`, `RunRepository`, `RunStepRepository`, `BranchRepository`, `ComparisonRepository`, `ChampionRepository`, `ManualBinningRepository`, `StepRepository`, `ProjectRepository` outside `adapters/sqlite/`.
- FastAPI imports (`fastapi`, `APIRouter`, `Depends`, `Header`) outside `api/`.
- Pydantic `BaseModel` outside `api/schemas.py` (domain uses dataclasses, not pydantic).
- `X-Project-Path` / `X-Project-Id` header strings outside `api/` (and after Batch 07, not at all).

### Existing preserved architecture tests

- `tests/test_canonical_contract.py` — legacy alias ban, node identity, score-scaling defaults, model artifact schema-version. **Preserved; update identifier lists as packages move.**
- `tests/test_evidence_adapters.py:test_adapters_do_not_import_artifact_evidence_reader` — adapter dependency direction. **Preserved.**
- `tests/test_evidence_adapters.py:test_adapters_do_not_implement_summarise` — removed method ban. **Preserved.**
- `tests/test_store_schema_no_queryable_json.py` — no `*_ids_json` columns. **Preserved; update table list for new schema.**
- `tests/test_error_code_sync.py` — frontend ↔ backend error code sync. **Preserved; add new codes.**
- `scripts/audit_artifact_reads.py` — production artifact-read boundary. **Preserved; update approved module list to `adapters/filesystem/`, `adapters/evidence/`, `application/` (via ports).**
- `scripts/check-line-counts.py` — line-count guard. **Preserved; update seam watchlist.**
- `scripts/check-sidecar-naming.py` — sidecar naming. **Preserved.**

## Domain tests

- `tests/test_domain_artifacts.py`, `test_domain_plan.py`, `test_domain_run.py`, `test_domain_step.py` — **preserved**, update imports to `cardre.domain.*`.
- New: `tests/domain/test_invariants.py` — assert invariants from 02-domain-and-use-cases.md (committed version immutable, graph acyclic, step ID uniqueness, run transitions legal, terminal cannot reopen). These are pure domain tests, no I/O.

## Application tests

One test file per use case in `tests/application/<subsystem>/`:
- `test_create_project.py`, `test_list_projects.py`, `test_get_project.py`
- `test_create_plan.py`, `test_commit_plan_version.py`, `test_apply_manual_binning_edit.py`, ...
- `test_submit_run.py`, `test_execute_run.py`, `test_cancel_run.py`, `test_finalize_run.py`, ...
- `test_explain_staleness.py`
- `test_create_branch.py`, `test_create_comparison.py`, `test_refresh_comparison.py`, `test_assign_champion.py`
- `test_generate_report.py`, `test_export_audit_pack.py`

Each use-case test uses an **in-memory `UnitOfWork`** fake + in-memory query objects (or the SQLite adapter against a temp file). Tests assert:
- Principal domain rules (e.g. `CommitPlanVersion` rejects already-committed).
- Transaction boundary (commit called on success, rollback on exception — via a spy UoW).
- Result type.
- Failure modes (each error code raised).

## Port contract tests

For each port in `application/ports/`:
- `tests/ports/test_unit_of_work_contract.py` — defines the contract (open, commit, rollback, conn available). Run against: (a) in-memory fake UoW, (b) `SqliteUnitOfWork` against a temp file. Both must pass.
- `tests/ports/test_artifact_store_contract.py` — stage, publish, read. Run against: (a) in-memory fake, (b) `adapters/filesystem/ArtifactStore` against a temp dir.
- `tests/ports/test_run_dispatcher_contract.py` — dispatch, get_status, shutdown. Run against: (a) `SyncRunDispatcher`, (b) `ThreadRunDispatcher`.
- `tests/ports/test_project_registry_contract.py` — register, resolve, list. Run against: (a) in-memory dict, (b) `adapters/system/ProjectRegistry` against a temp file.
- `tests/ports/test_node_catalogue_contract.py` — definition, availability, instantiate. Run against the real `NodeCatalogue` (no fake needed — it's deterministic from `Settings`).
- `tests/ports/test_clock_contract.py`, `test_id_generator_contract.py` — trivial; run against real + fake.

## Adapter tests

- `tests/adapters/sqlite/test_*.py` — one per query object. Use a temp `SqliteUnitOfWork`. Assert row mapping returns domain dataclasses, SQL is correct, constraints enforced.
- `tests/adapters/filesystem/test_artifact_store.py` — staging, atomic publish, dedup, orphan cleanup, hash computation.
- `tests/adapters/dispatch/test_thread_dispatcher.py` — dispatch, max_workers, duplicate reject, shutdown. **Preserve** `test_worker_lifecycle.py`, `test_run_dispatch.py` semantics.
- `tests/adapters/evidence/test_parsers.py` — **preserve** `test_evidence_adapters.py` parity tests; update to use `ArtifactReader` port instead of `ProjectStore`.
- `tests/adapters/rendering/test_html_report.py` — **preserve** `test_reporting.py`.
- `tests/adapters/system/test_project_registry.py` — atomic file write, missing file handling.

## Numerical parity tests

**Preserved as behavioural oracles:**
- `tests/test_scoring_export_parity.py` — Python/SQL/apply-model parity. **Must pass unchanged after Batch 05.**
- `tests/test_logistic_regression_known_input.py` — logistic regression on known input. **Must pass after Batch 04.**
- `tests/test_score_scaling_known_input.py` — score scaling on known input. **Must pass after Batch 05.**
- `tests/test_calibrate_probabilities.py` — calibration. **Deferred node; pass when graduated.**
- `tests/test_golden_fixtures_roundtrip.py` — `golden_bin_definition.json`, `golden_manual_binning_overrides.json`, `golden_model_artifact.json` round-trip. **Must pass after Batch 04.**
- `tests/test_golden_report_bundle.py` — structural diff against `golden_report_bundle.json`. **Must pass after Batch 07.** If `TechnicalManifestExportNode` redesign changes manifest structure, regenerate golden with `--update-golden` after confirming the change is intentional (R12).
- `tests/test_run_audit_integrity.py` — manifest hash, evidence completeness, run terminal state. **Must pass after Batch 06.**
- `tests/test_executor_characterization.py` — `PlanExecutor` behaviour pin. **Update to characterize `ExecuteRun` use case; preserve the behavioural assertions.**
- `tests/test_branch_service_characterization.py` — `BranchService` behaviour pin. **Update to characterize `CreateBranch` use case.**

## API tests

- `tests/test_api_*.py` (20 files) — **preserved in spirit; rewritten** to test new routes via `fastapi.testclient.TestClient(build_app(container))`. One file per route group.
- Assert: response shapes match `api/schemas.py` Pydantic models; error codes match `ErrorCode`; project_id scoping enforced (404 on unknown project); governance 403 when disabled.
- **No ownership-check tests** — ownership is in use cases now; use-case tests cover it. API tests assert the 404 surfaces.

## Frontend tests

- `frontend/src/api/__tests__/client.test.ts` — **preserved**; update for removed `projectHeaders`, new paths.
- `frontend/src/hooks/__tests__/useProjectWorkspace.test.tsx` — **preserved**; update for new endpoints, `cancelRun` mutation, terminal-status set including `cancelled`.
- `frontend/src/components/__tests__/ProjectView.test.tsx` (if exists) — **preserved**.
- MSW mocks updated to new OpenAPI paths.

## Full product acceptance pathway

Run after Batch 07 (the merged API + cleanup + acceptance batch). Script: `tests/acceptance/test_launch_pathway.py` (rewrite of `test_launch_pathway.py` + `test_api_scorecard_launch_pathway.py` using the new API).

Steps (the 20 items from the task):
1. **Create a project** — `POST /projects` with a temp path. Assert 201 + `ProjectResponse`.
2. **Import a supported dataset** — `POST /runs` with a plan whose first step is `cardre.import_dataset` pointing at `tests/fixtures/german_credit.csv` (or a generated CSV). Assert run succeeds.
3. **Profile the dataset** — `cardre.profile_dataset` step. Assert `PROFILE_SUMMARY` artifact produced.
4. **Create a plan** — `POST /projects/{id}/plans`. Assert 201.
5. **Edit the graph** — (via plan version steps; full editor is future; test uses a constructed plan with the 13-step build pathway).
6. **Commit an immutable plan version** — `POST /plan-versions/{id}/commit`. Assert `is_committed=true`.
7. **Submit a run** — `POST /runs`. Assert 201, status `running` (sync) or `running` (async).
8. **Execute the launch pathway** — wait for terminal status (poll). Assert `succeeded`.
9. **Produce deterministic artifacts** — assert each step produced ≥1 artifact with `physical_hash` + `logical_hash`.
10. **Perform binning and WOE** — assert `BIN_DEFINITION` + `WOE_IV_EVIDENCE` + `WOE_TABLE` artifacts exist.
11. **Fit a logistic scorecard** — assert `MODEL_ARTIFACT` with `schema_version=cardre.model_artifact.v1`.
12. **Scale scores** — assert `SCORE_SCALING` artifact.
13. **Apply the model to test and OOT data** — assert `scored_dataset` artifacts for test/oot roles.
14. **Calculate validation metrics** — assert `VALIDATION_METRICS` artifact.
15. **Export scoring code** — assert `SCORING_EXPORT_PYTHON` + `SCORING_EXPORT_SQL` artifacts.
16. **Generate an audit package** — `ExportAuditPack` use case. Assert `exports/audit-pack-{branch_id}/` exists with checksums.
17. **Replay a committed plan** — `POST /runs` same `plan_version_id`. Assert second run succeeds; compare artifact `logical_hash`es to first run — must match (deterministic).
18. **Verify scoring parity** — `test_scoring_export_parity.py` passes (Python/SQL/apply-model outputs match).
19. **Verify artifact hashes** — recompute `physical_hash` from file bytes; assert matches DB. Recompute `logical_hash` from canonical content; assert matches DB.
20. **Verify canonical manifest consistency** — read `manifests/runs/{run_id}.json`; assert `manifest_hash` recomputes; assert `run_id`/`plan_version_id`/`status` match DB; assert every `evidence_edge` has ≥1 `evidence_artifact`; assert no phantom run_steps.

## Test command summary

Per batch, run the relevant subset. Full suite:

```bash
. .venv/bin/activate
ruff check --fix
make preflight                      # ruff + mypy + line-counts + doc-refs + sidecar-naming + pytest cov gate + governance + artifact-reads + frontend + openapi drift
python3 -m pytest tests/ -q         # full backend
cd frontend && npm test             # frontend
cd frontend/src-tauri && cargo fmt --check && cargo clippy --all-targets -- -D warnings
```

Per-batch focused commands are in each batch document.