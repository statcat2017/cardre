# 06 — Sprint Plan

## Prerequisite decision

**Resolved 2026-07-21.** [ADR-0014](../adr/0014-supersede-0002-authorise-hexagonal-re-encapsulation.md) supersedes ADR-0002 and authorises the hexagonal re-encapsulation. ADR-0002 is marked Superseded. The sprint may begin. ADR-0014 records D1 (clean rewrite) and D2 (preserve domain vocabulary) as Accepted, and carries forward ADR-0002's preserved design commitments (dual hashing, computed staleness, build/validate role enforcement, settled vocabulary, single execution path).

## Pre-sprint: implementation decisions (D3–D18) — RESOLVED

All 16 implementation decisions are confirmed as Accepted (2026-07-21) in `00-validation-report.md` §Resolved implementation decisions. Two additional decisions (D19 `cardre/engine/` + `cardre/workflows/` disposition, D20 `pr7-followup` forwarders) were resolved after inspecting `cardre/engine/binning/` (5 modules, 10 import sites) and `cardre/workflows/scorecard.py` (canonical 13-step pathway, 5 test import sites). No batch agent should need to make or stall on any decision. The sprint may begin immediately.

## Batch 07 reset

The original Batch 07 combined frontend cutover, package relocation, persistence deletion, execution-context removal, enforcement, and full acceptance in one change. The abandoned `batch-07-cleanup` branch is retained only as historical evidence; no commit from it may be merged or cherry-picked.

Batch 07 is now a sequence of six bounded PRs: 7b through 7g. Each PR must leave one canonical implementation, delete the legacy surface it replaces, and add no compatibility shim. This is required by [ADR-0003](../adr/0003-no-legacy-plan-accommodation.md): Cardre has not launched, so persisted-plan or internal-API compatibility is not a delivery constraint.

## Batches at a glance (revised for bounded delivery)

The original 9-batch plan is restructured via four delivery levers: merge the trivial skeleton into Batch 01, overlap persistence with node-contract design, split the bulk node port into family PRs, and split the former final cleanup into bounded migrations. The final lever replaces a large, incompatible cleanup PR with independently reviewable work and one final acceptance gate.

| # | Title | Objective | Reason for position | Difficulty | Parallelizable |
|---|-------|-----------|---------------------|------------|----------------|
| 01 | Bootstrap + API skeleton + composition root + architecture enforcement | **Merged with old Batch 01.** `Settings`, `Container`, `build_app`, thin API (`/health` + `/projects`), `ProjectRegistryPort` + `ProjectProvisionerPort` + `UnitOfWork` skeleton + adapters; `importlinter` config + forbidden-symbol tests (xfail during migration); `domain/` `application/ports/` `nodes/contracts.py` `bootstrap/` skeletons. Regenerate OpenAPI. | First real batch; proves the composition root + dependency direction; enforcement blocking from the start | high | no (foundation) |
| 02 | SQLite persistence layer + clean schema + artifact store | Clean schema v1; `SqliteUnitOfWork`; all SQLite query objects; `adapters/filesystem/ArtifactStore` (staging+atomic publish); port contract tests (in-memory + sqlite) | Foundation every use case + node depends on; artifact atomicity is the core fix for H7 | very high | overlaps with 03-design (see below) |
| 03 | Domain moves + node contracts + port first node | Move `domain/evidence/`, `nodes/parameters.py`; introduce `NodeDefinition`/`NodeContext`/`InputCollection`/`OutputPublisher`/`NodeResult`; port `LogisticRegressionNode` (parity oracle); port `adapters/evidence/` behind `ArtifactReader` | Proves the node contract with the canonical fit node; evidence adapters become real adapters | very high | **design overlaps with 02** (see Parallelization) |
| 04 | Port remaining launch nodes (parallel family sub-PRs) | Port 30 launch nodes from `context.store` to `NodeContext`; port `modeling/adapters.py` + `serialization.py` + `_training_utils.py`; `bootstrap/node_catalogue.py`. **Split into 4–5 parallel sub-PRs by family:** prep (8), build-fit (15, incl. LogisticRegression done in 03), build-export (3), validate-apply (4). (`TechnicalManifestExportNode` deferred to 05.) | All launch nodes must be on the new contract before execution runs; mechanical work following the pattern 03 proved | high | **yes — 4-way parallel** |
| 05 | Execution runtime + runs use cases + `TechnicalManifestExportNode` | `SubmitRun`, `ExecuteRun`, `CancelRun`, `GetRun`, `ListRuns`, `GetRunSteps`, `GetRunEvidence`; `StepRunner` (new); `ThreadRunDispatcher`/`SyncRunDispatcher`; `FinalizeRun` (manifest inside UoW); port `TechnicalManifestExportNode` (needs `RunSummary` from `ExecuteRun`); cooperative cancellation; delete old `cardre/execution/` + `services/run_coordinator.py` | Ties nodes + persistence + dispatch; must follow 02+03+04 | very high | no (integration point) |
| 06 | Plans + evidence + governance + reporting use cases (parallel sub-PRs) | All remaining use cases: plans (8), evidence (1), governance (4), reporting (2); `adapters/rendering/`, `adapters/reporting/`; delete old `cardre/services/`, `cardre/reporting/`, `cardre/readiness/`, `cardre/evidence_locator.py`, `cardre/branch_step_resolver.py` | Use cases depend on 02+05; independent of each other → parallel | high | **yes — 4-way parallel** (plans, evidence, governance, reporting) |
| 07b | Frontend API cutover | Consume merged 7a API routes with path-only project identity; regenerate client types; update frontend hooks, components, and tests | 7a is the stable API producer; this is the only consumer cutover | high | no |
| 07d | Binning and canonical-pathway migration | Move binning and scorecard pathway to canonical domain locations; delete `cardre/engine` and `cardre/workflows` | Keeps canonical vocabulary and pathways together | high | no |
| 07c | Evidence-package migration | Move evidence models, schemas, and kinds into `domain/evidence`; move profiles, readers, and parsers into `adapters/evidence`; delete `cardre/_evidence` | Depends on 07d relocating the binning schema imported by evidence code | high | no |
| 07f | Legacy execution-context removal | Port deferred nodes and helpers to `NodeContext`; delete `ExecutionContext` and dual dispatch | Removes the final runtime compatibility seam | high | no |
| 07e | `ProjectStore` removal and test migration | Remove legacy store/config/artifact/capability surfaces after every production caller, including deferred nodes, uses ports and adapters | Cannot delete infrastructure until 07f removes its node callers | very high | no |
| 07g | Final enforcement and full acceptance | Make architecture rules strict and run the complete product acceptance pathway | Only valid once all legacy surfaces are absent | high | no (final gate) |

Each 07 sub-batch is one PR. Batches 04 and 06 remain sets of parallel sub-PRs; 07b–07g merge in dependency order so each deletion has a single, auditable owner.

## Dependency graph

```
        ┌────────────────────────────────────────────────┐
        │                                                │
01 ──> 02 ──> 03 ──> 04 (4 parallel sub-PRs) ──> 05 ──> 06 (4 parallel sub-PRs) ──> 07b ──> 07d ──> 07c ──> 07f ──> 07e ──> 07g
                ▲       │                                  │
                │       └── 03-design overlaps 02 ─────────┘
                │
        (03 contract design starts during 02 implementation)
```

Serial critical path: **01 → 02 → 03 → 04 → 05 → 06 → 07b → 07d → 07c → 07f → 07e → 07g**.
Wall-clock path retains the Batch 03-design and Batch 04/06 parallelism; the closeout is intentionally serial to prevent temporary compatibility layers becoming permanent.

## Parallelization opportunities (the four levers)

### Lever 1: Merge old Batch 01 into new Batch 01

Old Batch 01 was a trivial skeleton (empty packages + `importlinter` config + xfail tests). Folding it into the first commit of new Batch 01 (the bootstrap + API skeleton) loses one full PR cycle and loses nothing — enforcement starts the moment the new packages exist. The `importlinter` config and forbidden-symbol tests are part of the first commit.

### Lever 2: Overlap Batch 02 implementation with Batch 03 contract design

Batch 03's `NodeDefinition`/`NodeContext`/`InputCollection`/`OutputPublisher` Protocols are pure interface work depending only on ports from Batch 01, not on Batch 02's SQLite implementation. **Start Batch 03's contract design in a branch while Batch 02 implements.** Merge Batch 02 first, then Batch 03 lands on top. Saves the serial wait between the two "very high" batches.

Concretely: the agent for Batch 03 can begin writing `nodes/contracts.py` Protocols + `application/ports/artifact_store.py` + `application/ports/evidence_reader.py` while Batch 02 is in review. The port definitions don't import `adapters/sqlite/` or `adapters/filesystem/` — only `domain/`. When Batch 02 merges, Batch 03's contract branch rebases and fills in the implementations.

### Lever 3: Split Batch 04 into parallel family sub-PRs

Batch 04 is the wall-clock bottleneck: 30 nodes, mechanical, one proven pattern (from Batch 03's `LogisticRegressionNode`). **Split into 4 parallel sub-PRs landing concurrently after Batch 03 merges:**

| Sub-PR | Nodes | Approx. count |
|--------|-------|---------------|
| 04a — prep | `ImportTabularDatasetNode`, `ProfileDatasetNode`, `ValidateBinaryTargetNode`, `SplitTrainTestOotNode`, `ApplyExclusionsNode`, `ExplicitMissingOutlierTreatmentNode`, `DefineModellingMetadataNode`, `DevelopmentSampleDefinitionNode` | 8 |
| 04b — build-fit | `AutomaticBinningNode`, `CalculateWoeIvNode`, `WoeTransformTrainNode`, `ManualBinningNode`, `VariableClusteringNode`, `VariableSelectionNode`, `ScoreScalingNode`, `BuildSummaryReportNode`, `FrozenScorecardBundleNode`, `CoefficientSignCheckNode`, `SeparationDiagnosticsNode`, `VifDiagnosticsNode`, `CalibrationDiagnosticsNode`, `DummyFitNode`, `NoopNode` | 15 (LogisticRegression already in 03) |
| 04c — build-export | `ScorecardTableExportNode`, `PythonScoringExportNode`, `SqlScoringExportNode` | 3 |
| 04d — validate-apply | `ApplyWoeMappingNode`, `ApplyModelNode`, `ValidationMetricsNode`, `CutoffAnalysisNode` | 4 |

Plus shared work (ported once, in whichever sub-PR lands first, or in a tiny 04-shared pre-PR): `modeling/adapters.py`, `modeling/serialization.py`, `_training_utils.py`, `bootstrap/node_catalogue.py`.

Four agents in parallel cuts the critical-path time for this batch by ~4×. Sub-PRs merge into one batch; each must pass its own parity tests. The sub-PRs have minimal overlap (only the shared `modeling/` + catalogue — land that first in a 10-minute pre-PR, then the four family branches branch off it).

### Lever 4: Parallelize Batch 06 into four sub-PRs

After Batch 05 lands, the four use-case families are independent:

| Sub-PR | Use cases |
|--------|-----------|
| 06a — plans | `CreatePlan`, `GetPlan`, `ListPlans`, `GetPlanVersion`, `ListPlanVersions`, `UpdatePlanVersion`, `CommitPlanVersion`, `ApplyManualBinningEdit` |
| 06b — evidence | `ExplainStaleness` + `evidence_resolver.py` (4-stage fallback) |
| 06c — governance | `CreateBranch`, `CreateComparison`, `RefreshComparison`, `AssignChampion` |
| 06d — reporting | `GenerateReport`, `ExportAuditPack`, `adapters/rendering/`, `adapters/reporting/`, `readiness.py` |

Four agents in parallel; merge as one batch. Each deletes the old `cardre/services/*` files it replaces.

### Lever 5: Split Batch 07 into bounded clean cuts

The former combined Batch 07 is not a safe PR boundary. It mixed a frontend contract cutover with domain package moves, infrastructure deletion, deferred-node migration, and enforcement. Those changes cannot be reviewed or reverted independently, and compatibility shims hide incomplete work. The six briefs in `batches/07b-*.md` through `07g-*.md` define the exact sequence and per-PR gates.

## Review strategy

- **Run `make preflight` before every push.** It catches ruff, mypy, line-counts, artifact-reads, governance tests, openapi drift, frontend typecheck/build — most CI failures locally. The PR gate then only waits on jobs preflight can't run (sidecar build, tauri check, smoke test). Don't let agents push blind; a failed preflight is a wasted CI round.
- Each batch PR must pass the PR gate (`scripts/pr-gate.sh`).
- Each batch must include new tests proving the batch's invariants (see per-batch docs).
- Each batch must preserve the parity/characterization tests (`test_scoring_export_parity`, `test_logistic_regression_known_input`, `test_score_scaling_known_input`, `test_golden_fixtures_roundtrip`, `test_golden_report_bundle`, `test_run_audit_integrity`) — these are the behavioural oracles. Imports update; behaviour must not change.
- The product acceptance pathway (see 08-acceptance-and-test-strategy.md) is run only as the 07g gate.

## Deletion and migration ownership

The prior table described intended deletes, not the actual repository state. Do not infer that an original batch completed a listed deletion. The current state was revalidated before this reset.

| Original assignment | Actual current state | Corrected owner |
|---------------------|----------------------|-----------------|
| 02: delete `ProjectStore` and `cardre/store/` | `cardre/store/` remains; production callers still use it and the legacy `ProjectStore` name remains in the SQLite adapter. | 07e, after 07f removes all deferred-node callers. |
| 03: move/delete `cardre/_evidence`, `cardre/engine`, and `cardre/workflows` | All three legacy package surfaces remain. Evidence profiles and legacy evidence models import binning constants from `cardre.engine`. | 07d relocates binning and the pathway, including all legacy evidence-package importers; 07c then relocates and deletes `cardre/_evidence`. |
| 04: delete `cardre/execution/context.py` after all nodes port | `ExecutionContext`, `NodeOutput`, `context.store`, legacy artifact writers, and legacy evidence readers remain in deferred nodes and helpers. | 07f ports every remaining caller, then deletes the legacy execution context. |
| 05: delete legacy execution modules | Compatibility forwarders and the legacy context remain while deferred nodes still consume them. | 07f owns only the context and node-facing forwarders; it must not retain a dual runtime path. |
| 06: delete old service infrastructure | Most listed services moved, but legacy project-resolution and persistence glue remain. | 07e removes only glue made unused after its caller migration. |
| 07b | `X-Project-Id` handling and frontend header assumptions remain. | 07b removes both sides of the transport compatibility behavior. |
| 07d | `cardre/engine/` and `cardre/workflows/` remain. | 07d deletes them after moving code and every importer to canonical locations. |
| 07c | `cardre/_evidence/` remains. | 07c deletes it after 07d removes its binning-package dependency. |
| 07f | Deferred nodes still reach store/artifact surfaces through the legacy context. | 07f removes those callers before infrastructure deletion. |
| 07e | `cardre/store/`, `cardre/config.py`, `cardre/artifacts.py`, and `cardre/capabilities.py` remain. | 07e deletes them only after 07f. |
| 07g | Final enforcement has not run. | 07g adds no deletions; it makes the resulting architecture non-regressible. |

## Point at which old architecture disappears

After 07e, the old architecture is absent. 07g proves that absence with strict enforcement and the full acceptance pathway. Batches 01–06 and 07b–07f may retain only legacy surfaces that a later named sub-batch owns; they must not add aliases, forwarders, dual dispatch, or migration `xfail`s to make that coexistence appear complete.

**The application does not need to remain runnable after every intermediate batch.** Documented broken intermediate states:
- After 01: only `/health` + `/projects` work; all other routes 404.
- After 02: persistence layer exists but no use cases use it; old `ProjectStore` still in place for non-project routes (which are 404).
- After 03: one node ported; no execution path uses it yet.
- After 04: all nodes ported; old execution path intentionally broken (execution tests xfail).
- After 05: new execution path exists; old one deleted.
- After 06: all use cases exist; old services deleted.
- After 07b: frontend uses the 7a API contract with path-only project identity.
- After 07d: binning and the scorecard pathway have one canonical home; legacy evidence importers use the new binning surface.
- After 07c: evidence has one domain/adaptor home.
- After 07f: all nodes use `NodeContext`; no node or helper imports legacy store, artifact, or evidence surfaces.
- After 07e: `ProjectStore` and legacy infrastructure are absent.
- After 07g: enforcement is strict and the acceptance pathway is green.

## Open PRs and branches

Per 00-validation-report.md §Active overlapping work:
- All `refactor/slice-*` branches: **superseded** — do not merge. The rewrite deletes the code they refactor.
- `chore/fix-forward-heartbeat-coverage`, `chore/slice-5-coverage-bump`: **incorporate** the coverage floor policy into the plan (D17).
- `pr0-safety-net`, `pr0-followup-docs`: **preserve as behavioural knowledge** (golden fixture determinism). Verify golden fixtures still pass after the rewrite.
- `pr7-followup-drop-bin-definition-forwarders`: **verify** before Batch 01 that dead `_lifecycle` forwarders are gone; if not, the rewrite deletes them anyway.
- All merged deepening PRs: **absorbed** as the baseline; their behaviour is preserved by the parity tests.

## Acceptance pathway responsibility allocation

| Acceptance item | Responsible batch |
|-----------------|-------------------|
| 1. create a project | 01 |
| 2. import a supported dataset | 04 (ImportTabularDatasetNode ported) + 07b (frontend contract) |
| 3. profile the dataset | 04 (ProfileDatasetNode ported) + 07b |
| 4. create a plan | 06 (CreatePlan use case) + 07b |
| 5. edit the graph | 06 (UpdatePlanVersion — though graph editing is currently manual via params; full editor is future) + 07b |
| 6. commit an immutable plan version | 06 (CommitPlanVersion) + 07b |
| 7. submit a run | 05 (SubmitRun) + 07b |
| 8. execute the launch pathway | 05 (ExecuteRun) + 04 (all launch nodes) |
| 9. produce deterministic artifacts | 02 (artifact store) + 04 (nodes) + 05 (finalization) |
| 10. perform binning and WOE | 04 (AutomaticBinningNode, CalculateWoeIvNode, WoeTransformTrainNode) |
| 11. fit a logistic scorecard | 03 (LogisticRegressionNode) + 04 (ScoreScalingNode) |
| 12. scale scores | 04 (ScoreScalingNode) |
| 13. apply the model to test and OOT data | 04 (ApplyWoeMappingNode, ApplyModelNode) |
| 14. calculate validation metrics | 04 (ValidationMetricsNode, CutoffAnalysisNode) |
| 15. export scoring code | 04 (PythonScoringExportNode, SqlScoringExportNode) — parity test preserved |
| 16. generate an audit package | 06 (ExportAuditPack use case) + 07b |
| 17. replay a committed plan | 05 (SubmitRun on same version) |
| 18. verify scoring parity | 07g (final gate) |
| 19. verify artifact hashes | 02 (artifact store hashing) + 07g (audit integrity test) |
| 20. verify canonical manifest consistency | 05 (FinalizeRun manifest) + 07g (test_run_audit_integrity.py passes) |
