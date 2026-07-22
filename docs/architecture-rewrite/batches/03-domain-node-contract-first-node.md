# Batch 03 — Domain Moves + Node Contracts + Port First Node

```text
You are implementing one bounded batch of the Cardre architecture rewrite.

Do not redesign the wider system.

Do not broaden the scope.

Inspect the current repository before editing because earlier batches may already have changed the paths referenced here.

Preserve validated mathematical and product behaviour, but do not preserve obsolete internal APIs or compatibility layers.

Complete this batch fully, including tests and deletion of code superseded within its scope.
```

## 1. Task objective

Move the pure domain content to its final resting places, introduce the new node contract (`NodeDefinition`, `NodeContext`, `InputCollection`, `OutputPublisher`, `NodeResult`), port the evidence adapters to real adapters behind `ArtifactReader`, and port `LogisticRegressionNode` as the first proof of the new contract. The logistic regression parity test must pass.

## 2. Repository context

Read `docs/architecture-rewrite/04-node-and-execution-runtime.md` (full node contract), `02-domain-and-use-cases.md` (domain model), `01-target-architecture.md` (evidence split). Existing: `cardre/domain/` (pure), `cardre/_evidence/kinds.py`, `schemas.py`, `profiles.py`, `adapters/__init__.py`, `adapters/_base.py`, `reader.py` (`ArtifactEvidenceReader(store)`), `cardre/nodes/contracts.py` (`NodeType`, `ArtifactContract`, `RolePolicy`), `cardre/nodes/build/models.py:LogisticRegressionNode`, `cardre/node_parameters.py`, `cardre/nodes/build/_logit_helpers.py`, `cardre/nodes/build/scoring_export_ir.py` (pure).

## 3. Why the batch exists

This batch proves the node contract works with the canonical fit node. If `LogisticRegressionNode` ports cleanly and `test_logistic_regression_known_input.py` passes, the contract is validated for the family. Evidence adapters become real adapters (no `ProjectStore`).

## 4. Current relevant architecture

`LogisticRegressionNode.run(context)` (`models.py:33`): constructs `ArtifactEvidenceReader(context.store)`, calls `context.require_train_artifact()`, `context.target_metadata()`, `reader.read_optional(..., SELECTION_DEFINITION)`, `reader.read_dataframe(train_artifact)`, fits sklearn LogisticRegression, calls `write_json_artifact(store, artifact_type="model", role="model", payload=model, metadata={"schema_version": SCHEMA_MODEL_ARTIFACT})`, returns `NodeOutput(artifacts=[artifact], metrics=...)`. `ExecutionContext` has `store: ProjectStore`. `_evidence/adapters/__init__.py:EVIDENCE_ADAPTERS` is a module-level dict; `parse` callables take `(Path, ArtifactRef, ProjectStore)`.

## 5. Target architecture after the batch

- `cardre/domain/evidence/kinds.py` (moved from `_evidence/kinds.py`), `cardre/domain/evidence/schemas.py` (moved from `_evidence/schemas.py`). `cardre/_evidence/` deleted (or left empty; deleted in 09).
- `cardre/adapters/evidence/profiles.py` (moved from `_evidence/profiles.py`), `cardre/adapters/evidence/parsers.py` (moved from `_evidence/adapters/__init__.py` + `_base.py`; `parse` callables take `(bytes_or_path, ArtifactRef, ArtifactReader)` — no `ProjectStore`).
- `cardre/adapters/evidence/reader.py`: `EvidenceReader` implementing `InputCollection`-style reads against `ArtifactReader` + adapter registry. (Or `InputCollection` is built in `application/execution/` using `EvidenceReader` — decide based on cleanliness.)
- `cardre/nodes/contracts.py`: `NodeDefinition`, `NodeContext`, `InputCollection` (Protocol), `OutputPublisher` (Protocol), `NodeResult`, `ArtifactContract`, `ArtifactRoleSpec`, `NodeType` (ABC with `__definition__` + `run(context: NodeContext) -> NodeResult`).
- `cardre/nodes/parameters.py` (moved from `cardre/node_parameters.py`).
- `cardre/nodes/build/models.py:LogisticRegressionNode` rewritten to take `NodeContext`, use `context.inputs.read_dataframe(art)`, `context.inputs.read_optional(art, EvidenceKind.MODELLING_METADATA)`, `context.outputs.publish_json(role="model", kind=EvidenceKind.MODEL_ARTIFACT, payload=model, metadata=...)`, return `NodeResult`.
- `cardre/nodes/build/_logit_helpers.py` preserved (pure).
- `tests/test_logistic_regression_known_input.py` passes against the ported node (using a test `NodeContext` with in-memory `InputCollection` + `OutputPublisher` backed by `FsArtifactStore` + `SqliteUnitOfWork`).
- Old `cardre/_evidence/reader.py:ArtifactEvidenceReader` deleted (replaced by `EvidenceReader`/`InputCollection`).
- Old `cardre/nodes/contracts.py` content replaced (the old `NodeType`/`ArtifactContract`/`RolePolicy` removed; `RolePolicy` deleted entirely — unused).
- `cardre/node_parameters.py` deleted (moved to `nodes/parameters.py`).

## 6. Exact scope

- Move `cardre/_evidence/kinds.py` → `cardre/domain/evidence/kinds.py`; `cardre/_evidence/schemas.py` → `cardre/domain/evidence/schemas.py`. Update imports everywhere.
- Move `cardre/_evidence/profiles.py` → `cardre/adapters/evidence/profiles.py`; `cardre/_evidence/adapters/__init__.py` + `_base.py` → `cardre/adapters/evidence/parsers.py`. Change `parse` callable signature from `(Path, ArtifactRef, ProjectStore)` to `(Path, ArtifactRef, ArtifactReader)` (or `(bytes, ArtifactRef)` — decide; `ArtifactReader` is cleaner since some parsers need to read other artifacts). Most adapters ignore `store` already; only `parquet_has_columns` uses `store.artifact_path` — change to `artifact_reader.resolve_path(art)`.
- Write `cardre/adapters/evidence/reader.py:EvidenceReader` — wraps `ArtifactReader` + adapter registry; methods `find(artifacts, kind)`, `find_optional`, `read(artifact_id, kind)`, `read_optional`, `read_dataframe(art)`, `read_step_output_optional(run_step_id, kind)` (the last needs `RunStepRepoPort` — so `EvidenceReader` takes `ArtifactReader` + `ArtifactRepoPort` + `RunStepRepoPort`). This is the adapter-internal helper; use cases/nodes use `InputCollection` which wraps it.
- Write `cardre/application/execution/input_collection.py:StepInputCollection` implementing `InputCollection` Protocol — wraps `EvidenceReader` + the step's `input_artifacts`. Methods: `by_role`, `by_kind`, `first`, `require`, `read`, `read_optional`, `read_dataframe`, `target_metadata`, `find_frozen_bundle`.
- Write `cardre/application/execution/output_publisher.py:StagingOutputPublisher` implementing `OutputPublisher` Protocol — wraps `StagedArtifactWriter` + the node's `output_contract`. Validates role against contract; stages; returns `ArtifactRef` (provisional). Collects `staged_artifacts`, `metrics`, `warnings`, `execution_fingerprint`. Produces `NodeResult` via `build_result()`.
- Write `cardre/nodes/contracts.py` with `NodeDefinition`, `NodeContext`, `InputCollection`, `OutputPublisher`, `NodeResult`, `ArtifactContract`, `ArtifactRoleSpec`, `NodeType` (ABC).
- Move `cardre/node_parameters.py` → `cardre/nodes/parameters.py`. Update imports.
- Port `LogisticRegressionNode`:
  - `__definition__ = NodeDefinition(node_type="cardre.logistic_regression", version="1", category="fit", description=..., input_contract=ArtifactContract(roles=(ArtifactRoleSpec("train", required=True, kinds=("modelling_metadata","bin_definition","selection_definition")), ArtifactRoleSpec("definition", required=False))), output_contract=ArtifactContract(roles=(ArtifactRoleSpec("model", required=True, kinds=("model_artifact",)),)), parameter_schema=..., optional_dependencies=())`.
  - `run(self, context: NodeContext) -> NodeResult`: use `context.inputs.require("train", "cardre.logistic_regression")`, `context.inputs.target_metadata()`, `context.inputs.read_optional(art, EvidenceKind.SELECTION_DEFINITION)`, `context.inputs.read_dataframe(train_art)`, fit, `context.outputs.publish_json(role="model", kind=EvidenceKind.MODEL_ARTIFACT, payload=model, metadata={"schema_version": SCHEMA_MODEL_ARTIFACT, ...})`, `context.outputs.add_metric(...)`, return `context.outputs.build_result()`.
- Update `tests/test_logistic_regression_known_input.py` to construct a `NodeContext` with `StepInputCollection` + `StagingOutputPublisher` backed by temp `FsArtifactStore` + `SqliteUnitOfWork`, run the node, assert the model artifact payload matches the golden (or known input) expectations.
- Update `tests/test_evidence_adapters.py` to use `ArtifactReader` port instead of `ProjectStore`; assert parsers don't import `ArtifactEvidenceReader` (preserved ban); assert no `summarise` method (preserved ban).
- Delete `cardre/_evidence/reader.py`, `cardre/_evidence/adapters/_base.py`, `cardre/_evidence/adapters/__init__.py` (moved), `cardre/_evidence/profiles.py` (moved), `cardre/_evidence/kinds.py` (moved), `cardre/_evidence/schemas.py` (moved). Leave `cardre/_evidence/__init__.py` as empty or delete the dir.
- Delete `cardre/node_parameters.py` (moved to `nodes/parameters.py`).
- Delete `cardre/nodes/contracts.py:RolePolicy` (unused).

## 7. Files to inspect first

- `cardre/_evidence/kinds.py`, `schemas.py`, `profiles.py`, `adapters/__init__.py`, `adapters/_base.py`, `reader.py` — the evidence layer being moved.
- `cardre/nodes/contracts.py` — current contract being replaced.
- `cardre/nodes/build/models.py:LogisticRegressionNode` — the node being ported.
- `cardre/nodes/build/_logit_helpers.py` — preserved pure helpers.
- `cardre/node_parameters.py` — being moved.
- `cardre/execution/context.py:ExecutionContext` — the old context being replaced.
- `tests/test_logistic_regression_known_input.py` — the parity oracle.
- `tests/test_evidence_adapters.py` — the adapter parity tests.

## 8. Files likely to change

- `cardre/domain/evidence/__init__.py` (new), `kinds.py` (moved), `schemas.py` (moved)
- `cardre/adapters/evidence/__init__.py` (new), `profiles.py` (moved), `parsers.py` (moved+rewritten), `reader.py` (new `EvidenceReader`)
- `cardre/application/execution/__init__.py` (new), `input_collection.py` (new), `output_publisher.py` (new)
- `cardre/nodes/contracts.py` (rewritten)
- `cardre/nodes/parameters.py` (moved from `node_parameters.py`)
- `cardre/nodes/build/models.py` (LogisticRegressionNode rewritten)
- All files importing `cardre._evidence.kinds` / `cardre.node_parameters` / `cardre.nodes.contracts` — update imports.
- `tests/test_logistic_regression_known_input.py` (update to NodeContext)
- `tests/test_evidence_adapters.py` (update to ArtifactReader)
- `cardre/_evidence/` (empty or deleted)

## 9. Files likely to create

- `cardre/domain/evidence/` package
- `cardre/adapters/evidence/` package
- `cardre/application/execution/` package
- `cardre/application/execution/input_collection.py`, `output_publisher.py`

## 10. Files likely to delete

- `cardre/_evidence/reader.py`, `adapters/_base.py`, `adapters/__init__.py`, `profiles.py`, `kinds.py`, `schemas.py` (moved)
- `cardre/_evidence/__init__.py` (or leave empty)
- `cardre/node_parameters.py` (moved)
- `cardre/nodes/contracts.py:RolePolicy` (unused)

## 11. Required implementation sequence

1. Move `cardre/_evidence/kinds.py` → `cardre/domain/evidence/kinds.py` (content unchanged). Move `cardre/_evidence/schemas.py` → `cardre/domain/evidence/schemas.py`. Update all imports (`from cardre._evidence.kinds import` → `from cardre.domain.evidence.kinds import`).
2. Move `cardre/_evidence/profiles.py` → `cardre/adapters/evidence/profiles.py`. The `EVIDENCE_PROFILES` dict is unchanged. Update its import: it imports `SCHEMA_BIN_DEFINITION` from `cardre.engine.binning.definition` — after step 1b below, change to `from cardre.domain.binning.definition import SCHEMA_BIN_DEFINITION`.
1b. **Move `cardre/engine/binning/` → `cardre/domain/binning/`** (per D19). Move `woe.py`, `definition.py`, `diagnostics.py`, `capabilities.py` to `cardre/domain/binning/`. These are pure domain logic (no I/O, no store). Move `optbinning_adapter.py` to `cardre/nodes/build/_optbinning_adapter.py` (it imports the `optbinning` optional dep — node-support). Update all 10 import sites: `cardre/services/manual_binning_service.py`, `cardre/_evidence/profiles.py` (already moving to `adapters/evidence/`), `cardre/_evidence/models/binning.py`, `cardre/nodes/build/_fine_classing.py`, `cardre/nodes/build/manual.py`, `cardre/nodes/build/features.py`, `cardre/nodes/build/_optbinning.py`, `cardre/readiness/step_requirements.py`. Delete `cardre/engine/`.
1c. **Move `cardre/workflows/scorecard.py` → `cardre/domain/plans/scorecard_pathway.py`** (per D19). `build_canonical_scorecard_steps` + `canonical_scorecard_step_ids` are the canonical 13-step scorecard build graph — domain knowledge. Update 5 test import sites. Delete `cardre/workflows/`.
3. Move `cardre/_evidence/adapters/__init__.py` + `_base.py` → `cardre/adapters/evidence/parsers.py`. Change `AdapterSpec.parse: Callable[[Path, ArtifactRef, ProjectStore], Any]` → `Callable[[Path, ArtifactRef, ArtifactReader], Any]`. Update `parquet_has_columns` to use `artifact_reader.resolve_path(art)` instead of `store.artifact_path(art)`. Update `candidate_passes_payload_check` similarly. `match(artifacts, profile, artifact_reader)`. Update `EVIDENCE_ADAPTERS` dict literal — all 42 entries. Most lambdas ignore the third arg; update signature anyway.
4. Write `cardre/adapters/evidence/reader.py:EvidenceReader` — `__init__(artifact_reader: ArtifactReader, artifact_repo: ArtifactRepoPort, run_step_repo: RunStepRepoPort)`. Methods: `find(artifacts, kind)`, `find_optional`, `read(artifact_id, kind)`, `read_optional`, `read_dataframe(art)` (uses `artifact_reader.read_bytes` + polars), `read_step_output_optional(run_step_id, kind)` (uses `run_step_repo` + `artifact_repo`). Delegate matching/parsing to `parsers.match` + `AdapterSpec.parse`.
5. Write `cardre/application/ports/evidence_reader.py:EvidenceReaderPort` Protocol (or fold into `InputCollection` — decide; recommend a port so use cases can read evidence without a node context). Actually `InputCollection` is the node-facing interface; `EvidenceReader` is the adapter. Use cases that need evidence (e.g. `ExplainStaleness`, `RefreshComparison`) use `EvidenceReaderPort`. Define it.
6. Write `cardre/nodes/contracts.py`:
   - `ArtifactRoleSpec` (frozen dataclass: `role`, `required=True`, `kinds: tuple[str,...]=()`, `media_types: tuple[str,...]=()`).
   - `ArtifactContract` (frozen: `roles: tuple[ArtifactRoleSpec,...]`).
   - `NodeDefinition` (frozen: `node_type`, `version`, `category`, `description`, `input_contract`, `output_contract`, `parameter_schema`, `optional_dependencies`, `tier`).
   - `NodeContext` (frozen: `run_id`, `plan_version_id`, `step_spec`, `inputs: InputCollection`, `outputs: OutputPublisher`, `params: JsonDict`, `runtime: RuntimeMeta`, `logger`).
   - `InputCollection` Protocol (`by_role`, `by_kind`, `first`, `require`, `read`, `read_optional`, `read_dataframe`, `target_metadata`, `find_frozen_bundle`).
   - `OutputPublisher` Protocol (`publish_json`, `publish_table`, `publish_bytes`, `add_metric`, `add_warning`, `set_execution_fingerprint`, `build_result`).
   - `NodeResult` (dataclass: `staged_artifacts`, `metrics`, `execution_fingerprint`, `warnings`).
   - `NodeType` (ABC: `__definition__: NodeDefinition`, `run(self, context: NodeContext) -> NodeResult`, `validate_params`).
7. Move `cardre/node_parameters.py` → `cardre/nodes/parameters.py`. Update all imports.
8. Write `cardre/application/execution/input_collection.py:StepInputCollection` — `__init__(input_artifacts: list[ArtifactRef], reader: EvidenceReader)`. Implement all `InputCollection` methods. `target_metadata()` finds `MODELLING_METADATA` and builds `TargetMeta` (port from `execution/context.py:ExecutionContext.target_metadata`).
9. Write `cardre/application/execution/output_publisher.py:StagingOutputPublisher` — `__init__(output_contract: ArtifactContract, writer: StagedArtifactWriter, step_id, run_id)`. `publish_json(role, kind, payload, metadata)`: validate `role` in contract (raise `OUTPUT_CONTRACT_VIOLATION` if not), call `writer.stage_json(...)`, append to `staged_artifacts`, return `ArtifactRef` (provisional). `build_result()` returns `NodeResult`.
10. Port `LogisticRegressionNode` per §5.
11. Update `tests/test_logistic_regression_known_input.py`:
    - Build a temp project (`SqliteProjectProvisioner.initialize`).
    - Build `FsArtifactStore(root)`, `SqliteUnitOfWorkFactory`, open UoW, insert a train artifact (parquet) + `MODELLING_METADATA` artifact + `BIN_DEFINITION` artifact via `ArtifactRepo`.
    - Build `StepInputCollection([train_art, meta_art, bin_art], EvidenceReader(artifact_reader, artifact_repo, run_step_repo))`.
    - Build `StagingOutputPublisher(node_def.output_contract, artifact_store, step_id, run_id)`.
    - Build `NodeContext(...)` and call `node.run(context)`.
    - Assert `NodeResult.staged_artifacts` has one `model` artifact; publish it; assert the payload matches the known-input expectations (coefficients, intercept, feature_contract).
12. Update `tests/test_evidence_adapters.py`:
    - Replace `ProjectStore` with `ArtifactReader` (use `FsArtifactStore` as the reader).
    - Keep the parity assertions (adapter match + parse == reader find + read).
    - Keep the `test_adapters_do_not_import_artifact_evidence_reader` ban (update: adapters must not import `EvidenceReader` either — they're below it).
    - Keep the `test_adapters_do_not_implement_summarise` ban.
13. Update all imports across the codebase for moved modules.
14. Run `make preflight` + focused tests.

## 12. Interfaces and invariants

- `NodeContext` has no `store`. Nodes cannot reach `ProjectStore`, `sqlite3`, or env.
- `InputCollection.read(kind)` returns typed evidence (domain dataclasses from adapters).
- `OutputPublisher.publish_*` validates role against `output_contract`; stages (no DB write); returns provisional `ArtifactRef`.
- `NodeResult.staged_artifacts` is what `ExecuteRun` (Batch 05) will publish + register.
- `EvidenceKind` enum preserved (42 kinds). `SCHEMA_*` constants preserved.
- `normalize_node_params` preserved (from `nodes/parameters.py`).

## 13. Behaviour to preserve

- `LogisticRegressionNode` output payload shape (model_family, feature_contract, model_payload, training, warnings) — `test_logistic_regression_known_input.py` is the oracle.
- Evidence adapter matching (two-phase: schema_version first, then role/type/media) — `test_evidence_adapters.py` parity.
- `normalize_node_params` validation rules.

## 14. Intentional breaking changes

- `ExecutionContext` removed (replaced by `NodeContext`).
- `NodeOutput` removed (replaced by `NodeResult`).
- `ArtifactEvidenceReader` removed (replaced by `EvidenceReader` + `InputCollection`).
- `RolePolicy` removed (unused).
- `parse(Path, ArtifactRef, ProjectStore)` signature → `parse(Path, ArtifactRef, ArtifactReader)`.

## 15. Tests to add or update

- `tests/test_logistic_regression_known_input.py` — rewritten for `NodeContext`; must pass.
- `tests/test_evidence_adapters.py` — rewritten for `ArtifactReader`; parity + ban tests preserved.
- `tests/nodes/test_contracts.py` (new) — assert `NodeDefinition` frozen, `NodeContext` frozen, `OutputPublisher` rejects undeclared role (`OUTPUT_CONTRACT_VIOLATION`), `InputCollection.require` raises `MissingInputArtifactError`.
- `tests/application/execution/test_input_collection.py` — `target_metadata`, `find_frozen_bundle`, `by_role`, `read_dataframe`.
- `tests/application/execution/test_output_publisher.py` — staging, role validation, `build_result`.

## 16. Commands to run

```bash
. .venv/bin/activate
ruff check --fix
python3 -m importlinter --config .importlinter
make preflight
python3 -m pytest tests/test_logistic_regression_known_input.py tests/test_evidence_adapters.py tests/nodes tests/application/execution -q
python3 -m pytest tests/ -q   # full suite — watch for import-breakage from the moves
```

## 17. Acceptance criteria

- `test_logistic_regression_known_input.py` passes (model payload matches).
- `test_evidence_adapters.py` passes (parity + bans).
- `nodes/contracts.py` defines `NodeContext` with no `store` field; grep confirms no `context.store` in `cardre/nodes/**`.
- `cardre/_evidence/` is empty or deleted; all imports updated.
- `cardre/node_parameters.py` deleted; `nodes/parameters.py` in place.
- `make arch-check` passes (`nodes` doesn't import `application`/`adapters`/`store`).
- `make preflight` passes (coverage ≥60%).
- `RolePolicy` gone (grep confirms).

## 18. Architecture rules

- `nodes/**` imports only `domain/`, `nodes.contracts`, `nodes.parameters`, third-party numerical.
- `adapters/evidence/**` imports only `domain/evidence/`, `application/ports/`, stdlib, polars.
- `application/execution/**` imports only `domain/`, `application/ports/`, `nodes.contracts` (for `NodeContext`/`InputCollection` types — or define them in `application/ports/` and `nodes` imports from there; decide and be consistent. Recommend: `NodeContext`/`InputCollection`/`OutputPublisher` Protocols in `nodes/contracts.py`; `StepInputCollection`/`StagingOutputPublisher` implementations in `application/execution/` importing `nodes.contracts`).
- No `ProjectStore` in `nodes/`, `application/execution/`, `adapters/evidence/`.

## 19. Prohibited shortcuts

- Do not leave `context.store` as a hidden field on `NodeContext`.
- Do not let `InputCollection` expose `store` or `ArtifactRepository`.
- Do not let `OutputPublisher` write to DB (only stage).
- Do not change the logistic regression maths (coefficients, intercept, feature_contract).
- Do not change evidence adapter matching logic.
- Do not skip the `OUTPUT_CONTRACT_VIOLATION` enforcement.
- Do not keep `cardre/_evidence/` as a re-export shim — clean move.

## 20. Explicit out-of-scope work

- Porting other nodes (Batch 04).
- Execution runtime / `ExecuteRun` (Batch 05).
- Use cases (Batch 05–07).
- Routes (Batch 07).
- Deleting old `cardre/execution/context.py` (done here since `ExecutionContext` is replaced — but old `executor.py`/`step_runner.py` still reference it; they're rewritten in Batch 05. For this batch, leave old `execution/context.py` in place but unused by the new node. Actually: the old `ExecutionContext` is imported by old `step_runner.py`/`executor.py` which are still the live execution path. Do NOT delete `execution/context.py` yet — Batch 05 rewrites those. This batch only adds the new `NodeContext` and ports LogisticRegression to it; the old execution path is dormant for this node but still exists for others.)

## 21. Expected final report format

1. `test_logistic_regression_known_input.py` pass/fail.
2. `test_evidence_adapters.py` pass/fail.
3. Grep confirming no `context.store` in `cardre/nodes/**`.
4. Grep confirming no `cardre._evidence` imports remain.
5. `make preflight` + `make arch-check` summary.
6. Files moved/created/deleted.

## Identity

- Sequence: 03
- Title: Domain Moves + Node Contracts + Port First Node
- Architectural objective: prove the node contract with the canonical fit node; evidence adapters become real adapters
- Reason for position: nodes need the contract before bulk porting; evidence adapters needed by InputCollection
- Difficulty: very high — contract design + first port + evidence move

## Scope summary

- Created: `domain/evidence/`, `adapters/evidence/`, `application/execution/`, `nodes/contracts.py` (rewritten), `nodes/parameters.py` (moved), ported `LogisticRegressionNode`, `StepInputCollection`, `StagingOutputPublisher`, `EvidenceReader`, tests.
- Changed: all files importing moved modules.
- Deleted: `cardre/_evidence/` (moved), `cardre/node_parameters.py` (moved), `RolePolicy`.
- Behaviour preserved: logistic regression output, evidence matching, param validation.
- Behaviour changed: `ExecutionContext`→`NodeContext`, `NodeOutput`→`NodeResult`, `parse` signature.
- Exclusions: other nodes (05), execution (06), use cases (06–07), routes (08), old execution path still present.

## Design decisions

- D4 (evidence split), D9 (NodeContext no store), D2 (preserve vocabulary), D13 (enforcement).

## Tests

See §15.

## Acceptance criteria

See §17.

## Risks

- R2 (parity drift in logistic), R13 (evidence adapter store removal), R21 (NodeContext too restrictive), R17 (`cardre/engine/binning/` move — 10 import sites; `optbinning_adapter.py` is the one piece that goes to `nodes/build/` not `domain/`).

## Agent boundaries

Do not modify: `cardre/services/`, `cardre/store/`, `cardre/execution/executor.py`/`step_runner.py`/`run_lifecycle.py`/`worker.py` (Batch 05), `cardre/api/**` (Batch 07), other nodes (Batch 04), `cardre/config.py`, `cardre/artifacts.py` (old, dormant), frontend, sidecar.

## Dependencies

- Required earlier: Batch 02 (artifact store, UoW, query objects for EvidenceReader).
- Optional parallel: Batch 04 node ports can be designed in parallel but need this contract.
- Open PRs: none.

## Estimated reasoning difficulty

very high.