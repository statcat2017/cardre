# Batch 08 — Product On-Ramp (close the user-reachability gap)

## Objective

Make the canonical scorecard pathway reachable from the product boundary —
the API and the desktop UI — instead of only through direct repository
access. Today `CreatePlan` creates a plan record with no version, the plans
API has no route to create or populate a version, and the frontend renders
"No versions found." with no affordance to create one. The acceptance test
itself bypasses the API (`tests/acceptance/test_launch_pathway.py:96-98`)
because, in its own words, *"the step graph itself has no public editor
endpoint yet."*

This batch closes that gap with four small, independently shippable slices.
No engine, execution, evidence, or manifest work is required — those are
done. This is a boundary-layer addition: one use case + endpoint to
*generate* the canonical pathway, one use case + endpoint to *edit* a
draft step's parameters, frontend controls to drive both, and a rewrite of
the acceptance test to go through the API.

## Release gate (the single sentence this batch must make true)

> A non-developer can install Cardre, create a project, choose a CSV, set the
> target column and good/bad values, generate the fixed launch pathway, edit
> its essential parameters, commit it, run it asynchronously, inspect
> failures, and see the generated scorecard exports and report — without
> direct database or Python access.

The gate deliberately says "see" the exports and report, not "open or
download" them: the UI currently lists the generated artifact paths
(Reports / Exports panels). Opening or downloading those files from the
packaged app is a tracked launch blocker (see "Remaining launch blockers"
below), so the gate does not claim it.

The acceptance test (`tests/acceptance/test_launch_pathway.py`) is the
executable proxy for this gate. It drives generation, target propagation,
parameter editing, commit, async run, and artifact discovery through the
API and the acceptance-fixture pathway helper.

## What this batch deliberately does NOT include

- **No generic DAG / step-editor canvas.** The canonical pathway is fixed;
  users tune its parameters, not its topology. The review rules out a DAG
  editor and the architecture reinforces that (steps carry
  `canonical_step_id`; the pathway hash is manifest integrity data —
  arbitrary topology edits would break manifest identity).
- **No engine, run-execution, manifest publication, evidence, or export
  changes.** They are complete and tested. This batch touches only the
  on-ramp: one generation use case, one step-param edit use case, their API
  routes, and the frontend controls that drive them.
- **No new domain concepts.** `StepSpec`,
  `build_canonical_scorecard_steps`, `create_version`, `commit_version`,
  `validate_topology`, and the node catalogue all already exist. This batch
  is pure wiring at the application/API boundary.

## Review remediation (PR 385)

The first review of this batch raised three blocking findings (target
propagation, parameter validation before immutable commit, and
acceptance-fixture assumptions baked into the production template) plus a
release-gap finding. All are addressed in the revised batch:

**P1 — Custom target column now propagates consistently.** A single
`configure_canonical_scorecard()` function in
`cardre/domain/plans/scorecard_pathway.py` propagates `target_column` to
*every* target-dependent step (`define-metadata`, `validate-target`,
`split`) and is the sole place target/business decisions are applied. The
acceptance test now runs the full pathway with a non-default target column
name (`outcome`) and asserts every target step received it. The unit test
`test_target_propagates_to_all_target_dependent_steps` covers the regression
directly.

**P1 — Invalid parameters cannot be committed as immutable.** 
`UpdateStepParams` and `CommitPlanVersion` now resolve each step's node and
run both schema normalization (`normalize_node_params`) and the node's
`validate_params` before persisting/committing. Invalid edits leave the
version a draft and return a structured `422 PARAMETER_VALIDATION_ERROR`
with the step and field errors. `CommitPlanVersion` defensively validates
every step — not just topology — so a bad edit is caught at commit time,
not at run time. Tests cover an out-of-range edit (`min_iv < 0`) being
rejected without mutating the draft.

**P1 — Production template separated from acceptance-fixture config.** The
production canonical template no longer bakes fixture decisions: business
metadata (`product`, `segment`, windows, `reject_inference_position`) is
empty until supplied, `manual-binning.accept_automated` defaults to `False`,
and `final-woe-iv` carries no smoothing. The acceptance fixture's specific
decisions (additive smoothing for the tiny sample, automated-bin acceptance,
term-loan/retail metadata) now live in
`tests/acceptance/fixture_pathway.py` and are applied by the fixture tests;
the acceptance test supplies them through the API edit loop before commit —
exactly what a real user does. `test_production_template_is_neutral` guards
the separation.

**P2 — Release claim narrowed; the accessible journey is exercised.**
- The acceptance test now submits the run **asynchronously** and polls to a
  terminal state, exercising the async UI journey rather than `sync=true`.
- The frontend gains report/export discovery: `listReports` and
  `listExports` client operations and a "Reports / Exports" section in
  `RunDetailsPanel` showing the generated scorer, scorecard table, and
  report paths.
- CSV selection uses a browser file input that reads `File.path` in the
  Tauri webview (with a text-entry fallback for plain browsers).

**Remaining launch blockers (tracked, not silently claimed):**
- The packaged Tauri build does not yet wire the native `@tauri-apps/plugin-dialog`
  or a "reveal in filesystem" action; file selection relies on the webview's
  file input + `File.path`.
- "Open/download the exported artifacts" from the UI is limited to showing
  the artifact paths; a download endpoint or `shell.open` action is a
  follow-up.
These are recorded here and in the PR so the release gate sentence does not
overstate what a packaged install can do today.

## Second-review remediation (PR 385, head 00013b65)

**P1 — Desktop target journey is now atomic.** The generation form collects
the target column and good/bad values and sends them with the creation
request, so a non-default target propagates to every target-dependent step
at generation — no step-editor round-trip required. As defense in depth,
`UpdateStepParams` propagates a `target_column` edit across all three
target-dependent steps in one transaction, and `validate-target.target_column`
is now exposed in the step editor. `CommitPlanVersion` rejects inconsistent
target fields (a stray direct write diverging one step is caught at commit),
covered by `test_commit_rejects_inconsistent_target` and
`test_target_column_propagates_across_target_steps`.

**P1 — Canonical commit-readiness is gated.** New
`validate_canonical_readiness()` (`cardre/application/plans/canonical_readiness.py`)
runs at commit on top of generic node validation. It requires essential
business metadata (product, segment, observation/performance windows,
reject-inference position, target, good/bad values) and exactly one
manual-binning outcome (reviewed overrides *or* explicit automated-bin
acceptance — never neither). A neutral/incomplete draft therefore cannot
become immutable. Covered by `test_commit_rejects_incomplete_canonical_draft`
and `test_commit_accepts_complete_canonical_draft`.

**P2 — Reports/exports refresh on run completion.** The reports and exports
queries are invalidated when the selected run transitions from a
non-terminal state to a terminal one, so the panels do not keep showing
stale empty results after an async run. Covered by
`refreshes reports and exports when the run becomes terminal`.

**P2 — Structured validation errors are surfaced.** `toErrorMessage()`
now renders the `errors` context from `ApiError` (step + field messages),
so an invalid edit shows *why* it failed, not just the status line.

## Third-review remediation (PR 385, head 46a4b52)

**P1 — Overlapping/blank target definitions cannot become immutable.**
`DefineModellingMetadataNode.validate_params()` now performs the
data-independent target-definition checks that previously lived only in
`run()`: non-blank `target_column`, non-blank good/bad value lists (blank
members dropped and duplicates normalized), and disjoint good/bad/
indeterminate sets. `validate_canonical_readiness()` applies the same rules
at commit, so a draft with `good_values=["default"], bad_values=["default"]`
is rejected before it can be committed. Covered by
`test_commit_rejects_overlapping_good_bad`,
`test_commit_rejects_blank_good_values`, and node-level tests in
`tests/nodes/test_canonical_decision_gates.py`.

**P1 — `accept_automated` cannot contradict executed binning.**
`ManualBinningNode.validate_params()` now rejects
`accept_automated=True` combined with non-empty `overrides`, and its `run()`
defensively raises the same way. `validate_canonical_readiness()` enforces
the rule at commit. Covered by
`test_commit_rejects_accept_automated_with_overrides` and the node tests.

**P2 — Fast runs refresh reports/exports too.** The refresh now invalidates
reports/exports the *first time any terminal status is observed per run ID*
(rather than only on a non-terminal → terminal transition), closing the race
where a fast run's first status response is already terminal. Covered by
`refreshes reports and exports when the first status is already terminal`.

**P2 — Readiness validates normalized parameters.** `CommitPlanVersion`
passes the schema-normalized parameter sets to `validate_canonical_readiness`,
so an absent or `None` target key (which normalization would default) cannot
slip past the consistency check. All three target-dependent steps must exist
and carry the same stripped, non-empty target column. Covered by
`test_commit_rejects_missing_target_key`.

## Fourth-review remediation (PR 385, head 09b406e)

**P1 — Target consistency matches execution exactly.** The readiness gate now
requires every target-dependent step to exist with a non-whitespace
`target_column` string and for the three values to match *exactly as
persisted* — no strip-collapse that would approve `"outcome"` next to
`" outcome "` (execution does not strip). Empty dependent targets are also
rejected. Covered by `test_commit_rejects_empty_dependent_target` and
`test_commit_rejects_whitespace_different_target`.

**P1 — Target class values validated with runtime-exact semantics.** Both the
node and readiness validators now reject every blank or null member in
good/bad/indeterminate lists (execution consumes each member verbatim via
`str(v)`, so a blank would become a spurious declared category), and overlap
checks run on the exact representation runtime uses. The validator no longer
cleans a temporary copy while the executed parameters keep the blank.
Covered by `test_commit_rejects_blank_member_in_good_values` and
`test_rejects_blank_member_with_valid_reject_inference`.

**P1 — Essential metadata must be non-whitespace.** `product`, `segment`,
observation/performance windows and reject-inference position are required
to be non-whitespace strings at commit (ordinary truthiness previously let
`"   "` pass, and the UI returns text fields untrimmed). Covered by
`test_commit_rejects_whitespace_only_essential_metadata`.

**P2 — Node target validation no longer skipped.** 
`DefineModellingMetadataNode.validate_params()` always runs the target
definition checks before appending reject-inference errors; an absent or
malformed `reject_inference_position` no longer short-circuits the target
checks. Covered by `test_target_checks_run_even_without_reject_inference`.

## Existing seams this batch builds on (do NOT re-implement these)

Every piece of machinery this batch needs already exists. The work is to
wire it behind an endpoint and surface it in the UI.

| Need | Existing location |
| --- | --- |
| Build the 31-step canonical scorecard pathway from a CSV path | `cardre/domain/plans/scorecard_pathway.py:258` — `build_canonical_scorecard_steps(source_path, resolve_node)` |
| Persist a draft version with steps + edges | `PlanRepoPort.create_version(plan_id, steps, is_committed=False)` — `cardre/application/ports/unit_of_work.py:29`; SQLite impl `cardre/adapters/sqlite/plan_repo.py:43` |
| Resolve node types → classes (for `node_version` / `category` on each `StepSpec`) | `NodeCatalogue.resolve(node_type)` — `cardre/bootstrap/node_catalogue.py:64`; wired on the `Container` as `container.node_catalogue` |
| Validate a step graph before commit | `validate_topology(steps)` — `cardre/application/execution/topology.py:13` (already called by `CommitPlanVersion`) |
| Commit a draft version (already an endpoint) | `POST /plan-versions/{id}/commit` → `CommitPlanVersion` — `cardre/api/routes/plans.py:134`; uses `validate_topology` |
| Recompute a step's `params_hash` after a param edit | `cardre.domain.artifacts.json_logical_hash(params)` (already used by `build_canonical_scorecard_steps`) |
| Run a committed version asynchronously (already wired in the UI) | `POST /projects/{id}/runs` with `sync=false` — `cardre/api/routes/runs.py`; `useProjectWorkspace.runMutation` already calls this |
| Read back a version's steps (already an endpoint) | `GET /plan-versions/{id}/steps` — `cardre/api/routes/plans.py:157` |
| Regenerate TS types after adding API routes | `python3 scripts/generate-openapi-types.py` (writes `frontend/src/api/openapi.json` + `schema.d.ts`) — `scripts/generate-openapi-types.py` |

## Architecture rules this batch must respect (enforced by CI)

These are not suggestions — the gates below will fail the PR if violated.

1. **Layering** (`.importlinter`, run by `make lint` / `make arch-check`):
   - `application` imports only `domain`, `application.ports`.
   - `api` imports only `application`, `domain`, `api.*`.
   - `bootstrap` imports everything.
   - Therefore: the new use case in `cardre/application/plans/` may import
     `cardre.domain.plans.scorecard_pathway` and
     `cardre.application.ports.unit_of_work` and
     `cardre.application.ports.node_catalogue`. It may NOT import
     `cardre.api.*` or `cardre.adapters.*`. The new route in
     `cardre/api/routes/plans.py` imports the use case from
     `cardre.application.plans`.
2. **Pydantic `BaseModel` only in `api/schemas.py`.** Domain objects are
   dataclasses. The new request/response models go in `api/schemas.py`.
3. **No `fastapi` imports outside `api/`.** The use case must not import
   FastAPI; only the route file does.
4. **No direct `sqlite3` imports outside `adapters/sqlite/`.** The new
   `update_step_params` repo method goes in
   `cardre/adapters/sqlite/plan_repo.py` (or `step_repo.py`).
5. **Error codes stay in sync.** `cardre/domain/errors.py::ErrorCode` is the
   canonical set; `frontend/src/api/errorCodes.ts` mirrors it and
   `tests/test_error_code_sync.py` enforces that the frontend's server-code
   subset is a subset of the Python set. If you add a new `ErrorCode`, add
   it to both files. The codes this batch needs (`PLAN_VERSION_NOT_FOUND`,
   `PLAN_VERSION_ALREADY_COMMITTED`, `STEP_NOT_FOUND`) already exist.
6. **Line counts.** `scripts/check-line-counts.py` enforces per-file limits
   (Python 1000, TS/TSX 600, Rust 300). The files this batch edits are all
   well under their limits; keep them there. `frontend/src/api/schema.d.ts`
   and `frontend/src/api/openapi.json` are in `GENERATED_FILES` and are
   excluded — regenerating them is expected and fine.
7. **OpenAPI types must be regenerated and committed.** `make preflight`
   runs `python3 scripts/generate-openapi-types.py` and then
   `git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/schema.d.ts`.
   After adding API routes, run the generator and commit both files.

## Conventions to mimic (read these files before writing code)

Every new file below has a structural twin already in the repo. Copy its
shape exactly — header docstring, `from __future__ import annotations`,
dataclass command, `__init__` taking a `uow_factory` callable, `__call__`
with `try/commit/rollback/finally close`, and the `__all__` list.

| New file | Copy the shape of |
| --- | --- |
| `cardre/application/plans/create_canonical_scorecard_version.py` | `cardre/application/plans/commit_plan_version.py` (try/commit/rollback/finally) + `cardre/application/plans/create_plan.py` (command dataclass) |
| `cardre/application/plans/update_step_params.py` | `cardre/application/plans/update_plan_version.py` (note how it raises `PLAN_VERSION_NOT_FOUND` and `PLAN_VERSION_ALREADY_COMMITTED`) |
| `tests/application/plans/test_create_canonical_scorecard_version.py` | `tests/application/plans/test_plan_use_cases.py::TestCommitPlanVersion` (uses the `provisioned_project` fixture) |
| `tests/application/plans/test_update_step_params.py` | `tests/application/plans/test_plan_use_cases.py::TestUpdatePlanVersion` |
| New route handlers in `cardre/api/routes/plans.py` | the existing `create_plan` and `commit_plan_version` handlers in the same file (note the `_uc` helper that lazy-imports use cases and the `CardreError` → `CardreApiError` mapping for 404/409) |
| New schemas in `cardre/api/schemas.py` | `PlanCreateRequest` / `PlanVersionUpdate` |
| `frontend/src/components/VersionPanel.tsx` edits | the existing "Run selected version" button block in the same file |
| `frontend/src/hooks/useProjectWorkspace.ts` edits | the existing `createPlanMutation` and `runMutation` blocks |

---

# Slice 1 — `CreateCanonicalScorecardVersion` use case + endpoint

**Goal:** a single API call turns an empty plan into a draft plan version
populated with the full 31-step canonical scorecard pathway, parametrized by
a CSV path. This is the keystone slice; it alone makes the acceptance test
bypass obsolete.

**Files to create:**

### 1.1 `cardre/application/plans/create_canonical_scorecard_version.py`

```python
"""CreateCanonicalScorecardVersion — populate a plan with the launch pathway."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cardre.application.ports.node_catalogue import NodeCataloguePort
from cardre.domain.errors import CardreError, ErrorCode
from cardre.domain.plans.scorecard_pathway import build_canonical_scorecard_steps


@dataclass
class CreateCanonicalScorecardVersionCommand:
    plan_id: str
    source_path: str
    # Optional overrides for the two steps users always touch first.
    # All None means "use the canonical defaults from scorecard_pathway.py".
    target_column: str | None = None
    good_values: list[str] | None = None
    bad_values: list[str] | None = None


class CreateCanonicalScorecardVersion:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        node_catalogue: NodeCataloguePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._node_catalogue = node_catalogue

    def __call__(self, command: CreateCanonicalScorecardVersionCommand) -> Any:
        uow = self._uow_factory()
        try:
            # 1. Plan must exist.
            plan = uow.plans.get_plan(command.plan_id)
            if plan is None:
                raise CardreError(
                    f"Plan {command.plan_id!r} not found.",
                    code=ErrorCode.PLAN_NOT_FOUND,
                    context={"plan_id": command.plan_id},
                    status_code=404,
                )

            # 2. Build the canonical step set. build_canonical_scorecard_steps
            #    already resolves node_version/category from the catalogue
            #    and sets the import step's source_path.
            steps = build_canonical_scorecard_steps(
                Path(command.source_path),
                self._node_catalogue.resolve,
            )

            # 3. Apply optional overrides to the define-metadata step.
            #    The import step's source_path is already set by the builder.
            if command.target_column or command.good_values or command.bad_values:
                for i, step in enumerate(steps):
                    if step.canonical_step_id == "define-metadata":
                        params = dict(step.params)
                        if command.target_column is not None:
                            params["target_column"] = command.target_column
                        if command.good_values is not None:
                            params["good_values"] = list(command.good_values)
                        if command.bad_values is not None:
                            params["bad_values"] = list(command.bad_values)
                        from cardre.domain.artifacts import json_logical_hash
                        from cardre.domain.step import StepSpec
                        steps[i] = StepSpec(
                            step_id=step.step_id, node_type=step.node_type,
                            node_version=step.node_version, category=step.category,
                            params=params, params_hash=json_logical_hash(params),
                            parent_step_ids=step.parent_step_ids,
                            branch_label=step.branch_label, position=step.position,
                            canonical_step_id=step.canonical_step_id,
                            branch_id=step.branch_id,
                        )
                        break

            # 4. Persist as a draft version. create_version already exists
            #    on PlanRepoPort and the SQLite adapter.
            pv_id = uow.plans.create_version(
                command.plan_id, steps, is_committed=False,
                description="Canonical scorecard pathway",
            )
            uow.commit()
            return uow.plans.get_version(pv_id)
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
```

Notes for the implementer:
- `build_canonical_scorecard_steps` already sets `params["source_path"]` on
  the `import` step (see `cardre/domain/plans/scorecard_pathway.py:267-268`).
  Do not set it yourself.
- `NodeCataloguePort` is the port interface — import it from
  `cardre.application.ports.node_catalogue`. The concrete `NodeCatalogue`
  lives in `cardre/bootstrap/node_catalogue.py` and is already wired onto the
  `Container` as `container.node_catalogue`.
- The `StepSpec` is a frozen dataclass, so you must reconstruct it to change
  `params` (as shown). This matches how `build_canonical_scorecard_steps`
  itself constructs steps.

### 1.2 Export from `cardre/application/plans/__init__.py`

Add the new use case to the package `__init__.py` alongside the existing
exports:

```python
from cardre.application.plans.create_canonical_scorecard_version import (
    CreateCanonicalScorecardVersion,
    CreateCanonicalScorecardVersionCommand,
)
```

and add both names to `__all__`.

### 1.3 API route in `cardre/api/routes/plans.py`

Add a new request schema to `cardre/api/schemas.py`:

```python
class CanonicalScorecardVersionRequest(BaseModel):
    source_path: str
    target_column: str | None = None
    good_values: list[str] | None = None
    bad_values: list[str] | None = None
```

Add it to `__all__` in `schemas.py`.

In `cardre/api/routes/plans.py`, extend the `_uc` helper to construct the new
use case (it needs the node catalogue, which lives on the container). Add
the command to the returned dict:

```python
from cardre.application.plans.create_canonical_scorecard_version import (
    CreateCanonicalScorecardVersion,
    CreateCanonicalScorecardVersionCommand,
)
...
"create_canonical_version": CreateCanonicalScorecardVersion(_factory, container.node_catalogue),
"CreateCanonicalScorecardVersionCommand": CreateCanonicalScorecardVersionCommand,
```

Then add the route handler. Place it after `create_plan` and before
`get_plan`:

```python
@router.post("/plans/{plan_id}/canonical-version", response_model=PlanVersionResponse, status_code=201)
async def create_canonical_scorecard_version(
    project_id: str,
    plan_id: str,
    body: CanonicalScorecardVersionRequest,
    container=Depends(get_container),
):
    from cardre.domain.errors import CardreError

    uc = _uc(container, project_id)
    try:
        pv = uc["create_canonical_version"](
            uc["CreateCanonicalScorecardVersionCommand"](
                plan_id=plan_id,
                source_path=body.source_path,
                target_column=body.target_column,
                good_values=body.good_values,
                bad_values=body.bad_values,
            )
        )
    except CardreError as exc:
        if exc.code == ErrorCode.PLAN_NOT_FOUND:
            raise CardreApiError(
                code=ErrorCode.PLAN_NOT_FOUND,
                message=str(exc),
                status_code=404,
            ) from exc
        raise
    return plan_version_to_response(pv)
```

Import `CanonicalScorecardVersionRequest` in the existing import block from
`cardre.api.schemas` at the top of `plans.py`.

### 1.4 Tests

Create `tests/application/plans/test_create_canonical_scorecard_version.py`.
Use the `provisioned_project` fixture (from
`tests/application/conftest.py`) and the real `build_default_catalogue` from
`cardre/bootstrap/node_catalogue.py`. Write a tiny CSV to `tmp_path` so the
`import` step's `source_path` points at a real file (the node is not
executed here, but `build_canonical_scorecard_steps` does not open the file
— so a non-existent path is also fine; still, a real file is more
realistic).

```python
import csv
from pathlib import Path

from cardre.application.plans.create_canonical_scorecard_version import (
    CreateCanonicalScorecardVersion,
    CreateCanonicalScorecardVersionCommand,
)
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.plans.scorecard_pathway import canonical_scorecard_step_ids


def _write_csv(path: Path) -> Path:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["x", "credit_risk_class"])
        w.writeheader()
        for i in range(10):
            w.writerow({"x": i, "credit_risk_class": "good" if i % 2 else "bad"})
    return path


def _factory(uow_factory, project_id):
    return lambda: uow_factory.for_project(project_id)


class TestCreateCanonicalScorecardVersion:
    def test_creates_draft_version_with_all_canonical_steps(self, provisioned_project, tmp_path):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        catalogue = build_default_catalogue(Settings())
        uc = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), catalogue)
        csv_path = _write_csv(tmp_path / "in.csv")
        pv = uc(CreateCanonicalScorecardVersionCommand(plan_id=plan_id, source_path=str(csv_path)))
        assert pv is not None
        assert pv.is_committed is False
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv.plan_version_id)
        assert [s.canonical_step_id for s in steps] == canonical_scorecard_step_ids()

    def test_applies_target_column_override(self, provisioned_project, tmp_path):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        catalogue = build_default_catalogue(Settings())
        uc = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), catalogue)
        csv_path = _write_csv(tmp_path / "in.csv")
        pv = uc(CreateCanonicalScorecardVersionCommand(
            plan_id=plan_id, source_path=str(csv_path),
            target_column="y", good_values=["good"], bad_values=["bad"],
        ))
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv.plan_version_id)
        meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
        assert meta.params["target_column"] == "y"
        assert meta.params["good_values"] == ["good"]
        imp = next(s for s in steps if s.canonical_step_id == "import")
        assert imp.params["source_path"] == str(csv_path)

    def test_raises_on_unknown_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        catalogue = build_default_catalogue(Settings())
        uc = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), catalogue)
        from cardre.domain.errors import CardreError
        import pytest
        with pytest.raises(CardreError, match="not found"):
            uc(CreateCanonicalScorecardVersionCommand(plan_id="nope", source_path="x.csv"))
```

Also add an API-level test in
`tests/application/api/test_api_surface.py` mirroring
`test_plan_lifecycle`:

```python
def test_create_canonical_version_populates_steps(app_env, tmp_path):
    import csv
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    plan_resp = client.post(f"/projects/{pid}/plans", json={"name": "P"})
    plan_id = plan_resp.json()["plan_id"]
    csv_path = tmp_path / "in.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["x", "credit_risk_class"])
        w.writeheader()
        w.writerow({"x": 1, "credit_risk_class": "good"})
    resp = client.post(
        f"/projects/{pid}/plans/{plan_id}/canonical-version",
        json={"source_path": str(csv_path)},
    )
    assert resp.status_code == 201, resp.text
    pv = resp.json()
    assert pv["is_committed"] is False
    steps = client.get(f"/projects/{pid}/plan-versions/{pv['plan_version_id']}/steps").json()
    assert len(steps) == 31  # canonical_scorecard_step_ids() has 31 entries
```

### 1.5 Rewrite the acceptance test to use the API

In `tests/acceptance/test_launch_pathway.py`, replace the repository-bypass
block (lines 92-98, the `with container.uow_factory.for_project(project_id)
as uow: pv_id = uow.plans.create_version(...)` block) with:

```python
resp = client.post(
    f"/projects/{project_id}/plans/{plan_id}/canonical-version",
    json={"source_path": str(csv_path)},
)
assert resp.status_code == 201, resp.text
pv_id = resp.json()["plan_version_id"]
```

Also update the test module docstring (lines 1-15): remove the sentence
*"The step graph itself has no public editor endpoint yet (full editor is
future work), so the constructed canonical step set is persisted via the
repository before being committed through the API."* and replace with
something like: *"Plan creation, canonical-version generation, commitment,
and run submission all go through the API."*

### 1.6 Regenerate OpenAPI types

```bash
python3 scripts/generate-openapi-types.py
git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/schema.d.ts
```

Both files must be committed. They are in `GENERATED_FILES` for the
line-count gate, so they don't count against any limit.

### 1.7 Verify Slice 1 in isolation

```bash
. .venv/bin/activate
ruff check --fix
python3 -m pytest tests/application/plans/test_create_canonical_scorecard_version.py \
                 tests/application/api/test_api_surface.py::test_create_canonical_version_populates_steps \
                 tests/acceptance/test_launch_pathway.py -q
make preflight
```

`make preflight` runs the full local gate (ruff, mypy, line-counts,
doc-refs, sidecar-naming, import-lint, pytest, governance, frontend
build/test/typecheck, and the OpenAPI regen + diff). It is the
authoritative local check before pushing.

---

# Slice 2 — `UpdateStepParams` use case + endpoint

**Goal:** let a user edit a single draft step's `params` through the API.
This is a *single-step* editor, not a DAG editor — the user tunes the
canonical pathway's parameters, not its topology.

**Files to create / edit:**

### 2.1 Repo port method

Add to `PlanRepoPort` in `cardre/application/ports/unit_of_work.py`:

```python
def update_step_params(self, plan_version_id: str, step_id: str,
                       params: dict[str, Any], params_hash: str) -> None: ...
```

(Place it after `commit_version`, grouped with the other mutators.)

### 2.2 SQLite adapter method

Add to `cardre/adapters/sqlite/plan_repo.py`:

```python
def update_step_params(self, plan_version_id: str, step_id: str,
                       params, params_hash: str) -> None:
    import json
    self._conn.execute(
        "UPDATE plan_steps SET params_json = ?, params_hash = ? "
        "WHERE plan_version_id = ? AND step_id = ?",
        (json.dumps(params), params_hash, plan_version_id, step_id),
    )
```

Check the affected row count and raise `CardreError(code="STEP_NOT_FOUND")`
if zero rows matched (import `CardreError` from `cardre.domain.errors`).
Look at how other methods in this file handle their imports — they import
`json` / `uuid` / `utc_now_iso` lazily inside the method body, matching the
existing style.

### 2.3 Use case

Create `cardre/application/plans/update_step_params.py`, modeled on
`update_plan_version.py`:

```python
"""UpdateStepParams — edit a single draft step's parameters."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError, ErrorCode


@dataclass
class UpdateStepParamsCommand:
    plan_version_id: str
    step_id: str
    params: dict[str, Any]


class UpdateStepParams:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: UpdateStepParamsCommand) -> None:
        uow = self._uow_factory()
        try:
            existing = uow.plans.get_version(command.plan_version_id)
            if existing is None:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} not found.",
                    code=ErrorCode.PLAN_VERSION_NOT_FOUND,
                    context={"plan_version_id": command.plan_version_id},
                    status_code=404,
                )
            if existing.is_committed:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} is already committed.",
                    code=ErrorCode.PLAN_VERSION_ALREADY_COMMITTED,
                    context={"plan_version_id": command.plan_version_id},
                    status_code=409,
                )
            params_hash = json_logical_hash(command.params)
            uow.plans.update_step_params(
                command.plan_version_id, command.step_id,
                command.params, params_hash,
            )
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
```

Export it from `cardre/application/plans/__init__.py`.

Note: `validate_topology` is NOT re-run here because this endpoint does not
change topology (parent_step_ids unchanged). `CommitPlanVersion` already
runs `validate_topology` before commit, so a bad edit is caught at commit
time. Do not add a topology call to this use case — it would be redundant
and would require re-fetching all steps.

### 2.4 API route

Add a request schema to `cardre/api/schemas.py`:

```python
class StepParamsUpdate(BaseModel):
    params: dict[str, Any]
```

In `cardre/api/routes/plans.py`, add to `_uc`:

```python
from cardre.application.plans.update_step_params import (
    UpdateStepParams,
    UpdateStepParamsCommand,
)
...
"update_step_params": UpdateStepParams(_factory),
"UpdateStepParamsCommand": UpdateStepParamsCommand,
```

Add the route handler after `commit_plan_version`:

```python
@router.patch("/plan-versions/{plan_version_id}/steps/{step_id}", response_model=PlanVersionResponse)
async def update_step_params(
    project_id: str,
    plan_version_id: str,
    step_id: str,
    body: StepParamsUpdate,
    container=Depends(get_container),
):
    from cardre.domain.errors import CardreError

    uc = _uc(container, project_id)
    try:
        uc["update_step_params"](
            uc["UpdateStepParamsCommand"](
                plan_version_id=plan_version_id,
                step_id=step_id,
                params=body.params,
            )
        )
    except CardreError as exc:
        if exc.code == ErrorCode.PLAN_VERSION_NOT_FOUND:
            raise CardreApiError(
                code=ErrorCode.PLAN_VERSION_NOT_FOUND,
                message=str(exc),
                status_code=404,
            ) from exc
        if exc.code == ErrorCode.PLAN_VERSION_ALREADY_COMMITTED:
            raise CardreApiError(
                code=ErrorCode.PLAN_VERSION_IMMUTABLE,
                message=str(exc),
                status_code=409,
            ) from exc
        if exc.code == ErrorCode.STEP_NOT_FOUND:
            raise CardreApiError(
                code=ErrorCode.STEP_NOT_FOUND,
                message=str(exc),
                status_code=404,
            ) from exc
        raise
    pv = uc["get_version"](uc["GetPlanVersionCommand"](plan_version_id=plan_version_id))
    if pv is None:
        raise CardreApiError(
            code=ErrorCode.PLAN_VERSION_NOT_FOUND,
            message=f"Plan version {plan_version_id!r} not found.",
            status_code=404,
        )
    return plan_version_to_response(pv)
```

Note the committed-version mapping to `PLAN_VERSION_IMMUTABLE` (409) — this
matches the existing `update_plan_version` handler's mapping exactly (see
`plans.py:115-120`). `STEP_NOT_FOUND` already exists in `ErrorCode` and in
`frontend/src/api/errorCodes.ts`.

### 2.5 Tests

Create `tests/application/plans/test_update_step_params.py` modeled on
`test_plan_use_cases.py::TestUpdatePlanVersion`. Three cases:
1. Updates a draft step's params; assert `get_version_steps` reflects the
   change and `params_hash` matches `json_logical_hash(new_params)`.
2. Raises `PLAN_VERSION_ALREADY_COMMITTED` on a committed version.
3. Raises `STEP_NOT_FOUND` when the `step_id` does not exist on the
   version.

Add an API-level test in `tests/application/api/test_api_surface.py`:
PATCH a draft step, assert 200 and that the step's params changed; PATCH a
committed version's step, assert 409 `PLAN_VERSION_IMMUTABLE`.

### 2.6 Regenerate OpenAPI types

Same as Slice 1.6.

### 2.7 Verify Slice 2 in isolation

```bash
. .venv/bin/activate
ruff check --fix
python3 -m pytest tests/application/plans/test_update_step_params.py \
                 tests/application/api/test_api_surface.py -q
make preflight
```

---

# Slice 3 — Frontend on-ramp

**Goal:** surface the two new endpoints in the desktop UI. After this slice,
a user can: pick a CSV, click "Generate launch pathway", see the draft
version appear, edit its essential step params, commit, and run — all in
the existing single-page workspace.

This slice intentionally avoids a generic schema-driven form. It renders a
**fixed** list of editable fields on a **fixed** set of canonical step IDs.
No DAG canvas, no step picker.

### 3.1 API client methods

In `frontend/src/api/client.ts`, inside the `forProject` returned object,
add two methods alongside the existing `createPlan` / `listPlanVersions`:

```typescript
createCanonicalVersion: async (
  planId: string,
  body: components["schemas"]["CanonicalScorecardVersionRequest"],
) => {
  const client = makeClient();
  return requireData(
    await client.POST("/projects/{project_id}/plans/{plan_id}/canonical-version", {
      params: { path: { project_id: pid, plan_id: planId } },
      body,
    }),
  );
},
getPlanVersionSteps: async (planVersionId: string) => {
  const client = makeClient();
  return requireData(
    await client.GET("/projects/{project_id}/plan-versions/{plan_version_id}/steps", {
      params: { path: { project_id: pid, plan_version_id: planVersionId } },
    }),
  );
},
updateStepParams: async (
  planVersionId: string,
  stepId: string,
  body: components["schemas"]["StepParamsUpdate"],
) => {
  const client = makeClient();
  return requireData(
    await client.PATCH("/projects/{project_id}/plan-versions/{plan_version_id}/steps/{step_id}", {
      params: { path: { project_id: pid, plan_version_id: planVersionId, step_id: stepId } },
      body,
    }),
  );
},
```

The path constants and the `CanonicalScorecardVersionRequest` /
`StepParamsUpdate` types will exist in `schema.d.ts` after the Slice 1/2
OpenAPI regeneration. Run `python3 scripts/generate-openapi-types.py` before
writing frontend code.

### 3.2 `useProjectWorkspace.ts` additions

Add three things to `frontend/src/hooks/useProjectWorkspace.ts`:

1. **State** for the chosen source path and a per-step param-edit buffer:
   ```ts
   const [sourcePath, setSourcePath] = useState<string | null>(null);
   ```
2. **A query** for the selected draft version's steps (so the UI can render
   the param editor). Gate it on the selected version being a *draft*:
   ```ts
   const stepsQuery = useQuery({
     queryKey: ["planVersionSteps", scope.projectId, effectiveSelectedVersionId],
     queryFn: () => scoped.getPlanVersionSteps(effectiveSelectedVersionId!),
     enabled: !!effectiveSelectedVersionId && !selectedVersion?.is_committed,
   });
   ```
3. **A mutation** to generate the canonical version:
   ```ts
   const createCanonicalVersionMutation = useMutation({
     mutationFn: () =>
       scoped.createCanonicalVersion(effectiveSelectedPlanId!, { source_path: sourcePath! }),
     onSuccess: (pv) => {
       setError(null);
       setSelectedVersionId(pv.plan_version_id);
       queryClient.invalidateQueries({ queryKey: ["planVersions", scope.projectId, effectiveSelectedPlanId] });
     },
     onError: (err) => setError(toErrorMessage(err)),
   });
   ```
4. **A mutation** to update a step's params:
   ```ts
   const updateStepParamsMutation = useMutation({
     mutationFn: ({ stepId, params }: { stepId: string; params: Record<string, unknown> }) =>
       scoped.updateStepParams(effectiveSelectedVersionId!, stepId, { params }),
     onSuccess: () => {
       setError(null);
       queryClient.invalidateQueries({ queryKey: ["planVersionSteps", scope.projectId, effectiveSelectedVersionId] });
     },
     onError: (err) => setError(toErrorMessage(err)),
   });
   ```
5. Return all of these from the hook.

Also invalidate `["planVersions", ...]` after `createCanonicalVersion` and
`["planVersionSteps", ...]` after `updateStepParams`, as shown.

### 3.3 `VersionPanel.tsx` — replace the dead-end

The empty-state branch at `frontend/src/components/VersionPanel.tsx:117`
currently renders `<div>No versions found.</div>` with no CTA. Replace it
with a small form: a file picker for the CSV path and a "Generate launch
pathway" button.

The file picker: in the Tauri desktop context, use the native dialog
(`@tauri-apps/plugin-dialog` `open()`). In the browser dev path, a plain
`<input type="file">` is fine. Detect Tauri via
``typeof window.__TAURI_INTERNALS__ !== "undefined"`` (or whatever the
existing Tauri detection pattern is in the repo — grep for `__TAURI__`
before assuming). If unsure, ship the plain `<input type="file">` first and
upgrade to the Tauri dialog in a follow-up; the API only needs the path
string.

Pass the new props from `ProjectView.tsx`:

```tsx
<VersionPanel
  ...existing props...
  sourcePath={ws.sourcePath}
  onSourcePathChange={ws.setSourcePath}
  onGeneratePathway={() => ws.createCanonicalVersionMutation.mutate()}
  generatePathwayPending={ws.createCanonicalVersionMutation.isPending}
/>
```

The button should be disabled when `sourcePath` is empty or
`generatePathwayPending` is true. On success, `selectedVersionId` is set by
the mutation's `onSuccess` and the existing `versionsQuery` refetch will
show the new draft — no manual navigation needed.

### 3.4 New `StepParamsEditor.tsx` component

Create `frontend/src/components/StepParamsEditor.tsx`. It renders a fixed
list of fields for a fixed set of canonical step IDs. The list:

| canonical_step_id | editable params |
| --- | --- |
| `import` | `source_path` |
| `define-metadata` | `target_column`, `good_values` (comma-separated string in the UI → `list[str]` on save), `bad_values` (same), `purpose`, `product`, `segment`, `observation_window`, `performance_window` |
| `apply-exclusions` | `rules` (read-only JSON area for v1; editable later) |
| `sample-definition` | `sample_method`, `sample_domain`, `sample_description` |
| `split` | `target_column` |
| `validation-metrics` | `require_test` (checkbox), `require_oot` (checkbox), `fail_on_missing_score` (checkbox) |

Render only steps whose `canonical_step_id` is in this list. For each,
render one input per field, pre-populated from `step.params`. On blur (or a
per-step "Save" button), call `ws.updateStepParamsMutation.mutate({ stepId:
step.step_id, params: editedParams })`.

Keep the component under 600 lines (the TS threshold). It will be well
under — it is a small fixed-form component. Do not build a generic
schema-driven form renderer; that is explicitly out of scope.

Wire it into `ProjectView.tsx` below `VersionPanel`, rendered only when the
selected version is a draft:

```tsx
{ws.selectedVersion && !ws.selectedVersion.is_committed && (
  <StepParamsEditor
    steps={ws.stepsQuery.data ?? []}
    stepsLoading={ws.stepsQuery.isLoading}
    onSaveStep={(stepId, params) =>
      ws.updateStepParamsMutation.mutate({ stepId, params })
    }
    savePending={ws.updateStepParamsMutation.isPending}
  />
)}
```

### 3.5 Commit button

`VersionPanel.tsx` already gates "Run selected version" on
`is_committed`. Add a "Commit version" button next to it, visible only when
the selected version is a draft. It calls the existing
`POST /plan-versions/{id}/commit` endpoint — add a small mutation to
`useProjectWorkspace.ts`:

```ts
const commitVersionMutation = useMutation({
  mutationFn: () => scoped.commitPlanVersion(effectiveSelectedVersionId!),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["planVersions", scope.projectId, effectiveSelectedPlanId] });
  },
  onError: (err) => setError(toErrorMessage(err)),
});
```

and a `commitPlanVersion` method on the `forProject` object in `client.ts`
(POST to `/projects/{project_id}/plan-versions/{plan_version_id}/commit`).
The endpoint already exists (`plans.py:134`); this is just the client
method.

### 3.6 Frontend tests

Update `frontend/src/hooks/__tests__/useProjectWorkspace.test.tsx`:
add `createCanonicalVersion`, `getPlanVersionSteps`, `updateStepParams`,
and `commitPlanVersion` to the `mockScoped` object at the top of the file
(lines 27-37). Add at least one test that asserts
`createCanonicalVersion` is called and `selectedVersionId` is set on
success.

Update `frontend/src/components/__tests__/ProjectView.test.tsx`: add the
same new methods to its `mockScoped` (lines 18-28). Add a test asserting
the "Generate launch pathway" button renders when no versions exist.

### 3.7 Verify Slice 3

```bash
. .venv/bin/activate
cd frontend && npm run lint && npm run format:check && npm test && npx tsc --noEmit && npm run build
```

If `format:check` fails, run `npm run format` and re-stage.

---

# Slice 4 — Acceptance test goes through the API (the gate)

This slice is the automated proxy for the release gate. It is mostly
already covered by Slice 1.5, but if you want the test to also prove the
*edit* loop (not just generation), add one more assertion to
`test_launch_pathway.py` between the canonical-version POST and the commit
POST:

```python
# 5b. Edit the define-metadata step's target_column through the API,
#     proving the user-reachable parameter-edit loop.
steps = client.get(f"/projects/{project_id}/plan-versions/{pv_id}/steps").json()
meta_step = next(s for s in steps if s["canonical_step_id"] == "define-metadata")
patch_resp = client.patch(
    f"/projects/{project_id}/plan-versions/{pv_id}/steps/{meta_step['step_id']}",
    json={"params": {**meta_step["params"], "target_column": "credit_risk_class"}},
)
assert patch_resp.status_code == 200, patch_resp.text
```

This is optional but valuable: it proves the *edit* path is reachable, not
just generation. The commit + run + assertion sections of the test already
go through the API and stay unchanged.

After this, the test module docstring's "no public editor endpoint yet"
comment is false by construction — the test itself uses the public editor
endpoint. Remove that sentence from the docstring.

---

# Sequencing and PR strategy

Ship in this order. Each slice is a self-contained PR that independently
improves reachability and passes the full gate.

1. **Slice 1** (backend generation) — the keystone. Lands the use case,
   route, schema, tests, OpenAPI regen, and the acceptance-test rewrite.
   After this PR, the acceptance test no longer bypasses the API.
2. **Slice 2** (backend step-param edit) — lands the edit use case, route,
   and tests. Independent of Slice 1's UI but depends on Slice 1's
   canonical-version endpoint existing for the full journey test.
3. **Slice 3** (frontend) — lands the UI. Depends on Slices 1 and 2 being
   merged so `schema.d.ts` has the new endpoints.
4. **Slice 4** (optional edit-loop assertion in the acceptance test) — a
   tiny PR that hardens the gate. Can be folded into Slice 2 if Slice 2 is
   not yet merged when Slice 1 lands.

Every PR must pass `make preflight` before pushing, then
`scripts/pr-gate.sh` for CI (per `AGENTS.md`). Do not request human review
until the PR gate prints `CI GREEN`.

# Final verification: the full journey

After all four slices are merged, verify the release-gate sentence
end-to-end on a clean clone:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[sidecar,dev,test]"
python3 -m pytest tests/acceptance/test_launch_pathway.py -q
```

Then the desktop app, by hand:
1. Install the Tauri build.
2. Create a project.
3. Create a plan.
4. Pick a CSV.
5. Click "Generate launch pathway".
6. Edit `target_column` in the `define-metadata` step.
7. Click "Commit version".
8. Click "Run selected version" (async).
9. Wait for the run to reach `succeeded`; inspect steps and evidence.
10. Export the scorecard (Python + SQL) and the report.

If all ten steps succeed without direct database or Python access, the
release gate is met.