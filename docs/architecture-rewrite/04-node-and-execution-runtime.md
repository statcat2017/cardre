# 04 — Node and Execution Runtime

## Node contract

### `NodeDefinition` (in `nodes/contracts.py`)

```python
@dataclass(frozen=True)
class NodeDefinition:
    node_type: str           # e.g. "cardre.logistic_regression"
    version: str              # e.g. "1"
    category: str             # "fit" | "refinement" | "selection" | "apply" | "transform" | "export"
    description: str
    input_contract: ArtifactContract   # declared input roles + optional kinds
    output_contract: ArtifactContract  # declared output roles + required kinds
    parameter_schema: NodeParameterSchema | None
    optional_dependencies: tuple[str, ...] = ()
    tier: Literal["launch", "deferred"] = "launch"
```

`ArtifactContract` is extended from the current `input_roles`/`output_roles` lists to a structured shape:

```python
@dataclass(frozen=True)
class ArtifactRoleSpec:
    role: str                          # "train", "model", "definition", ...
    required: bool = True              # must be present in inputs
    kinds: tuple[str, ...] = ()        # allowed EvidenceKind values (empty = any)
    media_types: tuple[str, ...] = ()  # allowed media types (empty = any)

@dataclass(frozen=True)
class ArtifactContract:
    roles: tuple[ArtifactRoleSpec, ...] = ()
```

For outputs, `required` means the node must produce this role; `kinds` constrains what `OutputPublisher` will accept.

### `NodeContext` (replaces `ExecutionContext`)

```python
@dataclass(frozen=True)
class NodeContext:
    run_id: str
    plan_version_id: str
    step_spec: StepSpec
    inputs: InputCollection
    outputs: OutputPublisher
    params: JsonDict          # normalized, validated
    runtime: RuntimeMeta      # run_id, plan_version_id, step_id, node_type, clock
    logger: LoggerPort
```

**Nodes must NOT receive:** `ProjectStore`, repositories, `sqlite3.Connection`, project-root paths, `os.environ`, FastAPI objects, dispatch infrastructure, `ArtifactEvidenceReader(store)`, arbitrary artifact lookup.

### `InputCollection`

```python
class InputCollection(Protocol):
    def by_role(self, role: str) -> list[ArtifactRef]: ...
    def by_kind(self, kind: EvidenceKind) -> list[ArtifactRef]: ...
    def first(self, role: str) -> ArtifactRef | None: ...
    def require(self, role: str, node_type: str) -> ArtifactRef: ...
    def read(self, artifact: ArtifactRef, kind: EvidenceKind) -> Any: ...   # typed evidence read
    def read_optional(self, artifact: ArtifactRef, kind: kind) -> Any | None: ...
    def read_dataframe(self, artifact: ArtifactRef) -> pl.DataFrame: ...
    def target_metadata(self) -> TargetMeta | None: ...
    def find_frozen_bundle(self) -> ArtifactRef | None: ...
```

Implemented by `adapters/evidence/InputReader` (or an application-internal `StepInputCollection`) backed by `ArtifactReader` + `EvidenceReader` ports. No `store` exposure.

### `OutputPublisher`

```python
class OutputPublisher(Protocol):
    def publish_json(self, *, role: str, kind: EvidenceKind, payload: JsonDict,
                     metadata: JsonDict | None = None) -> ArtifactRef: ...
    def publish_table(self, *, role: str, kind: EvidenceKind, frame: pl.DataFrame,
                      metadata: JsonDict | None = None) -> ArtifactRef: ...
    def publish_bytes(self, *, role: str, kind: EvidenceKind, data: bytes,
                      media_type: str, logical_hash: str,
                      metadata: JsonDict | None = None) -> ArtifactRef: ...
    def add_metric(self, name: str, value: float | int | str | bool) -> None: ...
    def add_warning(self, warning: JsonDict) -> None: ...
    def set_execution_fingerprint(self, fp: JsonDict) -> None: ...
```

- Each `publish_*` call **validates** `role` against `NodeDefinition.output_contract.roles`. If the role is undeclared → `OUTPUT_CONTRACT_VIOLATION`.
- Each `publish_*` call **stages** the artifact (filesystem staging dir) and returns an `ArtifactRef` with `artifact_id`, `physical_hash`, `logical_hash` — but the artifact is not yet visible in `objects/` and not registered in DB. The `ExecuteRun` use case finalization publishes + registers inside a UoW.
- `add_metric`/`add_warning`/`set_execution_fingerprint` populate the `NodeResult`.

### `NodeResult` (replaces `NodeOutput`)

```python
@dataclass
class NodeResult:
    staged_artifacts: list[StagedArtifact]
    metrics: JsonDict
    execution_fingerprint: JsonDict | None
    warnings: list[JsonDict]
```

`StagedArtifact` is an internal handle (not an `ArtifactRef` yet — the `artifact_id` is provisional). On finalization, `ExecuteRun` promotes staged → published → registered.

### `NodeType` ABC

```python
class NodeType(ABC):
    __definition__: NodeDefinition  # class attribute, set by subclass or decorator

    @abstractmethod
    def run(self, context: NodeContext) -> NodeResult: ...

    def validate_params(self, params: JsonDict) -> list[str]:  # cross-field only
        return []
```

`contract()` and `parameter_schema()` accessors delegate to `__definition__`.

### `NodeCatalogue` (replaces `NodeRegistry`)

```python
class NodeCataloguePort(Protocol):
    def definition(self, node_type: str) -> NodeDefinition: ...
    def availability(self, node_type: str, settings: Settings) -> NodeAvailability: ...
    def instantiate(self, node_type: str) -> NodeType: ...
    def list_types(self, tier: str | None = None) -> list[NodeDefinition]: ...
```

`bootstrap/node_catalogue.py` builds a `NodeCatalogue` from the `Settings` + the static list of node classes. **No `CardreConfig.from_env()` inside the catalogue** — `Settings` is passed in. Availability probing of optional deps via `importlib.util.find_spec` against `settings.optional_dep_modules`.

## Enforcement of declared contracts

| Rule | Enforced where | Failure code |
|------|-----------------|-------------|
| Declared input roles | `StepRunner` filters `input_artifacts` by `definition.input_contract.roles` (preserved from current `_filter_input_artifacts`) | `NodeRoleAccessViolation` (preserved) |
| Required input roles present | `StepRunner` checks each `required=True` role is present before calling `node.run` | `MissingInputArtifactError` |
| Declared output roles | `OutputPublisher.publish_*` rejects undeclared roles | `OUTPUT_CONTRACT_VIOLATION` (new) |
| Required outputs produced | `StepRunner` checks each `required=True` output role has ≥1 staged artifact after `node.run` returns | `OUTPUT_CONTRACT_VIOLATION` |
| Output schema versions | `OutputPublisher.publish_json` sets `schema_version` from `kind`; rejects mismatch with `ArtifactRoleSpec.kinds` | `OUTPUT_CONTRACT_VIOLATION` |
| Duplicate roles | allowed (a node may produce two artifacts with the same role, e.g. train + train) | — |
| Attempt ownership | each `publish_*` call is recorded against `step_id`/`run_id`; a node cannot publish on behalf of another step | enforced by `OutputPublisher` being scoped to the current `NodeContext` |
| Metrics | `add_metric` types restricted to float/int/str/bool | `TypeError` |
| Warnings | `add_warning` must be a dict with `code` + `message` | `ValueError` |
| Diagnostics | on failure, `StepRunner` builds the error entry via `classify_step_failure` (preserved) | — |
| Execution fingerprints | `build_execution_fingerprint` (preserved) + `node_result.execution_fingerprint` merge (preserved) | — |

## Node catalogue

Built in `bootstrap/node_catalogue.py` from the static list of node classes (same 31 launch + 20 deferred as today). The catalogue is a frozen dict built once at bootstrap. No module-level singleton.

## Execution lifecycle

### State machine (D10)

```
submitted → running → {succeeded | failed | cancelled | interrupted}
```

(Drops `created`/`queued`. `submitted` is a transient in-memory state before the `INSERT`.)

Transitions enforced by `RunStatus._check_transition` (preserved, pruned) + `RunRepository.transition` compare-and-set (preserved).

### Sequence (D8, D14)

```
SubmitRun:
    validate (version exists, committed, governance, no concurrent run)
    open UoW (IMMEDIATE):
        sweep stale running runs → finalise each as INTERRUPTED
        insert run row (status="running", cancel_requested=0)
        commit
    return Run

ExecuteRun (called sync by SubmitRun if sync=True, or by RunDispatcher):
    RunLifecycle.start(uow, run_id): validate run is running, version matches
    PlanExecutor.load_and_validate(plan_version_id): steps, topology, availability
    for each action in topological order:
        if run.cancel_requested: finalise as CANCELLED; break
        heartbeat (UoW, UPDATE runs SET heartbeat_at=?)
        StepRunner.run_step(spec, ...):
            resolve inputs from parent step outputs
            instantiate node via catalogue
            normalize + validate params
            build NodeContext (inputs from InputCollection, outputs from OutputPublisher)
            node.run(context) → NodeResult
            validate declared outputs produced
            build execution fingerprint
            return StepExecutionResult
        open UoW (IMMEDIATE) for finalization:
            for staged in result.staged_artifacts:
                artifact_store.publish(staged)   # os.replace staging → objects
                uow.artifacts.register(...)     # INSERT dedup
                uow.lineage.register_lineage(...,"output")
            uow.run_steps.insert(run_step)
            uow.evidence.insert_edges(...)
            uow.evidence.insert_artifacts(...)
            uow.runs.heartbeat(run_id)
            commit
        if step failed: finalise as FAILED with diagnostic; break
    FinalizeRun:
        build manifest payload
        open UoW (IMMEDIATE):
            write manifest to manifests/runs/{run_id}.json (atomic temp+replace)
            uow.runs.transition(run_id, status, expected_from=("running",))
            commit
        (if transition fails: re-read status, rewrite manifest, raise)
```

### Failure points and recoverable state

| Failure point | State | Recovery |
|---------------|-------|----------|
| SubmitRun validation | no run row | return error; no cleanup |
| Stale sweep fails | stale runs remain; new run not created | next SubmitRun retries sweep |
| Run insert fails (commit error) | no run row | return error |
| Sync dispatch: node fails before staging | no artifacts staged; staging dir has orphan tmps | startup sweep cleans `.staging/` |
| Node fails after staging, before returning | staged artifacts not promoted; NodeFailedWithArtifacts carries staged refs | finalization UoW records them as output_artifact_ids of FAILED step (preserved behaviour) |
| Finalization UoW commit fails | published files in `objects/` orphan; run_step not recorded | gc sweeps orphan objects; run remains `running` → heartbeat stale → sweep on next submit |
| Manifest write fails | run not finalised | FinalizeRun retries; if still fails, finalise as FAILED with `RUN_FINALISATION_FAILED` |
| Transition fails (compare-and-set lost) | another finalizer already transitioned | re-read, rewrite manifest, raise `RUN_ALREADY_FINALISED` (preserved) |
| Worker process crash mid-step | run `running`, heartbeat stale | next SubmitRun sweeps → INTERRUPTED |
| `cancel_requested` set during step | next loop iteration checks, finalises CANCELLED | cooperative |

### Cancellation (D14)

- `CancelRun` use case: open UoW, `UPDATE runs SET cancel_requested=1 WHERE run_id=? AND status='running'`. Commit.
- `PlanExecutor` checks `run.cancel_requested` at the top of each step loop iteration (before heartbeat). If set, finalise as CANCELLED with diagnostic `RUN_CANCELLED_BY_USER`. No thread interrupt.
- If the run is between steps when cancelled, the next step does not execute.
- If a node is currently running, cancellation takes effect after the node returns (cooperative). Long nodes (clustering) may take minutes to observe the cancel — acceptable.
- `cancel_requested` is also visible in the run summary so the frontend can show "cancelling...".

### Interruption

- Stale heartbeat detected by `SubmitRun._sweep_stale_running_runs`: finalise as INTERRUPTED with diagnostic `RUN_RECOVERED_STALE`.
- `RunWorker._record_failure` on uncaught exception: finalise as FAILED with `RUN_WORKER_FAILED`.

## Manifest lifecycle

1. `FinalizeRun` builds `build_manifest_payload(run_id, ...)` (preserved from `run_lifecycle.py:48`).
2. Sets `manifest_hash=""`, computes `json_logical_hash(payload)`, sets `manifest_hash`.
3. Validates `RunManifest` pydantic (preserved).
4. Writes to `manifests/runs/{run_id}.json` via atomic temp+`os.replace` (preserved, path changed).
5. `uow.runs.transition(run_id, status, expected_from=("running",))`.
6. On transition failure: re-read status, rewrite manifest with actual status, raise `RUN_ALREADY_FINALISED`.

`assert_run_audit_integrity` (preserved test) verifies the manifest hash recomputes and the file matches DB state.

## Migration difficulty by node family

| Family | Nodes | Difficulty | Reason |
|--------|-------|------------|--------|
| prep | import, profile, split, treatment, metadata, exclusions, sample-definition | moderate | import reads external path (keep via param); profile/split read parquet via store (port to `InputCollection.read_dataframe`); rest use `ArtifactEvidenceReader(store)` → `InputCollection.read(kind)` |
| build (fit) | logistic, score-scaling, build-summary, freeze, automatic-binning, calculate-woe-iv, woe-transform, manual-binning, variable-clustering, variable-selection, diagnostics | high | heavy `ArtifactEvidenceReader(store)` + `write_*_artifact(store)` usage; `TechnicalManifestExportNode` reads entire run lineage (needs new `manifest` input role carrying run summary); `CoefficientSignCheckNode` has raw path read (remove) |
| build (export) | scorecard-table, scoring-export-python/sql | moderate | `context.find_frozen_bundle()` → `InputCollection.find_frozen_bundle()`; `compile_scorecard` preserved |
| validate (apply) | apply-woe-mapping, apply-model, validation-metrics, cutoff-analysis | moderate | `ArtifactEvidenceReader(store)` + `modeling/adapters` (which take store) → port to `InputCollection` + `ArtifactReader`/`ArtifactWriter` ports |
| selection (deferred) | feature-selection-filter/embedded, resampling, smote | moderate | `_training_utils.prepare_supervised_training_data` takes `context` → port to `InputCollection` |
| boosting/ensembles/calibrate/explainability/fairness/reject-inference/tuning (deferred) | various | low (deferred) | not executable in launch mode; port when graduated |

**First proof of the new contract:** `LogisticRegressionNode` — it is the canonical fit node, has a parameter schema, uses `ArtifactEvidenceReader` + `write_json_artifact`, and has a known-input parity test (`test_logistic_regression_known_input.py`). If LogisticRegression ports cleanly, the contract works for the family.

## Open design decisions (carried from 00)

- D9 `NodeContext` shape — validated above.
- D14 cancellation semantics — cooperative, validated.
- `TechnicalManifestExportNode` remains a node (per D19/batch decision) with a `manifest` input role carrying a `RunSummary` dataclass produced by `ExecuteRun` after all steps complete. This preserves node-level evidence. *Affects Batch 05.*