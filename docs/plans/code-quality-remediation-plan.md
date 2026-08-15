# Code Quality Remediation Plan — Legacy World Deletion & Structural Consolidation

> Derived from: thermo-nuclear code quality review of the full codebase (Aug 2026).
> Scope: `cardre/` (~37.2k lines), `tests/` (~18.2k lines), `frontend/src` (~2.1k lines excl. generated).
> Prime directive: **behavior preservation**. Every phase must keep the golden/parity anchors green.
> Estimated net deletion if fully executed: **~12k lines** (≈4k production dead code, ≈6.3k dead tests, ≈1.7k duplication).

---

## 0. Global Rules (read first — apply to every phase)

### 0.1 Verification harness

Every phase ends with, in this order:

```bash
. .venv/bin/activate
ruff check --fix
make preflight          # includes governance-mode pytest
scripts/pr-gate.sh      # push + PR + wait for CI green (never use gh pr * directly)
```

Never request review until the gate prints `CI GREEN`.

### 0.2 Behavioral anchors — if any of these change, STOP

| Anchor | What it pins |
|---|---|
| `tests/test_golden_fixtures_roundtrip.py` | Artifact serialization + logical-hash stability |
| `tests/test_scoring_export_parity.py` | Python/SQL scoring parity across node types |
| `tests/test_error_code_sync.py` | TS/Python error-code parity |
| `tests/application/governance/test_governance_routes_integration.py` | Governance API contract |
| `tests/test_api_scorecard_launch_pathway.py` | Full launch pathway incl. run execution |

Rule: before starting a phase, run its anchor subset and note the pass state. If a refactor is truly behavior-preserving, these stay green with **zero golden-fixture regeneration**. If you are tempted to regenerate a golden fixture, you are changing behavior — abort and reassess.

### 0.3 Verify-before-delete protocol

Deleting anything (file, module, symbol, test):

```bash
# 1. Prove no production importer exists (exclude the artifact itself and tests/):
grep -rn "from cardre.<module>" cardre/ sidecar/ scripts/ tools/ --include='*.py' | grep -v "cardre/<module>/"
# 2. Inventory test importers (they get migrated or deleted in the same PR):
grep -rln "from cardre.<module>" tests/ --include='*.py'
# 3. Only then: git rm, fix imports, run §0.1.
```

### 0.4 Branch/PR strategy

One branch per phase (or sub-phase where noted): `batch-08-p<N>-<slug>`. Do not mix phases in one PR. Each PR description lists: lines added/deleted, anchors run, grep-verification output for each deletion.

### 0.5 Do not refactor and feature-build simultaneously

While phases 1–4 are in flight, no new node types, no new routes. The migration debt compounds everything else.

---

## Phase Map (dependency-ordered)

```
P1  NodeContext migration completion (classifier family, then 5 deferred nodes)
P2  Legacy world deletion sweep (~4k lines)              [depends on P1]
P3  Test suite resurrection (6.3k xfail lines)           [depends on P1; overlaps P2]
P4  Canonical WOE application (correctness fix)          [independent]
P5  Classifier payload template unification              [depends on P1a]
P6  Schema surface dedup (domain owns shapes once)       [independent]
P7  API layer cleanup (error translator, N+1, catalogue) [independent]
P8  Node ergonomics (require_kind, typed params, publish tail)
P9  Atomic publish-and-register flow
P10 Test/tooling/frontend hygiene (conftest, AST scanners, AsyncList, Makefile)
```

---

## Phase 1 — Finish the NodeContext migration

**Problem.** The migration to `NodeContext` is ~90% done. Still on the legacy `ExecutionContext` (from `cardre/execution/context.py`, a ghost package of 1-line shims):

| Consumer | Evidence |
|---|---|
| `nodes/_classifier_base.py:31,89` — `BaseClassifierNode.run(context: ExecutionContext)` | drags in **6 nodes**: `ml_models.py` (DecisionTree/RF/GBDT) + `boosting.py` (XGB/LGBM/CatBoost) |
| `nodes/calibrate.py:32,306` | 604-line module, 299-line `run()` |
| `nodes/tuning.py:16,187` | |
| `nodes/reject_inference.py:14` | 3 `run()` methods |
| `nodes/explainability.py:17,139` | |
| `nodes/fairness.py:16` | 3 `run()` methods |
| `nodes/build/models.py:19,204` | dual-path dispatch `hasattr(context, 'inputs')` — dead legacy branch at `:342-476` |
| `modeling/builders.py:13` | |
| `application/execution/input_collection.py:17` | imports `TargetMeta` — **upward import papered over by an import-linter `ignore_imports` entry in `pyproject.toml`** |
| `nodes/ensembles.py` | registered nowhere — delete outright |

Split into three PRs.

### P1a — Port `BaseClassifierNode` to `NodeContext` (unblocks 8 nodes)

The target shape is `nodes/build/automatic.py:23-63` (the canonical new-style node). The port:

```python
# cardre/nodes/_classifier_base.py  (after)
from cardre.nodes.contracts import NodeContext, NodeResult

class BaseClassifierNode(NodeType):
    node_type = ""          # set by subclasses — DO NOT change any node_type/version
    version = "1"
    category = "fit"

    def run(self, context: NodeContext) -> NodeResult:
        train_artifact = context.inputs.require("train", type(self).__name__)
        frame = context.inputs.read_dataframe(train_artifact)
        target_spec = TargetSpec.from_metadata(context.inputs.target_metadata())
        if target_spec is None:
            raise ValueError(f"{type(self).__name__} requires target metadata")

        X, y, feature_names = prepare_supervised_training_data(frame, target_spec)  # new path only
        params = NodeParams(context.params)          # see Phase 8; dict access still works
        clf = self._build_estimator(params)
        clf.fit(X, y)

        context.outputs.publish_table(
            role="prediction", kind=EvidenceKind.PREDICTION_TABLE,
            frame=predictions_frame(clf, X, feature_names),
        )
        self._post_fit(context, clf, params, feature_names)   # payload hook, unchanged logic
        return context.outputs.build_result()
```

Rules:
1. `_build_estimator_kwargs` / `_post_fit` are already pure hooks taking params — **leave their bodies untouched**; only the context plumbing around them changes.
2. Replace every `write_json_artifact(self.context.store, ...)` with `context.outputs.publish_json(role=..., kind=..., payload=..., metadata={"schema_version": ...})`. Map each legacy `(artifact_type, role)` pair to the equivalent `EvidenceKind` — inventory them first:

    ```bash
    grep -n "write_json_artifact\|write_parquet_artifact" cardre/nodes/_classifier_base.py cardre/nodes/ml_models.py cardre/nodes/boosting.py
    ```

3. Delete `_training_utils._prepare_training_data` (old path, `:139-175`) once nothing calls it; `prepare_supervised_training_data` (`:89-136`) becomes the only prep.
4. While in `step_runner.py`: lines 130-134 compute `output_contract`/`outputs` **twice** — delete the duplicate pair.
5. **Anchor**: `tests/test_scoring_export_parity.py` must stay green. The six classifier nodes' model-artifact payloads (feature_importance, training_params, interpretability blocks) must be byte-identical — verify via the golden fixtures, not by eyeballing.

New test (add to a new `tests/test_classifier_nodes.py`):

```python
def test_random_forest_node_context_output_roles(node_harness):
    result = node_harness.run(
        RandomForestClassifierNode,
        inputs={"train": node_harness.dataset_frame(seed=7)},
        params={"n_estimators": 10, "max_depth": 3},
    )
    assert result.metrics["estimator_count"] == 10
    kinds = {a.kind for a in result.staged_artifacts}
    assert EvidenceKind.MODEL_ARTIFACT in kinds
```

(The `node_harness` fixture is defined in Phase 3 §3.2 — build it there first if you want the test now, or defer the test to Phase 3.)

### P1b — Port the five deferred modules + delete `ensembles.py`

For each of `calibrate.py`, `tuning.py`, `reject_inference.py`, `explainability.py`, `fairness.py`:

1. Add `__definition__ = NodeDefinition(...)` with proper `ArtifactContract` roles mirroring what the legacy code actually reads/writes (derive from the `ArtifactEvidenceReader` lookups and `write_json_artifact` calls — inventory with the grep in P1a step 2).
2. Change each `run(self, context: ExecutionContext) -> NodeOutput` to `run(self, context: NodeContext) -> NodeResult`.
3. Mechanical replacements:

    | Legacy | New |
    |---|---|
    | `ArtifactEvidenceReader(store).find(store, kind)` / `.read(...)` | `arts = context.inputs.by_kind(EvidenceKind.X)` then `context.inputs.read(arts[0], EvidenceKind.X)` |
    | `context.train_artifact()` / `context.require_train_artifact(nt)` | `context.inputs.require("train", nt)` |
    | `write_json_artifact(store, ...)` | `context.outputs.publish_json(...)` |
    | `write_parquet_artifact(store, ...)` | `context.outputs.publish_table(...)` |
    | warnings appended to a local list | `context.outputs.add_warning({...})` |
    | `NodeOutput(artifacts=..., metrics=...)` | `context.outputs.add_metric(...)` × n; `return context.outputs.build_result()` |

4. These nodes are **deferred tier** — they must keep `node_type`/`version`/tier exactly; verify with `tests/test_node_registry_tiers.py`.
5. `nodes/ensembles.py`: delete (verify with §0.3 — expect zero production importers).

**Anchor**: `tests/test_deferred_nodes.py` must stay green (it exercises deferred instantiation).

### P1c — Kill the dual path in `build/models.py` and fix `TargetMeta`

1. Delete `LogisticRegressionNode.run`'s `hasattr` dispatch (`:198-206`) and `_run_execution_context` (`:342-476`, ~135 lines). Keep `_run_node_context` as the only body (until Phase 5 folds it into `BaseClassifierNode`).
2. `TargetMeta` (defined in `cardre/execution/context.py:15-24`) is imported by `application/execution/input_collection.py:17`. `cardre/modeling/target.py` already owns `TargetSpec` with the same information. Consolidate:
   - Move/merge `TargetMeta` into `cardre/modeling/target.py` (or delete it outright if `TargetSpec` covers it — check `TargetSpec.from_metadata` first).
   - Update `input_collection.py` to import from the new home.
   - Remove both `ignore_imports` entries under the "Application must not import adapters..." contract in `pyproject.toml` (the `-> cardre.execution.context` one becomes structurally impossible; audit the `-> cardre.adapters.evidence.reader` one — if still needed, leave it and note why).
3. Update `tests/test_logistic_regression_legacy_path.py`: delete (it pins the path being removed).

**DoD (Phase 1)**: `grep -rn "ExecutionContext" cardre/ --include='*.py'` returns only `cardre/execution/context.py` itself. `lint-imports` green. All anchors green.

---

## Phase 2 — Legacy world deletion sweep (~4k lines)

Execute §0.3 for **every** row, in this order (each numbered step can be its own commit):

### 2.1 The manifest

| # | Artifact | Lines | Notes / caveats |
|---|---|---|---|
| 1 | `cardre/execution/` (whole package) | 154 | After P1: only `context.py` had content. Also remove `application/execution/input_collection`'s import exception if not done in P1c. |
| 2 | `cardre/store/` (whole package: schema.py 423, 11 repos, db.py, ...) | 2,335 | Production-dead (container wires only `adapters/sqlite/`, `bootstrap/container.py:14-15`). Importers after P1: `services/project_resolver.py`, `_evidence/reader.py`, `_evidence/adapters/`, `cardre/artifacts.py`, `nodes/explainability.py`, `nodes/ensembles.py` — all themselves on this list or already ported. `tests/test_store_repos.py` (488 lines) and `tests/test_store_manual_binning_reviews.py` test the **dead** stack: delete, and port any assertion that encodes a real invariant (e.g. artifact dedup by physical_hash) to the `adapters/sqlite` equivalents. |
| 3 | `cardre/_evidence/adapters/` (`__init__.py` 274 + `_base.py` 123) | 397 | Dead duplicate registry. Live registry: `adapters/evidence/parsers.py`. Repoint `tests/test_evidence_adapters.py` at the live registry first (keep the parity assertions — they're good tests — drop the dead-module imports at `:21-25,52`). |
| 4 | `cardre/adapters/evidence/profiles.py` | 319 | Dead twin of `_evidence/profiles.py`. Zero importers expected. |
| 5 | `cardre/_evidence/reader.py` | 86 | Thin wrapper over `adapters/evidence/reader.py`; after P1+P5 no production importers remain. |
| 6 | `cardre/domain/evidence.py` | 112 | Byte-identical to `domain/evidence/models.py`, shadowed by the package. Verify with `diff cardre/domain/evidence.py cardre/domain/evidence/models.py` before deleting. |
| 7 | `cardre/domain/binning/definition.py` | 9 | Re-export shim; repoint `nodes/build/manual.py:170,178` to `cardre.engine.binning.definition`. |
| 8 | `cardre/api/routes/_run_mappings.py` | 270 | Verbatim copy of `api/mappers.py`. Repoint `tests/test_api_mappers.py:3`. |
| 9 | `cardre/nodes/registry.py` | — | Self-documented as removable; production catalogue is `bootstrap/node_catalogue.py`. |
| 10 | `cardre/capabilities.py`, `cardre/node_parameters.py`, `_evidence/kinds.py` | ~60 | Export-only shims, zero production importers. |
| 11 | `cardre/artifacts.py` (root) | ~250 | Legacy store-based artifact writer. After P1 only tests import it — repoint them to the `node_harness`/artifact-store helpers from §3.2. |
| 12 | `cardre/services/` (whole package) | 37+ | `project_resolver.py` wraps the dead `store/project_registry`. The live equivalent is `adapters/system/project_registry.py` (used by the container). `services/comparison/` is an empty `__pycache__` dir. |
| 13 | Dead dirs `cardre/readiness/`, `cardre/reporting/` | 0 | `__pycache__` only. Remove from git if tracked, and purge stale bytecode dirs. |
| 14 | `api/dependencies.py:60-76` `get_run_queries` | ~17 | Builds a closure dict no route consumes. |
| 15 | `domain/evidence/schemas.py` vs `_evidence/schemas.py` | ~45 | Keep ONE canonical constant set (the `_evidence` copy is live). Repoint `domain/evidence` importers, delete the other. |

### 2.2 Configuration and documentation truth-up (same PR as the relevant deletions)

- `pyproject.toml`: remove any now-unneeded `ignore_imports`; **add** import-linter coverage for `cardre._evidence` (must not import `application`/`api`/`bootstrap`/`nodes`) so the layering that was implicit becomes enforced.
- `CONTEXT.md:29`: currently documents `cardre/_evidence/adapters/` + `EVIDENCE_ADAPTERS` as the registry — **it describes the dead copy**. Rewrite to point at `cardre/adapters/evidence/parsers.py` and name the real reader (`cardre/adapters/evidence/reader.py`). While there, note `store/` is gone and `adapters/sqlite` is the single persistence stack.
- `docs/architecture-rewrite/00-validation-report.md:26` claims "No import-linter is configured" — false. Fix.

**DoD (Phase 2)**: every §0.3 grep clean; `lint-imports` green including the new contract; `make preflight` green; net deletion ≥ 3.5k lines.

---

## Phase 3 — Test suite resurrection (6,307 xfail lines)

### 3.1 Triage rules

Current state: ~20 files carry `pytestmark = pytest.mark.xfail(...)` and `tests/conftest.py:44` auto-xfails 5 more by filename.

| Rule | Files | Action |
|---|---|---|
| A. Module under test was **deleted** (RunCoordinator, services) | `test_run_coordinator.py` (436), `test_run_plan_decision.py`, `test_run_coordinator_edge_cases.py` | **Delete.** An xfail for a removed class is a graveyard, not a migration state. |
| B. Tests the **old execution path** (`PlanExecutor` via `cardre.execution.executor`) | `test_executor.py` (724), `test_executor_characterization.py` (367), `test_run_step_writer.py`, `test_run_lifecycle_errors.py`, `test_worker_lifecycle.py`, `test_run_lifecycle.py` (395), `test_action_planning.py`, `test_audit_persistence.py`, `test_run_dispatch.py`, `test_audit_insert_semantics.py` | Rewrite the ones encoding live invariants (see §3.3) against `ExecuteRun`/`StepRunner`; delete the rest. Do NOT carry xfails forward. |
| C. Node unit tests on `ExecutionContext` | `test_binning_node.py`, `test_clustering_node.py`, `test_diagnostics_nodes.py` (381), `test_build_summary_report.py`, `test_build_summary_node.py`, `test_coefficient_sign_check_node.py`, `test_freeze_scorecard_bundle.py`, `test_score_scaling_known_input.py` (311), `test_score_scaling_errors.py`, `test_training_resampling.py` (315), `test_validation_metrics_node.py`, `test_model_apply_boundary.py` | Rewrite on the §3.2 harness, keeping the *assertions* (they encode real behavior: known-input score values, error paths, resampling semantics). |
| D. Duplicated scaffolding | `test_executor_characterization.py` vs `test_executor.py` (`_make_store`/`_write_input_csv` verbatim at both `:32`/`:40`) | Merge unique characterization assertions (manifest/lineage) into the rewritten executor contract test; delete the file. |

Target end-state: **zero module-level xfails**; delete the auto-xfail hook at `tests/conftest.py:44` (last step of the phase, after the filename list is empty).

### 3.2 The node test harness (build once, in `tests/conftest.py`)

Today only `step_runner.py:143` constructs `NodeContext`, so node tests had no cheap entry point. Build one:

```python
# tests/conftest.py
@dataclass
class HarnessStaged:
    kind: EvidenceKind
    role: str
    payload: JsonDict | pl.DataFrame
    metadata: JsonDict

class FakeOutputPublisher:  # implements the OutputPublisher protocol
    def __init__(self):
        self.staged: list[HarnessStaged] = []
        self.metrics: JsonDict = {}
        self.warnings: list[JsonDict] = []
    def publish_json(self, *, role, kind, payload, metadata=None):
        self.staged.append(HarnessStaged(kind, role, payload, metadata or {}))
    def publish_table(self, *, role, kind, frame, metadata=None):
        self.staged.append(HarnessStaged(kind, role, frame, metadata or {}))
    def add_metric(self, name, value): self.metrics[name] = value
    def add_warning(self, warning): self.warnings.append(warning)
    def set_execution_fingerprint(self, fp): self.fingerprint = fp
    def build_result(self):
        return NodeResult(staged_artifacts=[object()], metrics=self.metrics,
                          warnings=self.warnings)

class FakeInputCollection:  # implements the InputCollection protocol
    def __init__(self, frames: dict[str, pl.DataFrame], evidence: dict[EvidenceKind, Any],
                 target_metadata=None):
        ...
    def require(self, role, node_type):
        if role not in self.frames:
            raise ValueError(f"{node_type}: no input with role {role!r}")
        return role
    def read_dataframe(self, artifact): return self.frames[artifact]
    def by_kind(self, kind): return [k for k in self.evidence if k == kind]
    ...

@pytest.fixture
def node_harness():
    """Run a node directly with fakes: node tests without a store."""
    def run(node_cls, *, inputs, params, evidence=None, target_metadata=None, seed=0):
        outputs = FakeOutputPublisher()
        node = node_cls()
        errors = node.validate_params(params)
        assert errors == [], f"param validation failed: {errors}"
        node.run(NodeContext(
            run_id="run-test", plan_version_id="pv-test",
            step_spec=make_step_spec(node_cls, params),
            inputs=FakeInputCollection(inputs, evidence or {}, target_metadata),
            outputs=outputs, params=params,
            runtime=RuntimeMeta("run-test", "pv-test", "step-test", node_cls.node_type),
        ))
        return outputs
    return run
```

Rewritten rule-C test example (preserving the original assertion):

```python
def test_score_scaling_known_input(node_harness):
    out = node_harness.run(
        ScoreScalingNode,
        inputs={"train": KNOWN_INPUT_FRAME},          # fixture values copied verbatim
        evidence={EvidenceKind.MODEL_ARTIFACT: known_logistic_model()},
        params=KNOWN_SCALING_PARAMS,                   # copied verbatim from old test
        target_metadata=known_target_metadata(),
    )
    points = out.staged[0].payload["scorecard"]["points"]
    assert points == EXPECTED_POINTS_TABLE             # same expected values as the old test
```

### 3.3 Executor-path contract tests (replace group B)

Write ONE focused file, `tests/test_run_execution_contract.py`, driving the live path
(`SubmitRun` + `ExecuteRun` via the container, like `test_api_scorecard_launch_pathway.py` does),
asserting the invariants the old tests pinned:

- run lifecycle transitions (pending → running → succeeded/failed) and `RunFinalisation` manifest contents;
- per-step persistence: run_steps, evidence_edges grain `(run_step_id, parent_step_id, source_run_step_id)`, artifacts registered by physical_hash with dedup;
- failure classification: a failing node records diagnostics + failed status, no partial commit of that step;
- heartbeat/worker: only if `RunWorker` still exists post-P2 (it lives behind `cardre/execution/worker` shim — check where the real implementation is and test that directly).

**DoD (Phase 3)**: `grep -rn "pytest.mark.xfail" tests/ | wc -l` → 0 (or a documented remainder ≤ 2 with issues linked); suite line count drops ≥ 5k; anchors green.

---

## Phase 4 — Canonical WOE application (latent correctness bug)

**Problem.** The domain's central promise — "the validate stream applies fitted definitions from the build stream" (`CONTEXT.md:65`) — is implemented three times with **three different missing-WOE policies**:

| Site | Policy on missing WOE for a bin |
|---|---|
| `nodes/validate/apply.py:165-170` | **raise** |
| `nodes/build/features.py:501-515` | **default 0.0** |
| `nodes/build/clustering.py:259-274` | **silently skip the bin** |

Same `pl.when(mask).then(pl.lit(woe))` accumulation loop in all three.

### 4.1 One canonical function

Add to `cardre/engine/binning/woe.py` (already the canonical WOE home):

```python
class MissingWoePolicy(StrEnum):
    RAISE = "raise"      # any bin without a WOE value is a data-integrity error
    ZERO = "zero"        # missing WOE contributes 0.0 (build-stream WOE transform)
    SKIP_BIN = "skip_bin"  # omit the bin from the when/then chain (clustering previews)

def apply_woe_columns(
    df: pl.DataFrame,
    var_defs: Iterable[Any],          # objects with .variable, .kind, .bins (bin dicts)
    woe_lookup: Callable[[str, str], float | None],  # (variable, bin_id) -> woe
    *,
    policy: MissingWoePolicy,
    suffix: str = "_woe",
    skip_missing_variable: bool = True,   # variable not in df.columns -> skip (all 3 sites do this)
) -> tuple[pl.DataFrame, list[str]]:
    """Apply bin definitions to df, adding one <variable><suffix> column per variable.

    Returns the augmented frame and the list of created column names.
    """
    exprs, created = [], []
    for vd in var_defs:
        var, kind, bins = vd.variable, vd.kind, vd.bins
        if skip_missing_variable and var not in df.columns:
            continue
        woe_expr: pl.Expr | None = None
        for be in bins:
            bin_id = be["bin_id"]
            mask = build_bin_condition(be, pl.col(var), kind, bins, variable=var, bin_id=bin_id)
            woe_val = woe_lookup(var, bin_id)
            if woe_val is None:
                if policy is MissingWoePolicy.RAISE:
                    raise ValueError(f"missing WOE for {var}:{bin_id}")
                if policy is MissingWoePolicy.SKIP_BIN:
                    continue
                woe_val = 0.0
            clause = pl.when(mask).then(pl.lit(woe_val))
            woe_expr = clause if woe_expr is None else woe_expr.when(mask).then(pl.lit(woe_val))
        if woe_expr is None:
            if policy is MissingWoePolicy.RAISE:
                raise ValueError(f"WOE transform: variable {var!r} has no bins defined")
            continue
        exprs.append(woe_expr.otherwise(pl.lit(None, dtype=pl.Float64)).alias(f"{var}{suffix}"))
        created.append(f"{var}{suffix}")
    return (df.with_columns(exprs) if exprs else df), created
```

Note: `nodes/build/features.py:511` raises when a variable has **no bins at all** while the other two skip — model that with the `woe_expr is None` branch above, matching each call site's current policy (`RAISE` re-raises, others skip). If exact per-site parity cannot be expressed by the three policies, add a fourth — **do not** special-case at call sites.

### 4.2 Migrate the three call sites

Each site becomes ~10 lines: build the `woe_lookup` closure from its existing map/table, pick its policy. `build_bin_condition` stays where it is (`nodes/build/_bin_mask.py:10`); import it inside `engine/binning/woe.py` — wait, dependency direction: `engine` must not import from `nodes`. Therefore **move `build_bin_condition` to `cardre/engine/binning/masks.py`** (pure polars logic, belongs in engine) and keep a re-export in `nodes/build/_bin_mask.py` only if still referenced.

### 4.3 Tests

```python
# tests/test_apply_woe_columns.py
def test_raise_policy_matches_validate_apply_behavior(): ...   # missing bin woe -> ValueError
def test_zero_policy_matches_features_transform(): ...          # missing -> 0.0 column
def test_skip_bin_policy_matches_clustering_preview(): ...      # bin omitted, others applied
def test_unknown_variable_skipped(): ...
def test_parity_with_old_implementations(golden_dataset):
    """Column values identical to pre-refactor outputs for all three policies."""
```

Capture parity by running the OLD implementations on a fixed dataset before deleting them (commit the expected parquet under `tests/golden/`), then assert the new function reproduces it.

**DoD**: all three duplicate loops deleted; `grep -rn "pl.when(mask" cardre/nodes/` returns zero WOE-accumulation hits; parity test green.

---

## Phase 5 — Classifier payload template unification (~400 lines)

After P1a, five `_post_fit` bodies build the same payload shape: `ml_models.py:379-402` (RF), `:526-548` (GBDT), `boosting.py:154-175` (XGB), `:301-322` (LGBM), `:444-465` (CatBoost).

### 5.1 Extract once, in `nodes/_classifier_result.py`

```python
FEATURE_STRATEGIES = ("raw_numeric", "encoded_raw", "woe_challenger")  # replaces 6 literal copies

def classifier_result_payload(
    *, feature_importance: dict[str, float] | None, feature_count: int,
    estimator_count: int | None, learning_rate: float | None,
    training_params: JsonDict, limitations: tuple[str, ...], extra_metrics: JsonDict | None = None,
) -> JsonDict:
    """The single _ClassifierResult payload builder (schema unchanged)."""
```

Each `_post_fit` collapses to: parse its specific params → call `classifier_result_payload` → `context.outputs.publish_json(role="model", kind=EvidenceKind.MODEL_ARTIFACT, payload=...)`.

### 5.2 Kill double param parsing

`_build_estimator_kwargs` and `_post_fit` parse the same keys twice per node (`ml_models.py:160-175` vs `:193-198`; same pattern ×5). Parse once at the top of `run()` into a small frozen dataclass (`EstimatorParams`), pass it to both hooks. Adjust `BaseClassifierNode` signature accordingly — subclasses are all in-repo, no external contract.

### 5.3 Fold `LogisticRegressionNode` into the family

Port it onto `BaseClassifierNode` (it already will be NodeContext-native after P1c). Its coefficient handling, convergence-warning capture, and `feature_order_hash` become its `_post_fit` + one override (`_build_estimator` returning the sklearn LR). Delete `_run_node_context` (`models.py:208-340`). The model-artifact payload must stay **byte-identical** (coefficients, feature_order_hash, training_params) — pinned by golden fixtures; if any byte differs, stop.

**DoD**: `grep -c "interpretability" cardre/nodes/ml_models.py cardre/nodes/boosting.py` → 0 (moved to the helper); parity/golden anchors green.

---

## Phase 6 — Schema surface dedup (domain owns each shape once)

**Problem.** Four surfaces define overlapping shapes:

| Shape | Copies |
|---|---|
| `RunManifest`/`RunManifestStep` | `domain/manifest.py:20,66` ≡ `application/reporting/schema.py:424,446` |
| `ResolvedStepRef` | `application/reporting/contracts.py:45` ≡ `application/reporting/schema.py:20` (same package!) |
| `Diagnostic` | `domain/errors.py:55` ≡ `application/reporting/schema.py:471` ≡ `api/schemas.py:126` |
| `ArtifactRef` family | `domain/artifacts.py` ≡ `application/reporting/schema.py:392` ≡ `api/schemas.py:252` |

Plus `finalize_run.py:162-179` builds the manifest as a raw dict — a third representation, bypassing its own domain type.

### Rules

1. **`cardre/domain/` owns every shape once** (frozen dataclasses with `to_dict`/`from_dict`).
2. **`application/reporting/schema.py`** keeps pydantic (it serializes the audit bundle) but must **compose**, never redefine:

    ```python
    class RunManifestSection(BaseModel):
        @classmethod
        def from_domain(cls, m: RunManifest) -> "RunManifestSection": ...
    ```

3. **`api/schemas.py`** maps domain → wire in `api/mappers.py` (its job already).
4. Delete the duplicated dataclass OR pydantic twin — keep whichever is imported by live logic, derive the other via `from_domain`/`to_domain`. For `ResolvedStepRef`: the dataclass is the internal currency, pydantic only wraps for the bundle.
5. Rewrite `finalize_run.py:162-179` to construct `RunManifest(...)` and serialize through its `to_dict` — the raw-dict build is where drift starts.
6. `html_report.py`'s ~12 hand-built `rows = [[...] for ...]` blocks: add one `_rows(records, *formatters)` helper and rewrite them (~150 lines out). Also: `adapters/reporting/collector.py:202-204` re-implements the manifest hash inline — call `domain.manifest.compute_manifest_hash` instead.

**Anchor**: golden fixtures roundtrip + one new test asserting `RunManifest.from_dict(RunManifest(...).to_dict())` roundtrip and `RunManifestSection.from_domain(m).model_dump() == m.to_dict()` (field parity, once, forever).

---

## Phase 7 — API layer cleanup

### 7.1 One error translator (deletes 5 copy-pasted try/except ladders)

Current: `runs.py:57-78`, `reports.py:27-34`, `projects.py:46-53`, `plans.py:119-132`, `governance.py:251-258` — each a bespoke `if exc.code == ...` chain, some **string-matching messages** (`runs.py:59`: `"not found" in exc.message.lower()`), which is exactly the fragility the typed codes exist to prevent.

```python
# cardre/api/error_mapping.py
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.domain.errors import CardreError

DOMAIN_ERROR_MAP: dict[str, tuple[ErrorCode, int]] = {
    "PLAN_VERSION_NOT_FOUND": (ErrorCode.PLAN_VERSION_NOT_FOUND, 404),
    "PROJECT_NOT_FOUND":      (ErrorCode.PROJECT_NOT_FOUND, 404),
    "RUN_NOT_FOUND":          (ErrorCode.RUN_NOT_FOUND, 404),
    "CONCURRENT_RUN":         (ErrorCode.CONCURRENT_RUN, 409),
    "BRANCH_VALIDATION_ERROR": (ErrorCode.BAD_REQUEST, 400),
    "RUN_SCOPE_INVALID":       (ErrorCode.BAD_REQUEST, 400),
    "PARAMETER_VALIDATION_ERROR": (ErrorCode.BAD_REQUEST, 400),
    # ... inventory with: grep -rn "CardreError(" cardre/ --include='*.py' | grep -o 'code="[A-Z_]*"'
    "DEFAULT": (ErrorCode.INTERNAL_ERROR, 500),
}

def register_exception_handler(app: FastAPI) -> None:
    @app.exception_handler(CardreError)
    async def _(request, exc: CardreError):
        code, status = DOMAIN_ERROR_MAP.get(exc.code, DOMAIN_ERROR_MAP["DEFAULT"])
        return JSONResponse(status_code=status, content=CardreApiError(
            code=code, message=str(exc), status_code=status).to_response())
```

- Every `DOMAIN_ERROR_MAP` entry must correspond to codes actually raised — build the map from the grep, don't guess.
- Delete the message-string fallbacks: if a raise-site lacks a code, **add the code at the raise site** (that's the fix), don't pattern-match prose.
- Handlers collapse to `result = submit(...)` + `return _load_run(...)`.
- Anchors: `test_api_scorecard_launch_pathway.py` and the governance integration tests pin status codes for the error paths — they must stay green unchanged.

### 7.2 Kill `_uc()` string dispatch

`governance.py:46-65` and `plans.py:24-60` build `{name: use_case}` dicts and index by string. The container exists for exactly this: add explicit factories (`container.create_branch_factory` pattern is already there — `bootstrap/container.py:173-191`) and `Depends(get_container).create_branch` per route. String keys and the dict builders disappear.

### 7.3 Fix the `list_runs` N+1 (runs.py:87)

`[_load_run(...) for rid in run_ids]` opens a UoW **per run**. Same store, so fix with batching:

```python
@router.get("/runs", response_model=RunListResponse)
def list_runs(project_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        runs = uow.runs.list_for_project(project_id)
        steps = uow.run_steps.get_for_project(project_id)      # add repo method (one query)
        diags = uow.runs.get_diagnostics_for_project(project_id)  # add repo method (one query)
    steps_by_run = group_by(steps, key=lambda s: s.run_id)
    diags_by_run = group_by(diags, key=lambda d: d.run_id)
    return RunListResponse(runs=[
        run_to_response(r, step_count=len(steps_by_run[r.run_id]),
                        executed_step_ids=[s.step_id for s in steps_by_run[r.run_id]
                                           if s.status.value == "succeeded"],
                        diagnostics=diags_by_run[r.run_id]) for r in runs])
```

Two new repo methods replace N connections. **Do not** touch `application/projects/list_projects.py:27-55` the same way — each project is its own SQLite file, per-project opens are inherent there.

### 7.4 `async def` → `def`

Every handler is `async def` but calls only synchronous use cases — blocking the event loop. Change all route functions to plain `def` (FastAPI runs them in the threadpool). Mechanical, zero behavioral change via TestClient.

### 7.5 Node catalogue: declarative, no class mutation

`bootstrap/node_catalogue.py:151-153` sets `cls._deferred = True` as a registration side effect, with a 3-part manual registration and **no completeness assertion**. Restructure:

```python
LAUNCH_NODES: tuple[type[NodeType], ...] = (AutomaticBinningNode, ...)
DEFERRED_NODES: tuple[type[NodeType], ...] = (XGBoostClassifierNode, ...)

def build_default_catalogue(settings: Settings) -> NodeCatalogue:
    assert not set(LAUNCH_NODES) & set(DEFERRED_NODES), "node in both tiers"
    entries = [NodeCatalogueEntry.from_node(cls, tier="launch") for cls in LAUNCH_NODES]
    entries += [NodeCatalogueEntry.from_node(cls, tier="deferred") for cls in DEFERRED_NODES]
    return NodeCatalogue(entries)
```

- Tier becomes a property of the entry, never a mutation of the class; delete `_deferred()` and the `_deferred` class flag on `NodeType` (`contracts.py:116`).
- Completeness: `from cardre.nodes import __all__ as _public; registered = {*LAUNCH_NODES, *DEFERRED_NODES}; missing = [o for o in _public if isinstance(o, type) and issubclass(o, NodeType) and o not in registered]; assert not missing`.
- `workflows/scorecard.py:260` builds the full 52-node catalogue to look up a few classes — replace with a direct import/dict of the handful it needs.

**DoD (Phase 7)**: `grep -rn "except CardreError" cardre/api/` → only the handler; `grep -rn "_uc(" cardre/api/` → 0; `tests/test_node_registry_tiers.py` green.

---

## Phase 8 — Node ergonomics

### 8.1 `InputCollection.require_kind`

The `by_kind(...)` + `[0]` + `raise ValueError("No X found")` pattern repeats across 8+ files (worst: `build/freeze.py:51-74`, five consecutive blocks). Add to the protocol (`nodes/contracts.py:63`) and the implementation:

```python
def require_kind(self, kind: EvidenceKind, node_type: str) -> Any:
    arts = self.by_kind(kind)
    if not arts:
        raise ValueError(f"{node_type}: no input artifact of kind {kind.value}")
    return arts[0]
```

Migrate all `by_kind(...)[0]`-with-guard sites. ~60 lines out.

### 8.2 Typed params accessor (kills triple parsing)

`build/clustering.py` parses the same keys at `:543-549` (run), `:190-243` (validate_params), `:674-680` (worker). Add `cardre/nodes/_params.py`:

```python
class NodeParams(Mapping):  # drop-in: dict-style access still works everywhere
    def __init__(self, raw: JsonDict): self._raw = dict(raw)
    def __getitem__(self, k): return self._raw[k]
    def __iter__(self): return iter(self._raw)
    def __len__(self): return len(self._raw)
    def str(self, key, default): return str(self._raw.get(key, default))
    def float(self, key, default): ...
    def int(self, key, default): ...
    def bool(self, key, default): ...
    def choice(self, key, options, default): ...   # validates membership
```

`step_runner.py:149` passes `NodeParams(normalized_params)` — since it's a `Mapping`, nothing else changes. Migrate the worst offenders (clustering, calibrate, tuning, boosting); leave simple two-param nodes alone. Also delete `validate_params` re-checks of constraints the `ParameterConstraint` schema already enforces (clustering `:190-243` re-checks `candidate_limit`, `similarity_metric`, `threshold` already constrained at `:66-113`) — keep only cross-field rules.

### 8.3 `publish_report` tail helper

The `publish_json(role="report",...)` + `add_metric` × 2 + `build_result()` tail repeats in 12+ files (4× in `build/diagnostics.py` alone). One helper in `nodes/_reporting.py`:

```python
def publish_report(context: NodeContext, *, kind: EvidenceKind, payload: JsonDict,
                   schema_version: str, metrics: Mapping[str, float | int | str | bool]) -> None:
    context.outputs.publish_json(role="report", kind=kind, payload=payload,
                                 metadata={"schema_version": schema_version})
    for name, value in metrics.items():
        context.outputs.add_metric(name, value)
```

Plus: `_load_iv_map(inputs)` shared (3 copies: `selection.py:175`, `clustering.py:614`, `features.py:271`); `NUMERIC_DTYPES` constant (2 copies: `_fine_classing.py:68`, `_optbinning.py:14`).

### 8.4 Decompose `CalibrateProbabilitiesNode.run` (calibrate.py:306-604, 299 lines)

Target shape (behavior-preserving; each helper extracted verbatim from the current body):

```python
def run(self, context):
    params, frame, model_artifact = self._load_inputs(context)          # I/O boundary
    method = _CalibrateMethod.from_params(params)                       # replaces the platt/isotonic
    folds = _resolve_folds(method, params, len(frame))                  #   × CV boolean matrix at
    calibrator, bins_metrics = _fit_calibrator(method, folds, frame)    #   :417-458 and :509-518
    payload = _calibration_report(method, folds, calibrator, bins_metrics, warnings)
    publish_report(context, kind=EvidenceKind.CALIBRATION_REPORT, payload=payload, ...)
    _update_model_artifact(context, model_artifact, calibrator, method)
```

Rules: the four mode booleans (`cross_validated`, `score_scaling_compatible`, `has_linear_coefficients`, `too_few_rows`) become fields of `_CalibrateMethod`/`_CalibratePlan`, not threaded locals. Report field names/values unchanged (golden anchor).

---

## Phase 9 — Atomic publish-and-register

**Problem.** Three sites publish artifacts to the filesystem **before** the DB commit, so a crash orphans files with no DB row: `execute_run.py:141→224` (per-step), `execute_run.py:330-356` (`_publish_run_summary` — separate UoW from the final run state!), `refresh_comparison.py:172→220`. Meanwhile `export_audit_pack.py:83-97` already implements the correct pattern: write to temp → atomic rename → DB register, with **compensation** (delete the export dir if the DB write fails).

### 9.1 One canonical helper

`cardre/application/artifacts/publishing.py`:

```python
@dataclass(frozen=True)
class PublishedArtifact:
    artifact_id: str
    physical_hash: str
    logical_hash: str
    path: Path

def publish_and_register(
    uow_factory, artifact_store, project_id: str, *,
    stage: Callable[[Path], tuple[str, str]],   # write into temp dir -> (physical_hash, logical_hash)
    register: Callable[[Any], str],            # insert DB row inside the uow; returns artifact_id
) -> PublishedArtifact:
    with tempfile.TemporaryDirectory(dir=artifact_store.staging_root) as tmp:
        physical, logical = stage(Path(tmp))
        final_path = artifact_store.final_path_for(physical)
        os.replace(tmp_file, final_path)                 # atomic on same filesystem
        try:
            with uow_factory(project_id) as uow:
                artifact_id = register(uow)
                uow.commit()
        except Exception:
            final_path.unlink(missing_ok=True)           # compensation
            raise
    return PublishedArtifact(artifact_id, physical, logical, final_path)
```

(Adapt to the real signatures of `FsArtifactStore` — the point is: rename + register + compensate live in ONE place.)

### 9.2 Migrate

- `execute_run.py` per-step persistence: artifact publish via the helper; run_step + evidence_edges + lineage in the same UoW as the register callback where possible.
- `_publish_run_summary`: fold into the same UoW as the final run-state update — a crash between "summary written" and "run marked succeeded" is exactly the half-applied state the review flagged.
- `refresh_comparison.py:148` and `create_branch.py:267` reach into `uow._conn` / raw `conn.execute` — replace with repo methods (`comparison_snapshots.add`, `comparison_snapshot_plan_versions.add`, `plan_branches.add`, `branch_step_map.add` as needed). Repos exist to own those statements; also drop `remap_step_graph`'s pure computation out of the transaction body (`create_branch.py:250`).

### 9.3 Test

```python
def test_publish_and_register_compensates_on_db_failure(tmp_path, monkeypatch):
    """DB failure after rename deletes the file — no orphans."""
    with pytest.raises(sqlite3.Error):
        publish_and_register(uow_that_fails, store, project_id, stage=..., register=...)
    assert not list(store.artifacts_root.rglob("*.parquet"))
```

---

## Phase 10 — Test, tooling, and frontend hygiene

### 10.1 Tests

1. **Consolidate fixtures** (35 files hand-roll scaffolding): move `_make_store`/`_write_input_csv`/`_seed_*` into the 3 conftests (`tests/conftest.py` already has `store`, `registered_plan`, `committed_plan_version` — extend, don't duplicate). `governance_env` (`test_governance_routes_integration.py:31-38`) duplicates `gov_env` (`tests/application/api/conftest.py:32-38`) — keep one. `api_client` (`tests/conftest.py:194-200`) imports a private `cardre.api._app_instance.app` — make it use `create_app(build_container(...))` like everything else.
2. **Delete the AST source-scanners** (`test_canonical_contract.py:53-64,248-252`, `test_evidence_adapters.py:60-95`): they re-implement import-linter, which `pyproject.toml` already configures. Port any unique assertion into an import-linter contract first (e.g. forbidden `nodes → application`). Keep `test_error_code_sync.py` — that's TS/Python parity, a different concern.
3. Stop calling private methods: `test_evidence_adapters.py:143,156` (`reader._match`/`._parse`) — test through the public `read`/`match` surface.

### 10.2 Frontend

1. **`<AsyncList>`** — six copy-pasted loading/empty ternary blocks (`WelcomeScreen.tsx:197-224`, `PlanSidebar.tsx:78-102`, `VersionPanel.tsx:76-118`, `RunDetailsPanel.tsx` ×3):

    ```tsx
    export function AsyncList<T>({ isLoading, items, renderItem, emptyText, loadingText }: {
      isLoading: boolean; items: T[] | undefined; renderItem: (item: T) => ReactNode;
      emptyText: string; loadingText?: string;
    }) {
      if (isLoading) return <p className="muted">{loadingText ?? "Loading…"}</p>;
      if (!items?.length) return <p className="muted">{emptyText}</p>;
      return <>{items.map(renderItem)}</>;
    }
    ```

2. **Consume the error taxonomy or stop maintaining it**: add ONE meaningful branch in `useProjectWorkspace` — `SIDECAR_UNREACHABLE`/`REQUEST_TIMEOUT` → a retry affordance; everything else stays `toErrorMessage`. (`client.ts:72-74`'s `context.originalCode` is currently dead weight — either surface it in the retry handler or delete the field.)
3. Split `useProjectWorkspace.ts` (186 lines, returns 25 values) into `useProjects`/`usePlans`/`useVersions`/`useRuns` + keep the composed hook as the only consumer-facing API (zero component changes).
4. Delete dead exports: `fetchResponse`/`fetchJson`/`FetchOptions` from `client.ts` public surface (keep internal), the `displayRuns` alias (`PlanSidebar.tsx:36`).
5. Type hygiene: `client.ts:194` `undefined as unknown as T` → make the 204 path return `T | undefined` at the type level; `client.ts:251` → `declare global { interface Window { __API_URL__?: string } }`.

### 10.3 Tooling

1. `Makefile:56-57`: codegen is deliberately skipped in `preflight` ("skipped during migration") while CI (`ci.yml:316-333`) enforces it. After P1–P2 land, enable `python3 scripts/generate-openapi-types.py` in `preflight`; if it can't be enabled, the Makefile comment must reference a tracking issue.
2. Delete scripts not referenced by Makefile/CI after grep-verifying (`ls scripts/` vs `grep -rn "scripts/" Makefile .github/workflows/`).

**DoD (Phase 10)**: `grep -rln "_make_store" tests/ | wc -l` → 0; no AST-scanner tests; `npm run test -- src/api src/hooks src/components` green; `make preflight` includes codegen.

---

## Appendix A — Final state acceptance checklist

```bash
# Legacy world gone:
grep -rn "ExecutionContext\|cardre\.execution\.\|from cardre\.store\|cardre\.services" cardre/ --include='*.py'   # -> 0 hits
grep -rn "ignore_imports" pyproject.toml                                                                          # -> empty or justified

# Dead duplicates gone:
test ! -f cardre/api/routes/_run_mappings.py
test ! -f cardre/adapters/evidence/profiles.py
test ! -f cardre/domain/evidence.py
diff <(git show main:cardre/domain/evidence/models.py) cardre/domain/evidence/models.py >/dev/null && echo "domain intact"

# Suite health:
grep -rn "pytest.mark.xfail" tests/ --include='*.py' | wc -l   # -> 0
grep -rln "_make_store" tests/ | wc -l                          # -> 0

# WOE single-source:
grep -rn "pl.when(mask" cardre/nodes/ --include='*.py'          # -> 0 WOE-accumulation loops

# API:
grep -rn "except CardreError" cardre/api/ | wc -l               # -> 1 (the handler)
grep -rn "async def" cardre/api/routes/ | wc -l                 # -> 0

# Full gates:
ruff check && lint-imports && make preflight && scripts/pr-gate.sh
```

## Appendix B — Effort / ordering summary

| Phase | Est. net Δ lines | Risk | Suggested PR count |
|---|---|---|---|
| P1 a/b/c | −300 (deferred churn offsets additions) | medium | 3 |
| P2 | −4,000 | low (deletion, grep-verified) | 3-4 |
| P3 | −5,000 to −6,000 | medium (assertion preservation) | 3-4 |
| P4 | −80 + correctness fix | medium (parity test required) | 1 |
| P5 | −400 | medium (byte-identical payloads) | 1-2 |
| P6 | −300 | medium | 1-2 |
| P7 | −150 | low | 2 |
| P8 | −350 | low | 2 |
| P9 | +80 structure, fixes orphan windows | medium | 1 |
| P10 | −600 (tests) | low | 2 |

Abort criteria for any phase: a golden fixture or parity anchor requires regeneration → the phase is NOT behavior-preserving → stop, document the divergence in the PR, and get a human decision before proceeding.
