# Deferred / Optional Node Exposure — Implementation Guide

Read `README.md` first for the exposure model, validation context, scope,
and TDD ordering. This file is the step-by-step guide with test outlines
and code snippets for a smaller LLM to follow.

**Conventions:**
- Strict red-green-refactor per the TDD ordering in `README.md`.
- Run `make lint && make typecheck && make test` after every green step.
- Do not add comments unless asked.
- Mirror existing code style (dataclasses in `cardre/`, Pydantic in
  `sidecar/models.py`, the `status="coming_soon"` disabled-option pattern
  in the frontend).
- File:line references are accurate as of the inspection; re-read each
  file before editing because earlier steps may have shifted line numbers.

---

## Step 1 — Registry availability introspection

### Red: `tests/test_node_registry_availability.py` (new)

```python
"""Tests for NodeRegistry availability introspection (launch vs deferred,
optional-dependency importability)."""
from __future__ import annotations

import pytest

from cardre.registry import NodeRegistry, NodeAvailability


class TestAvailability:
    def test_launch_node_available_in_launch_mode(self) -> None:
        reg = NodeRegistry.with_defaults()
        av = reg.availability("cardre.logistic_regression")
        assert av.available is True
        assert av.tier == "launch"
        assert av.disabled_reason is None
        assert av.missing_optional_dependencies == []

    def test_deferred_node_unavailable_in_launch_mode(self) -> None:
        reg = NodeRegistry.with_defaults()
        av = reg.availability("cardre.gradient_boosting_classifier")
        assert av.available is False
        assert av.tier == "deferred"
        assert av.disabled_reason is not None
        assert "launch" in av.disabled_reason.lower()

    def test_deferred_node_available_when_launch_mode_off(self, monkeypatch) -> None:
        monkeypatch.setenv("CARDRE_LAUNCH_MODE", "0")
        reg = NodeRegistry.with_defaults()
        av = reg.availability("cardre.gradient_boosting_classifier")
        assert av.tier == "deferred"
        # available depends only on optional deps here (sklearn GBDT has none)
        assert av.available is True
        assert av.disabled_reason is None

    def test_optional_dep_missing_marks_unavailable(self, monkeypatch) -> None:
        reg = NodeRegistry.with_defaults()
        # Force the boosting probe to report "not installed"
        from cardre import registry as regmod
        monkeypatch.setattr(regmod, "_probe_optional_dep",
                            lambda group: group != "boosting")
        av = reg.availability("cardre.xgboost_classifier")
        assert av.available is False
        assert "boosting" in av.missing_optional_dependencies
        assert av.disabled_reason is not None
        assert "boosting" in av.disabled_reason.lower()

    def test_optional_dep_present_marks_available_when_not_deferred(self, monkeypatch) -> None:
        reg = NodeRegistry.with_defaults()
        from cardre import registry as regmod
        monkeypatch.setattr(regmod, "_probe_optional_dep", lambda group: True)
        # xgboost is deferred, so in launch mode it stays unavailable
        monkeypatch.setenv("CARDRE_LAUNCH_MODE", "0")
        av = reg.availability("cardre.xgboost_classifier")
        assert av.available is True
        assert av.missing_optional_dependencies == []

    def test_is_available_matches_availability(self) -> None:
        reg = NodeRegistry.with_defaults()
        assert reg.is_available("cardre.logistic_regression") is True
        assert reg.is_available("cardre.gradient_boosting_classifier") is False

    def test_availability_unknown_node_raises(self) -> None:
        reg = NodeRegistry.with_defaults()
        with pytest.raises(KeyError):
            reg.availability("cardre.does_not_exist")
```

### Green: `cardre/registry.py`

Add a `NodeAvailability` dataclass and the probe/availability methods.
Keep the existing `instantiate` deferred guard; extend it to raise the
new clean optional-dep error (the error class is added in Step 2, so
write Step 2 immediately after this one — or stub the import).

Add near the top of `cardre/registry.py`:

```python
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field

from cardre.audit import NodeType
from cardre.config import CardreConfig


@dataclass(frozen=True)
class NodeAvailability:
    """Whether a node type can be instantiated right now, and why not."""
    available: bool
    tier: str  # "launch" | "deferred"
    disabled_reason: str | None = None
    missing_optional_dependencies: list[str] = field(default_factory=list)


# Map of pyproject optional-dependency group -> importable module name(s)
# that prove the group is installed. Keep this as the single source of
# truth for optional-dep probing.
_OPTIONAL_DEP_MODULES: dict[str, tuple[str, ...]] = {
    "boosting": ("xgboost", "lightgbm", "catboost"),
    "imbalance": ("imblearn",),
    "explain": ("shap", "lime"),
    "deep": ("torch",),
    "optimal-binning": ("optbinning",),
}


def _probe_optional_dep(group: str) -> bool:
    """Return True if every module proving *group* is importable."""
    for mod in _OPTIONAL_DEP_MODULES.get(group, ()):
        if importlib.util.find_spec(mod) is None:
            return False
    return True
```

Add methods to `NodeRegistry`:

```python
    def availability(self, node_type: str) -> NodeAvailability:
        cls = self.resolve(node_type)
        is_deferred = getattr(cls, "_deferred", False)
        tier = "deferred" if is_deferred else "launch"

        missing = [
            g for g in (getattr(cls, "optional_dependencies", None) or [])
            if not _probe_optional_dep(g)
        ]

        if is_deferred and CardreConfig.from_env().launch_mode:
            return NodeAvailability(
                available=False,
                tier=tier,
                disabled_reason=(
                    "Not available in launch mode. "
                    "This method will be enabled in a future release."
                ),
                missing_optional_dependencies=missing,
            )

        if missing:
            return NodeAvailability(
                available=False,
                tier=tier,
                disabled_reason=(
                    f"Optional dependency group(s) not installed: "
                    f"{', '.join(missing)}. "
                    f"Install with: pip install -e '.[{','.join(missing)}]'"
                ),
                missing_optional_dependencies=missing,
            )

        return NodeAvailability(available=True, tier=tier)

    def is_available(self, node_type: str) -> bool:
        return self.availability(node_type).available
```

Update `instantiate` to raise the clean optional-dep error when not
deferred-but-blocked (Step 2 defines the class):

```python
    def instantiate(self, node_type: str) -> NodeType:
        cls = self.resolve(node_type)
        av = self.availability(node_type)
        if not av.available:
            if av.tier == "deferred" and CardreConfig.from_env().launch_mode:
                from cardre.errors import NodeNotAvailableForLaunch
                raise NodeNotAvailableForLaunch(
                    f"Node {node_type!r} is not available in launch mode. "
                    f"It will be available in a future release."
                )
            if av.missing_optional_dependencies:
                from cardre.errors import OptionalDependencyNotInstalled
                raise OptionalDependencyNotInstalled(
                    node_type=node_type,
                    missing_groups=av.missing_optional_dependencies,
                )
        return cls()
```

Run: `python3 -m pytest tests/test_node_registry_availability.py -q`.
Expect green after Step 2.

---

## Step 2 — New error classes

### Red: `tests/test_optional_dependency_errors.py` (new)

```python
"""Tests for OptionalDependencyNotInstalled and PlanContainsUnavailableNodesError."""
from __future__ import annotations

import pytest

from cardre.errors import (
    OptionalDependencyNotInstalled,
    PlanContainsUnavailableNodesError,
    NodeNotAvailableForLaunch,
)


class TestOptionalDependencyNotInstalled:
    def test_has_code_and_missing_groups(self) -> None:
        err = OptionalDependencyNotInstalled(
            node_type="cardre.xgboost_classifier",
            missing_groups=["boosting"],
        )
        assert err.code == "OPTIONAL_DEPENDENCY_NOT_INSTALLED"
        assert err.status_code == 400
        assert "boosting" in err.message
        assert "cardre.xgboost_classifier" in err.message
        assert err.context["missing_groups"] == ["boosting"]

    def test_install_hint_in_message(self) -> None:
        err = OptionalDependencyNotInstalled(
            node_type="cardre.xgboost_classifier",
            missing_groups=["boosting", "explain"],
        )
        assert "boosting" in err.message
        assert "explain" in err.message


class TestPlanContainsUnavailableNodesError:
    def test_carries_step_issues(self) -> None:
        issues = [
            {"step_id": "gbdt", "node_type": "cardre.gradient_boosting_classifier",
             "disabled_reason": "Not available in launch mode."},
        ]
        err = PlanContainsUnavailableNodesError(issues=issues)
        assert err.code == "PLAN_CONTAINS_UNAVAILABLE_NODES"
        assert err.status_code == 400
        assert err.context["issues"] == issues
        assert "gbdt" in err.message
```

### Green: `cardre/errors.py`

Add next to the existing `NodeNotAvailableForLaunch` (around line 101).
First read `cardre/errors.py` to confirm the `CardreError` base carries
`code`, `message`, `context`, `status_code` attributes (the
error-handling sprint README says Batch 0 added them — verify before
writing; if the base only has `code`/`status_code`, set `message` via
`__init__` and store `context` on the instance).

```python
class OptionalDependencyNotInstalled(CardreError):
    """Raised when a node's optional dependency group is not installed."""
    code = "OPTIONAL_DEPENDENCY_NOT_INSTALLED"
    status_code = 400

    def __init__(self, node_type: str, missing_groups: list[str]) -> None:
        self.node_type = node_type
        self.missing_groups = list(missing_groups)
        hint = f"pip install -e '.[{','.join(missing_groups)}]'"
        message = (
            f"Node {node_type!r} requires optional dependency group(s) "
            f"{missing_groups} which are not installed. Install with: {hint}"
        )
        super().__init__(message)
        self.context = {"node_type": node_type, "missing_groups": list(missing_groups)}


class PlanContainsUnavailableNodesError(CardreError):
    """Raised before a run starts when a plan contains unavailable nodes."""
    code = "PLAN_CONTAINS_UNAVAILABLE_NODES"
    status_code = 400

    def __init__(self, issues: list[dict]) -> None:
        self.issues = issues
        step_ids = ", ".join(i["step_id"] for i in issues)
        message = (
            f"Plan contains {len(issues)} unavailable node(s): {step_ids}. "
            "See context for details."
        )
        super().__init__(message)
        self.context = {"issues": issues}
```

> **Verify the `CardreError` base shape first.** Read
> `cardre/errors.py:21` — if `__init__(self, message, *, code=..., ...)` is
> the real signature, adapt the `super().__init__(message)` calls to match.
> Export both names in the `__all__` tuple at the bottom of `errors.py`.

Run: `python3 -m pytest tests/test_optional_dependency_errors.py tests/test_node_registry_availability.py -q`.

---

## Step 3 — Set `optional_dependencies` on node classes

### Red: extend `tests/test_node_registry_availability.py`

Append:

```python
class TestNodeClassOptionalDeps:
    @pytest.mark.parametrize("node_type,expected_group", [
        ("cardre.xgboost_classifier", "boosting"),
        ("cardre.lightgbm_classifier", "boosting"),
        ("cardre.catboost_classifier", "boosting"),
    ])
    def test_boosting_nodes_declare_optional_dep(self, node_type, expected_group, monkeypatch):
        from cardre import registry as regmod
        monkeypatch.setattr(regmod, "_probe_optional_dep", lambda g: g != expected_group)
        monkeypatch.setenv("CARDRE_LAUNCH_MODE", "0")
        reg = NodeRegistry.with_defaults()
        av = reg.availability(node_type)
        assert expected_group in av.missing_optional_dependencies

    def test_smote_node_declares_imbalance(self, monkeypatch):
        from cardre import registry as regmod
        monkeypatch.setattr(regmod, "_probe_optional_dep", lambda g: g != "imbalance")
        monkeypatch.setenv("CARDRE_LAUNCH_MODE", "0")
        reg = NodeRegistry.with_defaults()
        av = reg.availability("cardre.smote_training_data")
        assert "imbalance" in av.missing_optional_dependencies
```

### Green: `cardre/nodes/*.py`

Set the class attribute on each node. Read each file first to confirm the
class name and that it inherits `NodeType`.

- `cardre/nodes/boosting.py` — `XGBoostClassifierNode`,
  `LightGBMClassifierNode`, `CatBoostClassifierNode`: add
  `optional_dependencies = ["boosting"]` as a class attribute.
- `cardre/nodes/reject_inference.py` or wherever
  `SmoteTrainingDataNode` lives (grep for `class SmoteTrainingDataNode`)
  — add `optional_dependencies = ["imbalance"]`.
- `cardre/nodes/explainability.py` — `ModelExplainabilityNode`: add
  `optional_dependencies = ["explain"]`.

> **Note:** `smote` and `explainability` are already `_deferred`, so in
> launch mode the deferred reason wins. The attribute still matters for
> non-launch mode. Keep the existing `_MODEL_FAMILIES` meta in
> `sidecar/routes/node_types.py` as a display fallback; the registry now
> reads the class attribute first.

> **Do not** remove `optional_dependencies = None` default on
> `NodeType` (`cardre/audit.py:124`).

Run: `python3 -m pytest tests/test_node_registry_availability.py -q`.

---

## Step 4 — Pre-execution validation gate

### Red: `tests/test_plan_executability.py` (new)

```python
"""A plan containing a deferred node must be rejected BEFORE any run row
is created or step executed."""
from __future__ import annotations

import pytest

from cardre.audit import StepSpec
from cardre.errors import PlanContainsUnavailableNodesError
from cardre.registry import NodeRegistry
from cardre.services.run_service import RunService


def _plan_with_deferred_node(store, project_id: str) -> str:
    plan_id = store.create_plan(project_id, "deferred-plan")
    steps = [
        StepSpec(
            step_id="gbdt",
            node_type="cardre.gradient_boosting_classifier",  # deferred
            node_version="1",
            category="fit",
            parent_step_ids=[],
            params={},
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps, description="has deferred")
    return pv_id


class TestPreExecutionGate:
    def test_run_plan_rejects_deferred_node_before_run_row(self, store) -> None:
        # store fixture creates an initialised ProjectStore in a tmp dir
        project_id = "proj-1"
        store.create_project(project_id, name="t") if hasattr(store, "create_project") else None
        pv_id = _plan_with_deferred_node(store, project_id)

        service = RunService(store)
        with pytest.raises(PlanContainsUnavailableNodesError) as exc:
            service.run_plan(plan_version_id=pv_id, run_scope="full_plan", sync=True)

        # No run row created
        runs = store.list_runs(plan_version_id=pv_id)
        assert runs == [], "a run row was created despite the unavailable-node gate"

        # No run-step records
        # (if the store exposes a list_run_steps method, assert it is empty;
        #  otherwise assert list_runs is empty which implies no steps ran)
        assert exc.value.context["issues"][0]["node_type"] == "cardre.gradient_boosting_classifier"
        assert exc.value.context["issues"][0]["step_id"] == "gbdt"

    def test_executor_validate_plan_executability_lists_issues(self, store) -> None:
        from cardre.executor import PlanExecutor
        project_id = "proj-1"
        pv_id = _plan_with_deferred_node(store, project_id)

        executor = PlanExecutor(NodeRegistry.with_defaults())
        issues = executor.validate_plan_executability(store, pv_id)
        assert len(issues) == 1
        assert issues[0]["node_type"] == "cardre.gradient_boosting_classifier"
        assert issues[0]["available"] is False

    def test_clean_plan_has_no_issues(self, store) -> None:
        from cardre.executor import PlanExecutor
        project_id = "proj-1"
        plan_id = store.create_plan(project_id, "clean-plan")
        steps = [
            StepSpec(step_id="imp", node_type="cardre.import_dataset",
                     node_version="1", category="import", parent_step_ids=[], params={}),
        ]
        pv_id = store.create_plan_version(plan_id, steps, description="clean")
        executor = PlanExecutor(NodeRegistry.with_defaults())
        assert executor.validate_plan_executability(store, pv_id) == []
```

> **Read `cardre/store/project_store.py`** to confirm the real
> `create_project` / `create_plan` / `create_plan_version` signatures
> before finalising the test fixtures. The `store` fixture in
> `tests/conftest.py` returns an initialised `ProjectStore`. Adjust the
> helper above to match the actual API (e.g. `create_plan` may not need
> `project_id`).

### Green: `cardre/executor.py` + `cardre/services/run_service.py`

In `cardre/executor.py`, add a method to `PlanExecutor`:

```python
    def validate_plan_executability(
        self, store: ProjectStore, plan_version_id: str,
    ) -> list[dict]:
        """Return one issue dict per step whose node_type is unavailable.

        Each issue: {step_id, node_type, available, disabled_reason,
                     missing_optional_dependencies, tier}.
        Returns [] when every step's node is available. Does not mutate.
        """
        pv = store.get_plan_version(plan_version_id)
        if pv is None:
            from cardre.errors import CardreError
            raise CardreError(
                f"Plan version {plan_version_id} not found",
                code="PLAN_VERSION_NOT_FOUND",
                context={"plan_version_id": plan_version_id},
            )
        steps = pv["steps"]  # confirm the key name by reading the store
        issues: list[dict] = []
        for spec in steps:
            av = self._registry.availability(spec.node_type)
            if not av.available:
                issues.append({
                    "step_id": spec.step_id,
                    "node_type": spec.node_type,
                    "available": False,
                    "disabled_reason": av.disabled_reason,
                    "missing_optional_dependencies": av.missing_optional_dependencies,
                    "tier": av.tier,
                })
        return issues
```

> **Confirm the `pv` dict shape** by reading
> `cardre/store/project_store.py` `get_plan_version` — the steps may be
> stored as dicts that need to be rehydrated into `StepSpec`, or already
# be `StepSpec` instances. Rehydrate if needed (the executor's
> `_execute_step` already does this — mirror it).

In `cardre/services/run_service.py`, call the gate at the top of
`run_plan`, **before** `store.create_run` (currently `:102`):

```python
    def run_plan(self, plan_version_id, run_scope="full_plan", branch_id=None,
                 target_step_id=None, force=False, sync=False) -> RunResponse:
        pv = self._store.get_plan_version(plan_version_id)
        if pv is None:
            raise CardreError(...)  # keep existing

        # NEW: pre-execution availability gate
        from cardre.executor import PlanExecutor
        executor = PlanExecutor(self._registry if hasattr(self, "_registry")
                                else NodeRegistry.with_defaults())
        issues = executor.validate_plan_executability(self._store, plan_version_id)
        if issues:
            from cardre.errors import PlanContainsUnavailableNodesError
            raise PlanContainsUnavailableNodesError(issues=issues)

        # ... rest unchanged (governance check, preflight, create_run, ...)
```

> **Read `RunService.__init__`** to see whether it already holds a
> `NodeRegistry` instance. If not, construct one locally
> (`NodeRegistry.with_defaults()`) for the gate — do not add a constructor
> parameter. The executor already does this at `run_service.py:118`.

> **Important:** the gate must run for both sync and async paths (it is
> before the `if sync:` branch), and must raise *before*
> `store.create_run` so no run row is left behind. The test asserts
> `store.list_runs(pv_id) == []`.

Run: `python3 -m pytest tests/test_plan_executability.py -q`.

---

## Step 5 — API model + route availability fields

### Red: `tests/test_node_types_api.py` (new)

```python
"""Tests for /node-types availability fields in launch mode."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.api]


class TestNodeTypesLaunchMode:
    def test_deferred_node_marked_unavailable(self, client):
        resp = client.get("/node-types")
        assert resp.status_code == 200
        data = resp.json()
        deferred = [n for n in data["node_types"] if n["tier"] == "deferred"]
        assert deferred, "expected at least one deferred node"
        for n in deferred:
            assert n["available"] is False
            assert n["disabled_reason"] is not None
            assert "launch" in n["disabled_reason"].lower()

    def test_launch_node_marked_available(self, client):
        resp = client.get("/node-types")
        data = resp.json()
        logistic = next(n for n in data["node_types"]
                        if n["node_type"] == "cardre.logistic_regression")
        assert logistic["available"] is True
        assert logistic["disabled_reason"] is None

    def test_available_only_filters_deferred(self, client):
        resp = client.get("/node-types?available_only=true")
        data = resp.json()
        for n in data["node_types"]:
            assert n["available"] is True, f"{n['node_type']} should have been filtered"

    def test_schema_endpoint_carries_availability(self, client):
        resp = client.get("/node-types/cardre.gradient_boosting_classifier/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["disabled_reason"] is not None

    def test_boosting_node_reports_missing_dep(self, client, monkeypatch):
        from cardre import registry as regmod
        monkeypatch.setattr(regmod, "_probe_optional_dep", lambda g: g != "boosting")
        resp = client.get("/node-types")
        xgb = next(n for n in resp.json()["node_types"]
                   if n["node_type"] == "cardre.xgboost_classifier")
        # deferred in launch mode, but missing dep should still be listed
        assert "boosting" in xgb["missing_optional_dependencies"]
```

> The `client` fixture (`tests/conftest.py:23`) builds the app with
> `CARDRE_LAUNCH_MODE` defaulting to True. For the non-launch variant,
> add a second test class guarded by an env-setter or skip.

### Green: `sidecar/models.py`

Extend `NodeTypeItem` (`sidecar/models.py:686`):

```python
class NodeTypeItem(BaseModel):
    node_type: str
    version: str
    category: str
    tier: str = "available"
    available: bool = True
    disabled_reason: str | None = None
    missing_optional_dependencies: list[str] = Field(default_factory=list)
    description: str = ""
    model_family: str | None = None
    feature_strategies: list[str] = Field(default_factory=list)
    interpretability_level: str | None = None
    champion_eligibility: str | None = None
    optional_dependencies: list[str] = Field(default_factory=list)
    input_roles: list[str] = Field(default_factory=list)
    output_roles: list[str] = Field(default_factory=list)
```

Extend `NodeTypeSchemaResponse` (`sidecar/models.py:739`) — read it
first, then add:

```python
    available: bool = True
    disabled_reason: str | None = None
```

### Green: `sidecar/routes/node_types.py`

In `list_node_types` (`:148`), compute availability and accept the
query param:

```python
from fastapi import APIRouter, HTTPException, Query

@router.get("/node-types", response_model=NodeTypeListResponse)
def list_node_types(
    available_only: bool = Query(default=False, description="Exclude unavailable nodes"),
) -> NodeTypeListResponse:
    registry = _get_registry()
    items: list[NodeTypeItem] = []
    for node_type in sorted(registry.list_types()):
        cls = registry.resolve(node_type)
        if getattr(cls, "is_internal", False):
            continue
        meta = _MODEL_FAMILIES.get(node_type, {})
        av = registry.availability(node_type)
        if available_only and not av.available:
            continue
        items.append(NodeTypeItem(
            node_type=node_type,
            version=getattr(cls, "version", "1"),
            category=getattr(cls, "category", "unknown"),
            tier=av.tier,
            available=av.available,
            disabled_reason=av.disabled_reason,
            missing_optional_dependencies=av.missing_optional_dependencies,
            description=getattr(cls, "description", None) or meta.get("description", ""),
            model_family=getattr(cls, "model_family", None) or meta.get("model_family"),
            feature_strategies=getattr(cls, "feature_strategies", None) or meta.get("feature_strategies", []),
            interpretability_level=getattr(cls, "interpretability_level", None) or meta.get("interpretability_level"),
            champion_eligibility=getattr(cls, "champion_eligibility", None) or meta.get("champion_eligibility"),
            optional_dependencies=getattr(cls, "optional_dependencies", None) or meta.get("optional_dependencies", []),
            input_roles=getattr(cls, "input_roles", []),
            output_roles=getattr(cls, "output_roles", []),
        ))
    return NodeTypeListResponse(node_types=items, count=len(items))
```

> Replace the existing `tier="deferred" if is_deferred else "launch"`
> line with `tier=av.tier` and drop the now-unused `is_deferred` local.

In `get_node_type_schema` (`:222`), add availability to the response:

```python
    av = registry.availability(node_type)
    return NodeTypeSchemaResponse(
        node_type=node_type,
        version=schema.node_version,
        title=schema.title,
        methods=methods,
        params_schema=params_schema,
        defaults=defaults,
        description=meta.get("description", ""),
        available=av.available,
        disabled_reason=av.disabled_reason,
    )
```

Run: `python3 -m pytest tests/test_node_types_api.py tests/test_api_contracts.py tests/test_sidecar_api.py -q`.

---

## Step 6 — Frontend disabled banner

### Red: extend `frontend/src/components/__tests__/SchemaDrivenParamsEditor.test.tsx`

The existing test mocks `../../api/client` directly — mirror that pattern
for consistency with the file. Append:

```typescript
  it("renders a disabled banner and hides Save when schema.available is false", async () => {
    (api.getNodeTypeSchema as ReturnType<typeof vi.fn>).mockResolvedValue({
      node_type: "cardre.gradient_boosting_classifier",
      version: "1",
      title: "Gradient Boosting",
      methods: [{ id: "gbdt", label: "GBDT", status: "available", params: [] }],
      params_schema: {},
      defaults: {},
      description: "",
      available: false,
      disabled_reason: "Not available in launch mode.",
    });

    renderWithClient(<SchemaDrivenParamsEditor {...BASE_PROPS} nodeType="cardre.gradient_boosting_classifier" />);

    await waitFor(() => {
      expect(screen.getByText(/not available in launch mode/i)).toBeTruthy();
    });
    // Save button must not be rendered
    expect(screen.queryByRole("button", { name: /save params/i })).toBeNull();
    // updateStepParams must never have been called
    expect(api.updateStepParams).not.toHaveBeenCalled();
  });
```

> If `getByRole` is not imported, import `screen` already covers it via
> `@testing-library/react`. `queryByRole` is available on `screen`.

### Green: `frontend/src/components/params/SchemaDrivenParamsEditor.tsx`

1. Extend `SafeSchema` in `frontend/src/components/params/paramsTypes.ts`
   with `available?: boolean` and `disabled_reason?: string | null`.
2. In `normalizeSchema` (`SchemaDrivenParamsEditor.tsx:63`), read them:

```typescript
    available: raw.available !== false,  // default true when absent
    disabled_reason: (raw.disabled_reason as string | null | undefined) ?? null,
```

3. After the `schemaError || !schema || !schema.methods` fallback block
   (around `:328`), insert an unavailable-state branch **before** the
   normal render:

```tsx
  if (schema && schema.available === false) {
    return (
      <div style={{ borderTop: `1px solid ${theme.border}`, marginTop: 12, paddingTop: 12 }}>
        <div style={{
          fontSize: 11, color: theme.muted, lineHeight: 1.5,
          padding: "8px 10px", borderRadius: 4,
          backgroundColor: theme.surface, border: `1px solid ${theme.border}`,
        }}>
          <strong style={{ color: theme.textSoft }}>Not configurable.</strong>{" "}
          {schema.disabled_reason ?? "This node is not available."}
        </div>
      </div>
    );
  }
```

> **Read `theme`** in `frontend/src/styles` to confirm `textSoft`,
> `surface`, `border`, `muted` exist (they are used elsewhere in this
> file). Use existing token names only.

Run: `cd frontend && npx vitest run src/components/__tests__/SchemaDrivenParamsEditor.test.tsx`.

---

## Step 7 — Regenerate OpenAPI types

This is generation, not a TDD cycle. Run after Step 5 is green:

```bash
python3 scripts/generate-openapi-types.py
```

Commit the updated `frontend/src/api/openapi.json` and
`frontend/src/api/schema.d.ts` together with the backend model change.

Verify the new fields appear in `schema.d.ts` under `NodeTypeItem` and
`NodeTypeSchemaResponse`.

Run `make typecheck` to confirm the frontend still compiles against the
new types.

---

## Step 8 — Docs

### `AGENTS.md`

In the "Canonical API error codes" section, add:

```
- `NODE_NOT_AVAILABLE_FOR_LAUNCH` — deferred node instantiated in launch mode
- `OPTIONAL_DEPENDENCY_NOT_INSTALLED` — node's optional dep group missing
- `PLAN_CONTAINS_UNAVAILABLE_NODES` — plan has unavailable nodes; rejected before run
```

### `docs/plans/deferred-node-exposure/` (this directory)

Already documented by `README.md` + this file. No separate ADR required
unless the repo's `docs/adr/` convention mandates one for API-shape
changes — check `docs/adr/` and add an ADR only if a numbered ADR exists
for comparable API-shape decisions (e.g. the error envelope has one).

---

## Final verification checklist

```bash
make lint
make typecheck
make test
python3 -m pytest tests/test_node_registry_availability.py tests/test_optional_dependency_errors.py tests/test_plan_executability.py tests/test_node_types_api.py tests/test_launch_mode.py -q
cd frontend && npx vitest run src/components/__tests__/SchemaDrivenParamsEditor.test.tsx
```

All must pass. Confirm `git status` shows the regenerated
`frontend/src/api/openapi.json` and `schema.d.ts` as modified.

## Common pitfalls

- **`CardreError.__init__` signature**: the error-handling sprint may
  have changed it. Read `cardre/errors.py:21` before writing Step 2.
- **`get_plan_version` return shape**: the steps may be dicts, not
  `StepSpec`. Rehydrate in `validate_plan_executability` exactly as
  `_execute_step` does.
- **`RunService` registry access**: confirm whether `__init__` stores a
  registry. If not, build `NodeRegistry.with_defaults()` locally in
  `run_plan` for the gate — do not change the constructor signature.
- **`store.create_project` signature**: read `project_store.py` before
  writing the test helper; the `store` fixture is pre-initialised.
- **Forgetting the `available_only` query param** in the OpenAPI regen —
  it changes the operation signature, so regen is mandatory after
  Step 5, not optional.
- **Frontend `screen.queryByRole`** — ensure the Save button has an
  accessible name. It currently reads "Saving..." / "Save Params", so
  `name: /save params/i` matches the idle label. The test renders with
  `available:false` so the button is never in the saving state.