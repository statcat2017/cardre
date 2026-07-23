# Thermo-Nuclear Remediation Sprint

## Purpose

This is an implementation guide for a smaller coding agent. It turns the
2026-07-19 maintainability audit into small, independently verifiable changes.
Repair enforcement first, then incorrect persisted contracts, then architecture
and decomposition. Do not combine every slice into one pull request.

## Constraints

1. FastAPI/OpenAPI is the API source of truth. Do not maintain a second API
   contract by hand.
2. Typed evidence and `ModelArtifactV1` are canonical boundaries. Do not add
   legacy-shape fallbacks.
3. The manifest producer owns manifest hashing; report readers only verify it.
4. `NodeParameterSchema` must be the common scalar validation boundary.
5. Do not retain experimental-plan compatibility without an approved migration.
   ADR-0003 rules out legacy accommodation.
6. Put new tests at the narrowest ownership boundary. Broad executor tests are
   supplementary, not the sole coverage for a local contract.
7. Do not alter the SQLite schema, Run state values, or build/validate topology
   unless a slice explicitly says to.

## Delivery Order

| Order | Slice | Acceptance condition |
| --- | --- | --- |
| 0 | Repair quality gates | Every documented gate works; CI cannot green-light unclassified code |
| 1 | Canonical manifest writer | Normal finalized Runs have valid self-hashes |
| 2 | Compiled scoring export model | Python and SQL consume one bin/WOE semantics model |
| 3 | Executable node parameters | Defaults, coercion, and constraints run once before node execution |
| 4 | Typed model consumption | Apply, ensembles, and comparison do not flatten models into ad-hoc dicts |
| 5 | Coherent live workspace | The selected Run universe is consistent and active Runs refresh |
| 6 | Generated API boundary | Operations derive paths and types from generated OpenAPI types |
| 7 | Owned sidecar lifecycle | Startup/handoff failures are explicit and cleanup is reliable |
| 8 | Node-module decomposition | Independent nodes are split and covered at node level |
| 9 | Dead mode removal | Unsupported `to_node` has no runtime plumbing |

## Slice 0: Repair Quality Gates

### Scope

Change `Makefile`, `.github/workflows/ci.yml`, `scripts/`, `pyproject.toml`,
affected test setup, and documentation that names retired checks. Do not weaken
checks just to make the current branch pass.

### 0.1 Use one artifact-read policy

_scripts/scan-direct-artifact-reads.py_ is a stale pattern ratchet with a
baseline of 278 historical violations. `scripts/audit_artifact_reads.py` is
the context-aware production audit already used in `preflight`. Delete the
scanner and `.artifact-read-baseline.json`; update documentation; make both
`lint` and `preflight` call the same surviving target.

Target Makefile shape:

```make
audit-artifact-reads:
	python3 scripts/audit_artifact_reads.py --production --fail-on production_violation

lint-artifact-reads: audit-artifact-reads

lint: lint-line-counts lint-artifact-reads
```

Do not leave a compatibility wrapper for the deleted scanner. That preserves
two owners for the same policy.

### 0.2 Ensure every changed path triggers substantive CI

`ci-success` correctly permits legitimately skipped platform jobs, but the
path filter omits `tools/**`, most shell scripts, root operational files, and
some GitHub configuration. A skipped result is safe only when another job owns
the changed path.

Preferred design: make the Python quality lane match _scripts/**_, _tools/**_,
root build/config files, and GitHub workflow/config changes in addition to its
current paths. Add an explicit `unclassified` filter only if its complement
semantics are tested; do not rely on an untested glob negation.

Add a table-driven test or checked-in fixture that proves these paths activate
at least one owning job:

```text
tools/reference_extractors/extract_scorecard_r_german_credit.R
scripts/pr-gate.sh
scripts/check-sidecar-naming.py
.github/dependabot.yml
Makefile
docs/architecture/reporting.md
```

### 0.3 Replace stale focused commands and restore governance selection

`v2-phase-check.sh`, `test-evidence`, and `test-launch-core` name deleted
tests. Replace phase-numbered history with named maintained suites, or delete
the commands. Before publishing any focused target, validate every referenced
path with `git ls-files --error-unmatch`.

The declared `governance` pytest marker is unused while CI selects files by
name. Mark the actual governance tests and select them by marker:

```python
import pytest


@pytest.mark.governance
def test_branch_route_requires_governance() -> None:
    ...
```

```make
test-governance:
	CARDRE_GOVERNANCE=1 python3 -m pytest -m governance -q --tb=short --no-cov
```

### 0.4 Reduce raw-SQL setup duplication

Add small composable fixtures in `tests/conftest.py` for a registered Project,
Plan, PlanVersion, and Run. Use canonical repository/service paths. Keep
scenario-specific records in individual tests; do not build a generic hidden
test-object framework.

```python
@pytest.fixture
def registered_project(store: ProjectStore) -> Callable[..., Project]:
    def create(*, name: str = "Test project") -> Project:
        ...
    return create
```

### Slice 0 Tests

1. `make lint` succeeds from a clean checkout.
2. `make audit-artifact-reads` and `make lint-artifact-reads` have the same
   result.
3. Every published focused target names tracked tests only.
4. `pytest -m governance` collects governance tests but not unrelated API
   tests.
5. CI filter fixtures cover every path listed in section 0.2.
6. Migrate one representative API test to fixture factories, then migrate the
   remaining repeated project/plan/run setup within this slice.

## Slice 1: Canonical Manifest Writer

### Scope

Change `cardre/execution/run_lifecycle.py`, `cardre/application/reporting/schema.py`,
`cardre/adapters/reporting/collector.py`, and lifecycle/report integrity tests. Do not
put producer logic in the report collector.

### Design

Create one function that owns finished-manifest serialization:

1. Build the complete payload with `manifest_hash` set to `""`.
2. Hash that exact dictionary with `json_logical_hash`.
3. Store the resulting digest in `manifest_hash`.
4. Validate the completed payload with `RunManifest`.
5. Publish using a flushed temporary file and `os.replace`.

```python
def build_final_manifest_payload(...) -> JsonDict:
    payload = build_manifest_payload(...)
    payload["manifest_hash"] = ""
    payload["manifest_hash"] = json_logical_hash(payload)
    RunManifest.model_validate(payload)
    return payload


def publish_json_atomically(path: Path, payload: JsonDict) -> None:
    # Write beside path, flush/fsync, then replace path atomically.
    ...
```

Rename an un-hashed internal builder to make its incomplete state obvious. A
canonical writer must not create a finished manifest with an omitted or empty
hash. If old manifests must remain readable, isolate that leniency in a
historical-reader path that emits a clear warning.

### Slice 1 Tests

1. Finalize success, failure, and cancellation Runs; blank the stored hash and
   recompute it; assert equality with the stored digest.
2. Pass a normal finalized manifest to `ReportCollector`; assert no
   `ARTIFACT_HASH_UNRESOLVED` limitation.
3. Tamper with a persisted field and assert that exact blocker is produced.
4. Simulate write failure before replacement; assert the Run cannot become
   `succeeded` and any prior complete manifest remains unchanged.

## Slice 2: Compile Scorecard Semantics Once

### Scope

Extract a focused `cardre/nodes/build/scoring_export_ir.py` from
`scoring_export.py`; update `tests/test_scoring_export_parity.py`. Do not build
a generic code-generation framework.

### Design

Compile bin definitions, WOE mappings, feature contract, coefficients, and
score scaling into a small typed intermediate representation. Render Python
and SQL from that value.

```python
@dataclass(frozen=True)
class ScoringBin:
    bin_id: str
    woe: float
    kind: Literal["numeric", "categorical"]
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = False
    upper_inclusive: bool = True
    categories: tuple[str, ...] = ()
    is_missing: bool = False
    is_other: bool = False


@dataclass(frozen=True)
class ScoringVariable:
    name: str
    coefficient: float
    missing_policy: Literal["error", "zero"]
    bins: tuple[ScoringBin, ...]
```

The compiler owns ordered matching, missing values, unmatched non-null values,
categorical `other`, and variables that have bins but no model coefficient. It
must define one explicit unmatched fallback; renderers must not leave local
WOE variables unassigned. Determine the fallback from runtime scoring behavior
before implementation. Do not preserve the current Python/SQL disagreement.

Extract duplicated evidence resolution and output payload construction from
the two export nodes into one private helper. Keep renderer-specific code in
the renderers only.

### Slice 2 Tests

1. Numeric missing bin plus unmatched non-null input has the same Python and
   SQL outcome.
2. Cover no-missing-bin, categorical `other`, no-`other`, and inclusive/
   exclusive boundary cases.
3. Invalid bin/WOE relationships fail at compilation with a useful error.
4. Retain end-to-end parity coverage, but make compiler unit tests the primary
   regression seam.

## Slice 3: Make Node Parameter Schemas Executable

### Scope

Change `cardre/node_parameters.py`, `cardre/execution/step_runner.py`, narrow
node contract hooks if required, and parameter tests. Start with one launch
node and `cardre/nodes/boosting.py`; migrate remaining nodes in follow-ups.

### Design

Add one pure normalizer from raw persisted parameters to validated normalized
values:

```python
def normalize_node_params(
    schema: NodeParameterSchema,
    raw: JsonDict,
) -> JsonDict:
    method = select_declared_method(schema, raw)
    definitions = {p.name: p for p in method.params}
    reject_unknown_keys(raw, definitions | {"method"})
    values = {
        name: coerce_and_validate(raw.get(name, param.default), param)
        for name, param in definitions.items()
    }
    require_declared_values(values, definitions)
    return values
```

It must select the declared default method, apply defaults, enforce required
fields/kinds/enums/bounds/list bounds/patterns, and reject unknown keys. It
returns normalized values so node implementations stop repeating `int()` and
`float()` conversions. Keep `node.validate_params` temporarily only for
cross-field or data-dependent rules, after normalization.

The `StepRunner` flow becomes:

```python
node = registry.instantiate(spec.node_type)
params = normalize_node_params(node.parameter_schema(), spec.params)
errors = node.validate_params(params)  # cross-field checks only
context = ExecutionContext(..., validated_params=params)
```

If a node has no schema, make that absence explicit and retain its existing
validator temporarily. Do not create empty schemas that accept everything.

### Slice 3 Tests

1. Omitted values arrive in `ExecutionContext.validated_params` as defaults.
2. Invalid integers/floats, enum values, bounds, patterns, and unknown keys
   fail before optional dependency or estimator construction.
3. XGBoost rejects `n_estimators=0` and invalid `learning_rate` centrally.
4. A node-local cross-field rule still executes after normalization.
5. The API/UI schema and execution acceptance agree on an enum and bound.

## Slice 4: Keep Model Artifacts Typed Through Consumption

### Scope

Change `nodes/validate/apply.py`, `modeling/adapters.py`, `nodes/ensembles.py`,
`services/comparison/model.py`, and model/comparison tests. Add a focused
module such as _cardre/modeling/prediction.py_ if it reduces ownership drift.

### Design

`ModelArtifactV1.from_dict` rejects legacy top-level `features`,
`coefficients`, and `intercept`. Do not parse a typed model then call
`to_dict()` to regain dynamic `.get()` behavior.

```python
def predict_model(model: ModelArtifactV1, frame: pl.DataFrame) -> ModelPredictions:
    family = require_family(model.model_family)
    estimator = load_estimator_reference(model.estimator_reference)
    return family.predict(model, estimator, frame)
```

Create a modeling-owned `ModelComparisonView` for the comparison use case.
Comparison code should use that typed projection, rather than branch over
dict/list/top-level legacy coefficient shapes. If ensemble evidence is a
separate canonical artifact, give it a separate typed adapter; `dict[str, Any]`
is not the shared contract.

### Slice 4 Tests

1. Application consumes `ModelArtifactV1` without `to_dict()` at the boundary.
2. Legacy top-level fields are rejected once and never revived downstream.
3. Logistic and estimator-backed predictions retain existing scores.
4. Comparison covers coefficient and non-coefficient families through the
   typed view.
5. Mypy passes without new casts in model consumers.

## Slice 5: Make Workspace State Live and Consistent

### Scope

Change `useProjectWorkspace.ts`, `PlanSidebar.tsx`, `WelcomeScreen.tsx`,
`ProjectView.tsx`, `App.tsx`, and add Testing Library/MSW tests.

### 5.1 Derive one Run universe

The sidebar must either show all project Runs when no version is selected, or
only the selected version's Runs, including an intentional empty state. Derive
one collection and use it for both rendering and selected-ID validation.

```typescript
const visibleRuns = effectiveSelectedVersionId
  ? allRuns.filter((run) => run.plan_version_id === effectiveSelectedVersionId)
  : allRuns;

const effectiveSelectedRunId = useSelectedEntity(
  selectedRunId,
  visibleRuns,
  "run_id",
  "first",
);
```

Pass only `visibleRuns` to `PlanSidebar`. Do not preserve its current fallback
from an empty version-scoped list to all project Runs.

### 5.2 Poll active Runs only

Runs are created with `sync: false`, so invalidation after creation cannot
discover later terminal status. Define one terminal-status predicate and use it
to refresh the Run, list, steps, and evidence while active. Stop the shared
refresh when terminal; do not create three independent timers.

```typescript
const isTerminalRun = (status: string) =>
  status === "succeeded" || status === "failed" || status === "cancelled";

const selectedRunQuery = useQuery({
  // existing key and function
  refetchInterval: (query) =>
    query.state.data && isTerminalRun(query.state.data.status) ? false : 1_000,
});
```

Adapt the exact callback form to the installed TanStack Query v5 API.

### 5.3 Remove false project-path identity

`listProjects` is global, while the frontend gates and keys it on the typed
creation path. The selected project then carries a non-authoritative path that
the backend ignores whenever `X-Project-Id` exists.

Make selected app state `{ id: string }`; remove `projectPath` from
`ProjectScope`, request headers, `ProjectView`, and `App`. The creation path is
input for `createProject` only. Add an authoritative root field to the Project
response only if the product needs to display one.

### Slice 5 Tests

1. A selected version with no Runs shows an empty state, not another version's
   Run.
2. A displayed Run remains selected and loads details.
3. A running Run refetches and a terminal Run stops refetching.
4. A new async Run eventually renders its terminal state without manual reload.
5. Selecting an existing project never carries the currently typed creation
   path into requests.

## Slice 6: Make OpenAPI the API Boundary

### Scope

Change `frontend/package.json`, the API client/transport/tests, and backend
schemas plus generated files only for the diagnostic DTO. This depends on
Slice 5 for the simplified scope type.

### Design

Use `openapi-fetch` or a small equivalent wrapper based on generated
`paths`/`operations`. Preserve `ApiError` and its canonical error codes in a
single transport adapter; do not replace robust error behavior with a library
default.

```text
generated paths/operations
          |
          v
typed API operations
          |
          v
Cardre transport: timeout, abort, JSON parsing, ApiError normalization
```

Correct the raw transport's header handling while migrating:

```typescript
const headers = new Headers(init.headers);
headers.set("Accept", "application/json");
if (body !== undefined) headers.set("Content-Type", "application/json");
```

Do not cast `HeadersInit` to `Record<string, string>`. Split no-content
operations from JSON-returning operations instead of returning `undefined as T`.

Add a shared server diagnostic DTO for `latest_error`, diagnostics, step
warnings, and step errors where appropriate. Regenerate `openapi.json` and
`schema.d.ts`; remove the assertion inside `RunDetailsPanel`.

```python
class DiagnosticResponse(BaseModel):
    code: str
    message: str
    context: JsonDict = Field(default_factory=dict)
```

### Slice 6 Tests

1. Operation paths, request bodies, and response types derive from generated
   types and fail TypeScript checking when incompatible.
2. Object, `Headers`, and tuple-array header input reach the fetch mock.
3. No-content operations have an honest return type and test.
4. A typed diagnostic renders without a JSX cast.
5. OpenAPI generation leaves no unexpected generated-file diff.

## Slice 7: Own Tauri Sidecar Lifecycle

### Scope

Change `frontend/src-tauri/src/main.rs`, focused Rust tests, the sidecar smoke
test in CI, and ADR-0011 only if operational behavior changes.

### Design

Startup succeeds only after the process is spawned, healthy, owned by app
state, and its exact API URL has been injected into the webview. A failure at
any step kills the locally owned child and returns an error from setup. Do not
ignore lock/eval errors or call `std::process::exit` from a branch that bypasses
cleanup.

```rust
let mut child = spawn_sidecar(port)?;
wait_for_health(port, 30).inspect_err(|_| kill_child(&mut child))?;
inject_api_url(&window, &api_url).inspect_err(|_| kill_child(&mut child))?;
app.state::<AppState>().store_sidecar(child)?;
```

Exact helper signatures may differ. The invariant is one owner and visible
failure. Extract pure URL-script and port-allocation helpers when that enables
unit tests.

The CI smoke test must choose an available ephemeral loopback port and install
cleanup immediately after spawn:

```bash
cleanup() { kill "$SIDECAR_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
```

### Slice 7 Tests

1. Failed health check kills its child before setup returns.
2. Failed URL injection and failed state storage are surfaced, not ignored.
3. The injected URL contains the selected ephemeral port, never the frontend
   fallback port.
4. The smoke script has no hard-coded `18000` and installs its trap before any
   health/name assertion.
5. Run `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and
   sidecar-resolution tests.

## Slice 8: Split Independent Node Bundles

### Scope

This is behavior-preserving refactoring after Slices 2-4 pass.

| Current file | Target modules |
| --- | --- |
| `nodes/feature_selection.py` | `nodes/selection/filter.py`, `embedded.py`, `resampling.py`, `smote.py`, narrow shared helper |
| `nodes/validate/analyse.py` | metrics, threshold optimization, cutoff analysis |
| `nodes/build/bins.py` | automatic binning, manual review/application |

Keep registry node identifiers and public class names unchanged. Update
registry imports in one focused change per original file.

For feature selection, extract only the duplicated definition-read/merge
policy. Do not create a base class merely to share imports:

```python
def merge_selection_definition(
    reader: ArtifactEvidenceReader,
    definition: ArtifactRef | None,
    *,
    key: Literal["selection_filter", "selection_embedded"],
    selection: JsonDict,
) -> JsonDict:
    ...
```

Also separate expected non-clusterable evidence from unexpected computation
failures. Return a typed no-clusters result only for the former; preserve
unexpected numeric exceptions as node failures with causal diagnostics.

### Slice 8 Tests

1. Replace empty `tests/test_feature_selection.py` with node tests for filter,
   embedded, resampling, and SMOTE behavior.
2. Both selection nodes produce the same definition merge shape.
3. Validation metrics, threshold, and cutoff have separate focused tests.
4. Automatic and manual binning have separate focused tests.
5. Clustering catches only expected insufficient-evidence behavior.
6. Run characterization tests before each extraction and the line-count guard
   after it. Do not create a new catch-all replacement module.

## Slice 9: Delete Unsupported `to_node`

### Scope

Change `services/run_coordinator.py`, related request/dispatch/lifecycle
plumbing, and tests. `to_node` is rejected publicly but retained in internal
branches, persistence fields, and type suppression.

Delete it until there is a real scoped executor:

1. Remove it from public coordinator and API request types.
2. Remove target-step plumbing that exists only for it.
3. Remove manual tests that instantiate this impossible mode.
4. Preserve `full_plan` and `branch` behavior exactly.

If scoped execution is required, stop and write that design first. Do not
re-enable it as special cases spread across coordinator, dispatcher, and
lifecycle paths.

### Slice 9 Tests

1. Public schemas expose only supported scopes.
2. No production `to_node` reference remains.
3. Full-plan and branch dispatch/finalization regressions pass.
4. Mypy passes without a run-scope `type: ignore`.

## Cross-Slice Completion Checklist

Run the owning focused suite while implementing each slice, then run:

```bash
. .venv/bin/activate
ruff check --fix
make preflight
cd frontend && cargo fmt --check && cargo clippy --all-targets -- -D warnings
```

Also run:

```bash
python3 -m pytest tests/test_run_audit_integrity.py tests/test_run_lifecycle.py -q
python3 -m pytest tests/test_scoring_export_parity.py -q
python3 -m pytest tests/test_model_apply_boundary.py -q
python3 -m pytest tests/test_feature_selection.py tests/test_clustering_node.py -q
cd frontend && npm test
```

Before a pull request, regenerate OpenAPI files, inspect the generated diff,
then use the repository PR gate only after local preflight succeeds.

## Definition of Done

1. All published local and CI gates work and own every relevant change path.
2. Normal Run manifests self-validate and reports have no false integrity
   blocker.
3. Python and SQL exports share tested scoring semantics.
4. Parameters and model artifacts retain one explicit typed contract.
5. Async frontend state is live, coherent, and derived from authoritative IDs.
6. API operations are generated-contract-derived and diagnostics are typed.
7. Sidecar lifecycle failures are explicit and cleanup is centralized.
8. The listed node bundles are decomposed with focused coverage.
9. Unsupported `to_node` runtime code is absent.
