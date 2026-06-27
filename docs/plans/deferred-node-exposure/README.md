# Deferred / Optional Node Exposure — Launch Safety Plan

A focused plan to close the gap between the **launch/deferred node tier**
(`cardre/registry.py`) and the surfaces that expose nodes to users and to
the executor. Today `/node-types` returns every registered node in launch
mode without any availability signal, optional-dependency absence is never
surfaced as a clean error, and a plan that contains a deferred node only
fails **mid-run** after earlier steps have already written artifacts.

## Chosen exposure model — Option B (with a hard pre-execution gate)

`/node-types` returns **all** nodes with an explicit
`available: bool`, `disabled_reason: str | None`, and
`missing_optional_dependencies: list[str]`. The UI renders unavailable
nodes/methods as disabled (mirroring the existing `MethodOption.status =
"coming_soon"` pattern already rendered as a disabled `<option>` in
`SchemaDrivenParamsEditor.tsx`). A new **pre-execution validation gate**
rejects any plan containing an unavailable node **before** a run row is
created — no step executes.

Why not A (filter `/node-types`): the registry docstring
(`cardre/registry.py:6`) explicitly intends deferred nodes to "render in
the UI via their parameter schemas" for discoverability; filtering loses
that. Why not C: B *is* the Cardre-consistent design — it reuses the
existing `status`/`disabled` UI pattern rather than inventing a new one.

## Validation context (confirmed against the repo)

- `cardre/config.py:16` `launch_mode` defaults **True**; read via
  `CardreConfig.from_env().launch_mode`.
- `cardre/registry.py:50` `instantiate()` already guards deferred nodes
  in launch mode → raises `NodeNotAvailableForLaunch`
  (`cardre/errors.py:101`, code `NODE_NOT_AVAILABLE_FOR_LAUNCH`).
- `cardre/registry.py:172` `_register_deferred_nodes` marks 19 nodes
  `_deferred=True` via the `_deferred` decorator (`:85`).
- `cardre/audit.py:124` `NodeType` declares `optional_dependencies:
  list[str] | None` — but **no node class sets it**. It is only present
  in the static `_MODEL_FAMILIES` dict in `sidecar/routes/node_types.py:66-82`
  (xgboost/lightgbm/catboost → `["boosting"]`).
- `sidecar/routes/node_types.py:148` `list_node_types` **never reads
  `launch_mode`** and returns all nodes with `tier` only.
- `cardre/executor.py:416` `registry.instantiate(spec.node_type)` is
  called **per-step during execution**, so a deferred node fails
  mid-run. There is no pre-execution scan.
- `cardre/services/run_service.py:57` `run_plan` creates the run row
  (`store.create_run`, `:102`) **before** dispatching execution.
- `cardre/services/plan_service.py:297` `update_step_params` calls
  `registry.instantiate` for schema validation — a deferred node in a
  plan would raise `NodeNotAvailableForLaunch` here too, but with a
  confusing message at param-save time rather than a clear "this node
  is not available in launch mode" signal.
- `sidecar/proof_pathway.py:176` `REJECT_INFERENCE_PATHWAY` references
  `cardre.reject_inference_none` (deferred). It is **not** auto-registered
  in launch mode (only `register_proof_pathway` is called at
  `projects.py:57`), so it is latent. **Decision: keep
  `reject_inference_none` deferred** — the new pre-execution gate will
  reject the pathway cleanly at run time.
- The frontend has **no node-type picker/palette**. `ConfigureTab`/
  `SchemaDrivenParamsEditor` only configure *existing* plan steps.
  So the "selection" concern is limited to schema rendering + param save.
- `frontend/src/components/params/SchemaDrivenParamsEditor.tsx:386`
  already renders `m.status === "coming_soon"` as a disabled `<option>`.
  This is the pattern to mirror for node-level unavailability.
- OpenAPI regen: `python3 scripts/generate-openapi-types.py`
  (imports `sidecar.main`, writes `frontend/src/api/openapi.json` +
  `schema.d.ts` via `npx openapi-typescript`).
- Tests: `make test` = `python3 -m pytest tests/ -q`; `make typecheck`
  = `cd frontend && npx tsc --noEmit`; `make lint` runs line-count +
  artifact-read scans. The `client` fixture (`tests/conftest.py:23`)
  provides a FastAPI `TestClient`.

## Work items

| Item | Files | Outcome |
|------|-------|---------|
| 1 | `cardre/errors.py` | New `OptionalDependencyNotInstalled`, `PlanContainsUnavailableNodesError` |
| 2 | `cardre/registry.py` | `NodeAvailability` dataclass; `availability()` / `is_available()`; optional-dep probes; clean `instantiate` error |
| 3 | `cardre/nodes/*.py` | Set `optional_dependencies` class attr on boosting/smote/explainability nodes |
| 4 | `cardre/executor.py`, `cardre/services/run_service.py` | Pre-execution `validate_plan_executability` gate before `create_run` |
| 5 | `sidecar/models.py` | Extend `NodeTypeItem` + `NodeTypeSchemaResponse` with availability fields |
| 6 | `sidecar/routes/node_types.py` | Populate availability; add `?available_only=true` |
| 7 | Frontend | Regenerate OpenAPI types; `SchemaDrivenParamsEditor` disabled banner |
| 8 | Tests | New + extended backend/frontend tests (see below) |
| 9 | `AGENTS.md`, `docs/` | Error codes + availability-model note |

## TDD ordering

Implement strictly red-green-refactor in this order (each item's failing
test first, then minimal impl):

1. Registry availability (item 2 test → item 2)
2. Optional-dep error class (item 1 test → item 1)
3. Node `optional_dependencies` attrs (item 3 test → item 3)
4. Pre-execution gate (item 4 test → item 4)
5. API model + route (item 5/6 test → item 5/6)
6. Frontend disabled banner (item 7 test → item 7)
7. Docs (item 9 — no test; non-TDD follow-up)
8. OpenAPI regen (item 7 tail — generation, not a TDD cycle)

After every green item: `make lint && make typecheck && make test` must
all pass before moving on.

## Scope boundary

**In scope:** availability introspection, pre-execution gating, clean
optional-dep errors, API/UI availability signals, tests, docs.

**Out of scope:** adding a node-type picker/palette to the frontend,
promoting any deferred node to launch, changing `_deferred` membership,
new modelling/evidence/scorecard behaviour, new endpoints beyond the
`?available_only` query param.

## Definition of done

1. `GET /node-types` returns `available`, `disabled_reason`,
   `missing_optional_dependencies` on every item; deferred nodes are
   `available=false` with a launch-mode reason in launch mode.
2. `GET /node-types/{node_type}/schema` carries `available` +
   `disabled_reason`.
3. `?available_only=true` excludes deferred nodes in launch mode.
4. A run request for a plan version containing a deferred node returns
   400 `PLAN_CONTAINS_UNAVAILABLE_NODES` **before** any run row is
   created and **before** any step executes.
5. Instantiating a node whose optional dependency is missing raises
   `OptionalDependencyNotInstalled` (code
   `OPTIONAL_DEPENDENCY_NOT_INSTALLED`), not a raw `ImportError`.
   In launch mode the deferred reason takes precedence.
6. The frontend `SchemaDrivenParamsEditor` renders a disabled banner
   with `disabled_reason` and hides Save when `schema.available === false`.
7. `make lint && make typecheck && make test` pass; the regenerated
   `openapi.json` + `schema.d.ts` are committed in the same PR.
8. `AGENTS.md` lists the three canonical error codes.

Detailed step-by-step implementation with code snippets lives in
`implementation.md`.