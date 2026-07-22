# Batch 06 — Plans + Evidence + Governance + Reporting Use Cases

```text
You are implementing one bounded batch of the Cardre architecture rewrite.

Do not redesign the wider system.

Do not broaden the scope.

Inspect the current repository before editing because earlier batches may already have changed the paths referenced here.

Preserve validated mathematical and product behaviour, but do not preserve obsolete internal APIs or compatibility layers.

Complete this batch fully, including tests and deletion of code superseded within its scope.
```

## 1. Task objective

Port the remaining use cases: plans (CreatePlan, GetPlan, ListPlans, GetPlanVersion, ListPlanVersions, UpdatePlanVersion, CommitPlanVersion, ApplyManualBinningEdit), evidence (ExplainStaleness), governance (CreateBranch, CreateComparison, RefreshComparison, AssignChampion), reporting (GenerateReport, ExportAuditPack). Port the `adapters/rendering/` (HTML report) + `adapters/reporting/` (collector). Delete the old `cardre/services/` files + `cardre/reporting/` + `cardre/readiness/` + `cardre/evidence_locator.py` + `cardre/branch_step_resolver.py`.

## 2. Repository context

Read `docs/architecture-rewrite/02-domain-and-use-cases.md` (all use cases), `01-target-architecture.md` (adapters/rendering, adapters/reporting). Existing: `cardre/services/plan_service.py`, `plan_mutation_service.py`, `branch_service.py`+`branch_validator.py`+`branch_graph.py`+`branch_writer.py`, `comparison_service.py`+`comparison/*`, `champion_service.py`, `staleness_service.py`, `export_service.py`, `report_service.py`, `manual_binning_service.py`, `plan_dto.py`, `export_listing.py`, `project_resolver.py` (deleted in 02). `cardre/reporting/`, `cardre/readiness/`, `cardre/evidence_locator.py`, `cardre/branch_step_resolver.py`. Batches 03 (persistence) + 06 (runs) are in place.

## 3. Why the batch exists

These use cases complete the application layer. After this batch, all business rules live in `application/**`; old services are gone. Routes (Batch 07) can then be thin handlers.

## 4. Current relevant architecture

Each service takes `ProjectStore`, constructs repositories inline, has business rules mixed with SQL/persistence. `comparison/*` builders take `store`. `staleness_service` takes `store` + constructs `EvidenceLocator(store)`. `reporting/collector.py` takes `store`. `evidence_locator.py:EvidenceLocator(store)` has the 4-stage fallback chain. `branch_step_resolver.py` takes `store`.

## 5. Target architecture after the batch

- `application/plans/create_plan.py`, `get_plan.py`, `list_plans.py`, `get_plan_version.py`, `list_plan_versions.py`, `update_plan_version.py`, `commit_plan_version.py`, `apply_manual_binning_edit.py` — use cases via UoW.
- `application/evidence/explain_staleness.py:ExplainStaleness` — via UoW + `EvidenceReaderPort`. The 4-stage fallback chain (branch → full_plan → latest_plan_run → across_plan) ported from `evidence_locator.py` into `application/evidence/evidence_resolver.py` (or inline) using `uow.runs`/`uow.run_steps`/`uow.evidence` query ports. No `EvidenceLocator` class; the logic is in the use case + a helper.
- `application/governance/create_branch.py`, `create_comparison.py`, `refresh_comparison.py`, `assign_champion.py` — use cases via UoW. Branch validation rules ported from `branch_validator.py` into the use case or a `domain/plans/branch_rules.py`. Graph remapping from `branch_graph.py` → `domain/plans/graph.py` (pure). Transaction writer from `branch_writer.py` → inline in `CreateBranch` use case via UoW.
- `application/reporting/generate_report.py:GenerateReport`, `export_audit_pack.py:ExportAuditPack` — via UoW + `ArtifactReader` + `ReportRendererPort`.
- `adapters/rendering/html_report.py:HtmlReportRenderer` (from `reporting/renderer_html.py`) implementing `ReportRendererPort`. Templates moved to `adapters/rendering/templates/`.
- `adapters/reporting/collector.py:ReportCollector` (from `reporting/collector.py`) — takes `EvidenceReaderPort` + `ArtifactReader` (not `ProjectStore`). Reads evidence via ports; assembles `ReportBundle` (pydantic preserved from `reporting/schema.py` → `api/schemas.py` or `application/reporting/schema.py`). `_resolve.py` ported to use `EvidenceReaderPort`.
- `application/ports/report_renderer.py:ReportRendererPort` (`render(bundle: ReportBundle, output_dir: Path) -> Path`).
- Old `cardre/services/plan_service.py`, `plan_mutation_service.py`, `branch_service.py`, `branch_validator.py`, `branch_graph.py`, `branch_writer.py`, `comparison_service.py`, `comparison/*`, `champion_service.py`, `staleness_service.py`, `export_service.py`, `report_service.py`, `manual_binning_service.py`, `plan_dto.py`, `export_listing.py` — deleted.
- Old `cardre/reporting/` — moved to `adapters/rendering/` + `adapters/reporting/` + `application/reporting/`. `cardre/reporting/` deleted.
- Old `cardre/readiness/` — ported into `application/reporting/readiness.py` (the readiness check logic) using `EvidenceReaderPort`. `cardre/readiness/` deleted.
- Old `cardre/evidence_locator.py`, `cardre/branch_step_resolver.py` — deleted (logic in `application/evidence/`).

## 6. Exact scope

- Write all plans use cases (8).
- Write `application/evidence/explain_staleness.py` + `application/evidence/evidence_resolver.py` (the fallback chain).
- Write all governance use cases (4) + `domain/plans/graph.py` (descendant/ancestor closure — moved from `execution/step_graph.py` or kept in `application/execution/`; decide). Actually `step_graph.py` is already moved to `application/execution/` in Batch 05; reuse it.
- Write `application/reporting/generate_report.py`, `export_audit_pack.py`, `readiness.py`.
- Write `adapters/rendering/html_report.py` + move templates.
- Write `adapters/reporting/collector.py` + `_resolve.py` port.
- Move `cardre/reporting/schema.py` (pydantic `ReportBundle`, `RunManifest`) → `application/reporting/schema.py` (or `api/schemas.py` — decide: `ReportBundle` is an internal model used by the collector + renderer, not an API response; keep in `application/reporting/schema.py`. `RunManifest` is used by `FinalizeRun` — already referenced in Batch 05; ensure it's accessible. Put both in `application/reporting/schema.py`.)
- Delete old services + reporting + readiness + evidence_locator + branch_step_resolver.
- Port characterization tests: `test_branch_service_characterization.py` → `test_create_branch_characterization.py`; `test_comparison_service.py`, `test_champion_service.py`, `test_staleness_service.py`, `test_reporting.py`, `test_exports.py` updated for use cases.

## 7. Files to inspect first

- `cardre/services/plan_service.py`, `plan_mutation_service.py` (plan rules).
- `cardre/services/branch_service.py`, `branch_validator.py`, `branch_graph.py`, `branch_writer.py` (branch rules).
- `cardre/services/comparison_service.py`, `comparison/woe_iv.py`, `model.py`, `validation.py`, `cutoff.py`, `resolver.py` (comparison builders — port `store` to `EvidenceReaderPort`).
- `cardre/services/champion_service.py`, `staleness_service.py`, `export_service.py`, `report_service.py`, `manual_binning_service.py`, `export_listing.py` (port each).
- `cardre/evidence_locator.py` (4-stage fallback).
- `cardre/branch_step_resolver.py`.
- `cardre/reporting/collector.py`, `_resolve.py`, `schema.py`, `renderer_html.py`, `evidence_contract.py`, `sections/`, `templates/`.
- `cardre/readiness/check.py`, `step_requirements.py`.
- `tests/test_branch_service_characterization.py`, `test_comparison_service.py`, `test_champion_service.py`, `test_staleness_service.py`, `test_reporting.py`, `test_exports.py`, `test_plan_mutation_service.py`, `test_golden_report_bundle.py`.

## 8. Files likely to change

- `cardre/application/plans/` (new package with 8 use cases)
- `cardre/application/evidence/` (new package)
- `cardre/application/governance/` (new package with 4 use cases)
- `cardre/application/reporting/` (new package with `generate_report.py`, `export_audit_pack.py`, `readiness.py`, `schema.py`)
- `cardre/application/ports/report_renderer.py` (new)
- `cardre/adapters/rendering/` (new package)
- `cardre/adapters/reporting/` (new package: `collector.py`, `_resolve.py`)
- `cardre/domain/plans/graph.py` (new — or reuse `application/execution/step_graph.py`)
- Tests updated.
- Old services/reporting/readiness/evidence_locator/branch_step_resolver deleted.

## 9. Files likely to create

See "Files likely to change" — the `new` entries.

## 10. Files likely to delete

- `cardre/services/plan_service.py`, `plan_mutation_service.py`, `branch_service.py`, `branch_validator.py`, `branch_graph.py`, `branch_writer.py`, `comparison_service.py`, `comparison/`, `champion_service.py`, `staleness_service.py`, `export_service.py`, `report_service.py`, `manual_binning_service.py`, `plan_dto.py`, `export_listing.py`.
- `cardre/reporting/` (all moved).
- `cardre/readiness/`.
- `cardre/evidence_locator.py`.
- `cardre/branch_step_resolver.py`.
- `cardre/services/__init__.py` (or trim to only remaining exports — none remain after this batch; the manual-binning extract functions `extract_woe_by_bin` etc. move to `application/plans/manual_binning_preview.py` or `domain/binning/`).

## 11. Required implementation sequence

1. Write `application/plans/create_plan.py`, `get_plan.py`, `list_plans.py`, `get_plan_version.py`, `list_plan_versions.py`, `update_plan_version.py` — straightforward UoW use cases. `commit_plan_version.py`: validate version exists + draft, run `validate_topology` on steps, `uow.plans.commit_version`, commit. `apply_manual_binning_edit.py`: port `PlanMutationService.apply_manual_binning_edit` logic (source evidence validation, override merge, params_hash recompute, new draft version + review in one UoW).
2. Write `application/evidence/evidence_resolver.py:resolve_evidence(uow, plan_version_id, step_id, branch_id, plan_id, fingerprint_match)` — port the 4-stage fallback from `evidence_locator.py:EvidenceLocator.resolve`. Uses `uow.evidence.get_edges_for_plan_step_branch`, `uow.run_steps.get`, `uow.runs.get_latest_successful_id`, etc.
3. Write `application/evidence/explain_staleness.py:ExplainStaleness` — port `StalenessService.explain_step` recursive DAG walk using `resolve_evidence` + parent output hash comparison.
4. Write `application/plans/manual_binning_preview.py` (or `domain/binning/`) — move `extract_woe_by_bin`, `extract_iv`, `extract_event_rate_by_bin` from `services/manual_binning_service.py` (pure functions; keep pure).
5. Write `application/governance/create_branch.py:CreateBranch` — port `BranchService.create_branch` + `BranchValidator` rules + `branch_graph.py` closure/remap + `branch_writer.py` transaction. All in one UoW.
6. Write `application/governance/create_comparison.py:CreateComparison` + `refresh_comparison.py:RefreshComparison` — port `comparison_service` logic; `comparison/*` builders take `EvidenceReaderPort` instead of `store` (port `find_typed_artifact` to use `EvidenceReaderPort.read_optional` + `uow.artifacts.output_artifacts_for_run_step`). Snapshot creation + plan version rows in one UoW. Comparison artifact written via `ArtifactStore`.
7. Write `application/governance/assign_champion.py:AssignChampion` — port `champion_service.assign_champion` rules + supersede in one UoW.
8. Move `cardre/reporting/schema.py` → `application/reporting/schema.py` (`RunManifest`, `ReportBundle`). Update imports (Batch 05's `FinalizeRun` references `RunManifest` — update).
9. Write `application/reporting/readiness.py:check_report_readiness(evidence_reader, run_id, ...)` — port `readiness/check.py` logic.
10. Write `adapters/reporting/collector.py:ReportCollector` — port `reporting/collector.py` to take `EvidenceReaderPort` + `ArtifactReader` instead of `ProjectStore`. `_resolve.py` ported to use `resolve_evidence` + `EvidenceReaderPort`.
11. Write `adapters/rendering/html_report.py:HtmlReportRenderer` — port `reporting/renderer_html.py` (jinja2 templates moved to `adapters/rendering/templates/`). Implement `ReportRendererPort.render(bundle, output_dir)`.
12. Write `application/reporting/generate_report.py:GenerateReport` — port `report_service.py:ReportGenerationService` logic: readiness check → collector → renderer → write. Uses `EvidenceReaderPort` + `ReportRendererPort`.
13. Write `application/reporting/export_audit_pack.py:ExportAuditPack` — port `export_service.py:export_branch_audit_pack` logic: atomic tmp-dir→rename, checksums, optional report. Uses `EvidenceReaderPort` + `ArtifactReader` + `ReportRendererPort`.
14. Delete old services, reporting, readiness, evidence_locator, branch_step_resolver.
15. Update characterization tests: `test_branch_service_characterization.py` → assert `CreateBranch` use case persisted state; `test_comparison_service.py` → `test_refresh_comparison.py`; `test_champion_service.py` → `test_assign_champion.py`; `test_staleness_service.py` → `test_explain_staleness.py`; `test_reporting.py` → `test_generate_report.py`; `test_exports.py` → `test_export_audit_pack.py`; `test_plan_mutation_service.py` → `test_apply_manual_binning_edit.py`; `test_golden_report_bundle.py` updated (regenerate golden if `TechnicalManifestExportNode` changed in 06).
16. Run all tests.

## 12. Interfaces and invariants

- All use cases take ports, not `ProjectStore`.
- `ExplainStaleness` uses `EvidenceReaderPort` + UoW (read-only).
- `CreateBranch` does graph remap + write in one UoW.
- `RefreshComparison` does all snapshots + final UPDATE in one UoW.
- `GenerateReport` writes via `ReportRendererPort` (filesystem).
- `ExportAuditPack` atomic tmp→rename (preserved).
- `ReportBundle` + `RunManifest` pydantic models preserved (in `application/reporting/schema.py`).

## 13. Behaviour to preserve

- `test_branch_service_characterization.py` assertions (branch + step_map + plan_version rows).
- `test_comparison_service.py` (comparison + challenger branches + snapshots).
- `test_champion_service.py` (champion assignment + supersede).
- `test_staleness_service.py` (staleness status fresh/stale/missing + upstream changes).
- `test_reporting.py` (report bundle structure).
- `test_exports.py` (audit pack contents, checksums, atomic rename).
- `test_plan_mutation_service.py` (manual binning edit new draft version + review).
- `test_golden_report_bundle.py` (structural diff — regenerate golden if manifest changed).
- Governance 403 when disabled (preserved via use case checks).

## 14. Intentional breaking changes

- `BranchService` → `CreateBranch`. `ComparisonService` → `CreateComparison`/`RefreshComparison`. `ChampionService` → `AssignChampion`. `StalenessService` → `ExplainStaleness`. `ReportGenerationService` → `GenerateReport`. `ExportService` → `ExportAuditPack`. `PlanService` → multiple use cases. `PlanMutationService` → `ApplyManualBinningEdit`. `EvidenceLocator` → `resolve_evidence` helper. `ManualBinningService` pure functions → `application/plans/manual_binning_preview.py`.
- `ReportBundle`/`RunManifest` moved to `application/reporting/schema.py`.

## 15. Tests to add or update

- `tests/application/plans/test_*.py` (8 files).
- `tests/application/evidence/test_explain_staleness.py` + `test_resolve_evidence.py` (4-stage fallback).
- `tests/application/governance/test_create_branch.py` (characterization), `test_create_comparison.py`, `test_refresh_comparison.py`, `test_assign_champion.py`.
- `tests/application/reporting/test_generate_report.py`, `test_export_audit_pack.py`, `test_readiness.py`.
- `tests/adapters/reporting/test_collector.py`.
- `tests/adapters/rendering/test_html_report.py`.
- Update `test_golden_report_bundle.py` (regen golden if needed).

## 16. Commands to run

```bash
. .venv/bin/activate
ruff check --fix
python3 -m importlinter --config .importlinter
make preflight
python3 -m pytest tests/application/plans tests/application/evidence tests/application/governance tests/application/reporting tests/adapters/reporting tests/adapters/rendering -q
python3 -m pytest tests/test_golden_report_bundle.py tests/test_scoring_export_parity.py -q
python3 -m pytest tests/ -q
```

## 17. Acceptance criteria

- All plans/evidence/governance/reporting use cases work via UoW + ports.
- `test_golden_report_bundle.py` passes (regen golden if `TechnicalManifestExportNode` output changed).
- `test_scoring_export_parity.py` passes.
- No `ProjectStore` in `application/`, `adapters/reporting/`, `adapters/rendering/`.
- Old `cardre/services/`, `cardre/reporting/`, `cardre/readiness/`, `cardre/evidence_locator.py`, `cardre/branch_step_resolver.py` deleted.
- `make arch-check` passes.
- `make preflight` passes (coverage ≥60%).
- Governance tests (`pytest -m governance`) pass with `CARDRE_GOVERNANCE=1`.

## 18. Architecture rules

- `application/**` no `ProjectStore`, no `sqlite3`, no `os.environ`.
- `adapters/reporting/**` + `adapters/rendering/**` import `application/ports/`, `domain/`, stdlib, jinja2.
- `application/reporting/schema.py` pydantic models are internal (not API responses).

## 19. Prohibited shortcuts

- Do not leave any `ProjectStore` in ported use cases.
- Do not skip the 4-stage fallback in `resolve_evidence`.
- Do not skip atomic rename in `ExportAuditPack`.
- Do not change `ReportBundle` field structure (golden fixture).
- Do not skip governance checks (403 when disabled).

## 20. Explicit out-of-scope work

- Routes (Batch 07).
- Deleting `cardre/store/`, `cardre/config.py`, `cardre/artifacts.py` (Batch 07).
- Frontend (Batch 07).

## 21. Expected final report format

1. Use case list (plans 8, evidence 1, governance 4, reporting 2).
2. Characterization test results.
3. `test_golden_report_bundle.py` (regen if needed).
4. Grep confirming no `ProjectStore` in `application/`/`adapters/`.
5. `make preflight` + `make arch-check` + governance tests summary.
6. Files created/deleted.

## Identity

- Sequence: 06
- Title: Plans + Evidence + Governance + Reporting Use Cases
- Architectural objective: complete the application layer; delete old services
- Reason for position: follows 03 + 06 (persistence + execution); precedes 08 (routes)
- Difficulty: high — many use cases, porting business rules + characterization tests

## Scope summary

- Created: `application/plans/*`, `application/evidence/*`, `application/governance/*`, `application/reporting/*`, `adapters/rendering/*`, `adapters/reporting/*`, `application/ports/report_renderer.py`, tests.
- Changed: characterization tests updated.
- Deleted: `cardre/services/*`, `cardre/reporting/`, `cardre/readiness/`, `cardre/evidence_locator.py`, `cardre/branch_step_resolver.py`.
- Behaviour preserved: all business rules + golden fixtures.
- Behaviour changed: service classes → use cases; `ReportBundle`/`RunManifest` moved.
- Exclusions: routes (08), old infra deletion (09).

## Design decisions

- D2 (preserve vocabulary), D5 (UoW), D6 (registry port), D13 (enforcement).

## Tests

See §15.

## Acceptance criteria

See §17.

## Risks

- R11 (governance regression), R12 (golden report bundle regen), R2 (parity), R13 (evidence adapter usage in collector).

## Agent boundaries

Do not modify: `cardre/store/`, `cardre/api/**`, `cardre/nodes/**`, `cardre/domain/`, `cardre/config.py`, `cardre/artifacts.py`, `cardre/capabilities.py`, frontend, sidecar, `cardre/execution/` (already deleted in 06).

## Dependencies

- Required earlier: Batch 02 (persistence), Batch 05 (runs + execution).
- Optional parallel: **yes — 4-way parallel.** Split into sub-PRs by family (06a plans, 06b evidence, 06c governance, 06d reporting) landing concurrently after Batch 05 merges. Merge as one batch.
- Open PRs: none.

## Estimated reasoning difficulty

high.