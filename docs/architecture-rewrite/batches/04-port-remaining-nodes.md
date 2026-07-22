# Batch 04 — Port Remaining Launch Nodes

```text
You are implementing one bounded batch of the Cardre architecture rewrite.

Do not redesign the wider system.

Do not broaden the scope.

Inspect the current repository before editing because earlier batches may already have changed the paths referenced here.

Preserve validated mathematical and product behaviour, but do not preserve obsolete internal APIs or compatibility layers.

Complete this batch fully, including tests and deletion of code superseded within its scope.
```

## 1. Task objective

Port the remaining 30 launch nodes from `ExecutionContext(store)` to `NodeContext(inputs, outputs)`. Port `modeling/adapters.py` + `serialization.py` to `ArtifactReader`/`ArtifactWriter` ports. Port `_training_utils.py`. Update the node catalogue registration (in `bootstrap/node_catalogue.py`). All parity tests (`test_scoring_export_parity.py`, `test_score_scaling_known_input.py`, `test_golden_fixtures_roundtrip.py`, `test_binning_node.py`, etc.) must pass.

## 2. Repository context

Read `docs/architecture-rewrite/04-node-and-execution-runtime.md` (migration difficulty by family). Batch 03 established `NodeContext`, `InputCollection`, `OutputPublisher`, `NodeResult`, ported `LogisticRegressionNode`, moved evidence adapters. Existing nodes in `cardre/nodes/prep/`, `build/`, `validate/`, `selection/` all use `ExecutionContext.store` + `ArtifactEvidenceReader(context.store)` + `write_*_artifact(store, ...)`.

## 3. Why the batch exists

All launch nodes must be on the new contract before `ExecuteRun` (Batch 05) can run them. This is bulk mechanical work following the pattern Batch 03 proved.

## 4. Current relevant architecture

Each node's `run(context: ExecutionContext) -> NodeOutput`:
- `ArtifactEvidenceReader(context.store)` → `context.inputs.read(kind)` / `context.inputs.read_optional(kind)`.
- `context.require_train_artifact()` → `context.inputs.require("train", node_type)`.
- `context.target_metadata()` → `context.inputs.target_metadata()`.
- `context.find_frozen_bundle()` → `context.inputs.find_frozen_bundle()`.
- `context.data_artifacts()` → `context.inputs.by_role("train","test","oot")`.
- `reader.read_dataframe(art)` → `context.inputs.read_dataframe(art)`.
- `write_json_artifact(store, role=..., payload=...)` → `context.outputs.publish_json(role=..., kind=..., payload=...)`.
- `write_parquet_artifact(store, role=..., frame=...)` → `context.outputs.publish_table(role=..., kind=..., frame=...)`.
- `NodeOutput(artifacts=[...], metrics=...)` → `context.outputs.add_metric(...)` + `context.outputs.build_result()`.
- `NodeFailedWithArtifacts(artifacts=[...])` → stage the artifacts via `context.outputs.publish_*` first, then raise `NodeFailedWithArtifacts(staged_artifacts=[...])` (the exception type is preserved but carries `StagedArtifact`s; `ExecuteRun` finalization handles them).

Special cases:
- `TechnicalManifestExportNode` (`build/export.py`) constructs `PlanRepository`/`RunStepRepository`/`ArtifactRepository` directly and reads the entire run's lineage. **Redesign**: give it a `manifest` input role carrying a `RunSummary` dataclass produced by `ExecuteRun` after all steps (Batch 05 produces this); the node assembles the technical manifest from declared inputs only. If this is too large a redesign for this batch, split: port the other nodes, and defer `TechnicalManifestExportNode` to Batch 05 (where `ExecuteRun` exists to produce the `RunSummary`). **Recommendation: defer `TechnicalManifestExportNode` to Batch 05.**
- `CoefficientSignCheckNode` (`build/diagnostics.py:47`) reads a WOE evidence JSON via raw `store.artifact_path(...).read_text()` (suppressed `low-level-evidence-parser`). Replace with `context.inputs.read_optional(woe_art, EvidenceKind.WOE_IV_EVIDENCE)` — the typed adapter already parses it.
- `ProfileDatasetNode` (`prep/profile.py`) reads parquet via `pl.read_parquet(store.artifact_path(...))` (suppressed `dataset-frame-input`). Replace with `context.inputs.read_dataframe(art)`.
- `ImportTabularDatasetNode` (`prep/import_.py`) reads from `params["source_path"]` (arbitrary host path). Keep the param; read via `pl.read_csv`/`pl.read_parquet` directly (this is the ingest boundary — `source_path` is a user-supplied param, not a project artifact). No `store` access needed.
- `FrozenScorecardBundleNode` (`build/freeze.py`) constructs `ArtifactRepository(store).get(source_artifact_id)` to resolve source artifacts. Replace with `context.inputs.read_artifact(source_artifact_id)` (add this method to `InputCollection` — it reads an arbitrary declared input artifact by id; the node declares these source ids in its input contract or via metadata).

## 5. Target architecture after the batch

- All 30 launch nodes (minus `TechnicalManifestExportNode`, deferred to 06) ported to `NodeContext`.
- `cardre/modeling/adapters.py` (`apply_logistic`, `apply_sklearn_estimator`, `apply_ensemble`) take `ArtifactReader` + `ArtifactWriter` (or `InputCollection`-style helpers) instead of `ProjectStore`.
- `cardre/modeling/serialization.py` (estimator save/load) takes `ArtifactReader`/`ArtifactWriter`.
- `cardre/nodes/_training_utils.py:prepare_supervised_training_data` takes `InputCollection` instead of `context`.
- `cardre/nodes/registry.py` replaced by `bootstrap/node_catalogue.py` (built from `Settings` + node classes; no `from_env()`).
- Each node has `__definition__: NodeDefinition` with input/output contracts.
- Parity tests pass.
- Old `cardre/nodes/registry.py` deleted. Old `cardre/execution/context.py` deleted (no consumers after all nodes ported). Old `cardre/execution/step_runner.py` + `executor.py` still present (dormant; Batch 05 rewrites). Actually — if no node uses `ExecutionContext`, the old `step_runner`/`executor` can't run. **This batch breaks the old execution path intentionally.** Document the broken state: after Batch 04, there is no working execution path until Batch 05. `make preflight` still passes (tests don't require execution); execution-specific tests (`test_executor.py`, `test_run_coordinator.py`) are marked `xfail` or updated.

## 6. Exact scope

- Port each node family (prep, build-fit, build-export minus technical-manifest, validate-apply, selection-deferred):
  - prep: `ImportTabularDatasetNode`, `ProfileDatasetNode`, `ValidateBinaryTargetNode`, `SplitTrainTestOotNode`, `ApplyExclusionsNode`, `ExplicitMissingOutlierTreatmentNode`, `DefineModellingMetadataNode`, `DevelopmentSampleDefinitionNode`.
  - build-fit: `AutomaticBinningNode`, `CalculateWoeIvNode`, `WoeTransformTrainNode`, `ManualBinningNode`, `VariableClusteringNode`, `VariableSelectionNode`, `ScoreScalingNode`, `BuildSummaryReportNode`, `FrozenScorecardBundleNode`, `CoefficientSignCheckNode`, `SeparationDiagnosticsNode`, `VifDiagnosticsNode`, `CalibrationDiagnosticsNode`, `DummyFitNode`, `NoopNode`. (`LogisticRegressionNode` already done in 04.)
  - build-export: `ScorecardTableExportNode`, `PythonScoringExportNode`, `SqlScoringExportNode`. (`TechnicalManifestExportNode` deferred to 06.)
  - validate-apply: `ApplyWoeMappingNode`, `ApplyModelNode`, `ValidationMetricsNode`, `CutoffAnalysisNode`.
  - selection-deferred: `FeatureSelectionFilterNode`, `FeatureSelectionEmbeddedNode`, `ResampleTrainingDataNode`, `SmoteTrainingDataNode` (deferred tier but port the contract so they're ready).
- Port `modeling/adapters.py` + `serialization.py`.
- Port `_training_utils.py`.
- Write `bootstrap/node_catalogue.py:NodeCatalogue` (replaces `NodeRegistry.with_defaults()`); built from `Settings` + node classes.
- Update `tests/test_node_registry_tiers.py` for `NodeCatalogue`.
- Mark execution-path tests (`test_executor.py`, `test_executor_characterization.py`, `test_run_coordinator.py`, `test_run_coordinator_edge_cases.py`, `test_run_lifecycle.py`, `test_run_lifecycle_errors.py`, `test_run_dispatch.py`, `test_worker_lifecycle.py`, `test_action_planning.py`, `test_run_plan_decision.py`, `test_run_step_writer.py`, `test_run_repo_request_fields.py`, `test_launch_pathway.py`, `test_api_scorecard_launch_pathway.py`) as `xfail` with reason "Execution path broken during Batch 04; restored in Batch 05". Or update them to use the new path if Batch 05 lands in the same PR — but they're separate batches, so xfail.
- Delete `cardre/nodes/registry.py`, `cardre/execution/context.py`.

## 7. Files to inspect first

- Each node file (listed in §6).
- `cardre/modeling/adapters.py`, `serialization.py`.
- `cardre/nodes/_training_utils.py`.
- `cardre/nodes/registry.py`.
- Batch 03's `LogisticRegressionNode` port (the pattern to follow).
- `tests/test_scoring_export_parity.py`, `test_score_scaling_known_input.py`, `test_golden_fixtures_roundtrip.py`, `test_binning_node.py`, `test_validation_metrics_node.py`, etc. (the oracles).

## 8. Files likely to change

- All node files in `cardre/nodes/prep/`, `build/`, `validate/`, `selection/`.
- `cardre/modeling/adapters.py`, `serialization.py`.
- `cardre/nodes/_training_utils.py`.
- `cardre/nodes/registry.py` → deleted; replaced by `bootstrap/node_catalogue.py`.
- `cardre/execution/context.py` → deleted.
- `cardre/nodes/__init__.py` (update exports).
- `cardre/nodes/build/__init__.py`, etc. (update exports).
- `tests/test_node_registry_tiers.py` (update for `NodeCatalogue`).
- Execution-path tests (mark xfail).

## 9. Files likely to create

- `cardre/bootstrap/node_catalogue.py` (new).

## 10. Files likely to delete

- `cardre/nodes/registry.py`.
- `cardre/execution/context.py`.

## 11. Required implementation sequence

1. Port `modeling/adapters.py`: `apply_logistic(model, frame, artifact_reader)` and `apply_sklearn_estimator(model, frame, artifact_reader, artifact_writer)` — replace `ProjectStore` params with `ArtifactReader` (for reading estimator/calibrator artifacts by id) + `ArtifactWriter` (for writing scored datasets). The `apply_model` node passes these from `context.inputs`/`context.outputs`.
2. Port `modeling/serialization.py`: `save_estimator_artifact(writer, estimator, metadata)`, `read_estimator_artifact(reader, artifact_id)` — replace `ProjectStore` with `ArtifactReader`/`StagedArtifactWriter`.
3. Port `_training_utils.py:prepare_supervised_training_data(inputs, operation)` — take `InputCollection` instead of `ExecutionContext`; use `inputs.read_dataframe`, `inputs.target_metadata()`, `inputs.read_optional(..., MODELLING_METADATA)`.
4. Port prep nodes (8 nodes) — mechanical: replace `context.store`/`ArtifactEvidenceReader(context.store)`/`write_*_artifact(store,...)` with `context.inputs.*`/`context.outputs.publish_*`. Each gets a `__definition__` with input/output contracts.
5. Port build-fit nodes (15 nodes) — same pattern. `FrozenScorecardBundleNode`: add `context.inputs.read_artifact(source_artifact_id)` (extend `InputCollection` Protocol with `read_artifact(artifact_id) -> ArtifactRef` that reads from `ArtifactRepoPort`). `CoefficientSignCheckNode`: remove raw `store.artifact_path().read_text()`, use `context.inputs.read_optional(woe_art, EvidenceKind.WOE_IV_EVIDENCE)`.
6. Port build-export nodes (3 nodes) — `PythonScoringExportNode`/`SqlScoringExportNode` use `context.inputs.find_frozen_bundle()`, `compile_scorecard` (preserved), `context.outputs.publish_json(role="report", kind=SCORING_EXPORT_PYTHON, payload=...)`.
7. Port validate-apply nodes (4 nodes) — `ApplyModelNode` delegates to ported `modeling/adapters.apply_*`.
8. Port selection-deferred nodes (4 nodes) — same pattern; they're deferred tier but the contract port readies them.
9. Write `bootstrap/node_catalogue.py:NodeCatalogue` — `__init__(settings: Settings, node_classes: list[type[NodeType]])`. `definition(node_type)`, `availability(node_type, settings)` (probe optional deps via `importlib.util.find_spec` against `settings.optional_dep_modules`; tier from `__definition__.tier`), `instantiate(node_type)`, `list_types(tier)`. Build the default catalogue from the 31 launch + 20 deferred classes (same list as current `registry.py:_register_launch_nodes`/`_register_deferred_nodes`).
10. Delete `cardre/nodes/registry.py`, `cardre/execution/context.py`.
11. Mark execution-path tests `xfail`.
12. Run all parity tests + node tests.

## 12. Interfaces and invariants

- Every node has `__definition__: NodeDefinition` with input/output contracts.
- `NodeContext` has no `store`.
- `InputCollection.read_artifact(artifact_id)` added (for `FrozenScorecardBundleNode`).
- `NodeCatalogue.availability` takes `Settings`, not `from_env()`.
- `NodeFailedWithArtifacts` carries `staged_artifacts: list[StagedArtifact]` (not `list[ArtifactRef]`).

## 13. Behaviour to preserve

- Every node's output payload shape (artifact_type, role, schema_version, metadata, metrics).
- `test_scoring_export_parity.py` (Python/SQL/apply-model parity).
- `test_score_scaling_known_input.py`.
- `test_golden_fixtures_roundtrip.py`.
- `test_binning_node.py`, `test_validation_metrics_node.py`, `test_clustering_node.py`, `test_feature_selection.py`, `test_diagnostics_nodes.py`, `test_calibrate_probabilities.py` (deferred but ported).
- `test_node_registry_tiers.py` (launch/deferred counts; availability probing).

## 14. Intentional breaking changes

- Old execution path broken (no `ExecutionContext`); execution tests xfail until Batch 05.
- `NodeRegistry` → `NodeCatalogue`.

## 15. Tests to add or update

- Update each node test to use `NodeContext` (same pattern as Batch 03's logistic test).
- `tests/bootstrap/test_node_catalogue.py` — `NodeCatalogue` builds from `Settings`; availability probes; instantiate.
- Mark execution-path tests xfail.
- `tests/test_node_registry_tiers.py` → `test_node_catalogue_tiers.py`.

## 16. Commands to run

```bash
. .venv/bin/activate
ruff check --fix
python3 -m importlinter --config .importlinter
make preflight
python3 -m pytest tests/test_scoring_export_parity.py tests/test_score_scaling_known_input.py tests/test_golden_fixtures_roundtrip.py tests/test_binning_node.py tests/test_validation_metrics_node.py tests/test_clustering_node.py tests/test_feature_selection.py tests/test_diagnostics_nodes.py -q
python3 -m pytest tests/ -q   # expect xfail on execution-path tests
```

## 17. Acceptance criteria

- All node parity tests pass.
- Grep confirms no `context.store` in `cardre/nodes/**`.
- Grep confirms no `ArtifactEvidenceReader` in `cardre/nodes/**`.
- Grep confirms no `write_json_artifact(store` / `write_parquet_artifact(store` in `cardre/nodes/**`.
- `NodeCatalogue` builds; `availability` works; `instantiate` works.
- `cardre/nodes/registry.py` and `cardre/execution/context.py` deleted.
- `make arch-check` passes.
- `make preflight` passes (coverage ≥60%).
- Execution-path tests xfail (not xpass, not error).

## 18. Architecture rules

- `nodes/**` no `ProjectStore`, no `ArtifactEvidenceReader`, no `write_*_artifact(store)`, no `store.artifact_path`, no `sqlite3`.
- `nodes/**` imports only `domain/`, `nodes.contracts`, `nodes.parameters`, third-party numerical.
- `modeling/**` imports only `domain/`, `application/ports/` (ArtifactReader/Writer), third-party.

## 19. Prohibited shortcuts

- Do not leave any `context.store` access.
- Do not change node maths.
- Do not skip `__definition__` on any node.
- Do not skip the `OUTPUT_CONTRACT_VIOLATION` validation.
- Do not make execution-path tests pass by re-introducing `ExecutionContext`.

## 20. Explicit out-of-scope work

- `TechnicalManifestExportNode` (Batch 05 — needs `RunSummary` input from `ExecuteRun`).
- `ExecuteRun` use case (Batch 05).
- Old `execution/executor.py`/`step_runner.py`/`run_lifecycle.py`/`worker.py` rewrite (Batch 05).
- Use cases for plans/evidence/governance/reporting (Batch 06).
- Routes (Batch 07).

## 21. Expected final report format

1. List of ported nodes (30) with pass/fail of their tests.
2. Parity test results.
3. Grep results confirming no `context.store`/`ArtifactEvidenceReader`/`write_*_artifact(store` in `nodes/`.
4. `NodeCatalogue` test results.
5. xfail test list.
6. `make preflight` + `make arch-check` summary.
7. Files changed/deleted.

## Identity

- Sequence: 04
- Title: Port Remaining Launch Nodes
- Architectural objective: all launch nodes on new contract; old execution path intentionally broken
- Reason for position: must precede Batch 05 (execution) which runs them
- Difficulty: high — bulk mechanical but large surface

## Scope summary

- Created: `bootstrap/node_catalogue.py`; ported node files (rewritten in place).
- Changed: all node files, `modeling/`, `_training_utils.py`, node tests.
- Deleted: `cardre/nodes/registry.py`, `cardre/execution/context.py`.
- Behaviour preserved: all node outputs + parity.
- Behaviour changed: nodes take `NodeContext`; old execution broken.
- Exclusions: `TechnicalManifestExportNode` (06), execution runtime (06), use cases (07), routes (08).

## Design decisions

- D9 (NodeContext), D2 (preserve maths), D4 (evidence adapters).

## Tests

See §15.

## Acceptance criteria

See §17.

## Risks

- R2 (parity drift across many nodes), R21 (NodeContext too restrictive for a node — extend `InputCollection` if needed), R12 (`TechnicalManifestExportNode` deferred — golden report bundle test may xfail until 06), R17 (`_training_utils` import paths).

## Agent boundaries

Do not modify: `cardre/services/`, `cardre/store/`, `cardre/execution/executor.py`/`step_runner.py`/`run_lifecycle.py`/`worker.py` (Batch 05), `cardre/api/**` (Batch 07), `cardre/domain/` (settled), `cardre/config.py`, frontend, sidecar.

## Dependencies

- Required earlier: Batch 03 (contract + first node + evidence adapters).
- Optional parallel: **yes — 4-way parallel.** Split into sub-PRs by family (04a prep, 04b build-fit, 04c build-export, 04d validate-apply) landing concurrently after Batch 03 merges. Land the shared `modeling/` + `_training_utils.py` + `bootstrap/node_catalogue.py` in a tiny pre-PR first, then the four family branches branch off it. Merge as one batch.
- Open PRs: none.

## Estimated reasoning difficulty

high — bulk mechanical, but 30 nodes + parity risk.