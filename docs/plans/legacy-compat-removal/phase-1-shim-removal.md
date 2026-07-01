# Phase 1 — Shim + Legacy-Migration Removal

**Sprint:** `docs/plans/legacy-compat-removal-sprint.md`
**Phase goal:** Delete the three dead/near-dead import shims and the
non-load-bearing read-time node-type migration code. Pure removal; no
behaviour change.

## Authority

ADR 0003 (`docs/adr/0003-no-legacy-plan-accommodation.md`) — no launch, no
persisted plans, backward compatibility is not a constraint. The ADR
explicitly calls `_LEGACY_NODE_TYPE_METHOD` defence-in-depth, not load-bearing.

A pre-sprint audit confirmed:
- `cardre/store_schema.py` — **zero** importers repo-wide.
- `cardre/reporting/readiness.py` — **zero** importers repo-wide.
- `cardre/reporting/limitation_codes.py` — still imported by two files in its
  own package (must be retargeted before deletion).
- `_migrate_step_spec` / `_LEGACY_NODE_TYPE_METHOD` — **zero** tests exercise
  them.

## Files

### Read first (do not edit)
- `cardre/store_schema.py` — confirm it's a 9-line re-export shim.
- `cardre/reporting/readiness.py` — confirm it's a 13-line re-export shim.
- `cardre/reporting/limitation_codes.py` — confirm it's an 8-line re-export.
- `cardre/store/project_store.py:52-55` — `_LEGACY_NODE_TYPE_METHOD`.
- `cardre/store/project_store.py:526-544` — `_migrate_step_spec()`.
- `cardre/store/plan_repo.py:62-87` — `get_version_steps()` wraps each step.
- `docs/adr/0003-no-legacy-plan-accommodation.md:25` — stale path reference.

### Modify
- `cardre/reporting/schema.py:13` — retarget the `LimitationCode` import.
- `cardre/reporting/collector.py:20` — retarget the `LimitationCode` import.
- `cardre/store/project_store.py` — remove `_LEGACY_NODE_TYPE_METHOD` and
  `_migrate_step_spec()`.
- `cardre/store/plan_repo.py` — return `StepSpec(...)` directly in
  `get_version_steps()`.
- `docs/adr/0003-no-legacy-plan-accommodation.md` — fix the stale path.

### Delete
- `cardre/store_schema.py`
- `cardre/reporting/readiness.py`
- `cardre/reporting/limitation_codes.py`

## Steps

### Step 1 — Retarget the two live `LimitationCode` imports

These two files import from the shim. Change them to import from the
canonical location. This must happen **before** deleting the shim.

`cardre/reporting/schema.py:13`:
```python
# before
from cardre.reporting.limitation_codes import LimitationCode  # noqa: F401
# after
from cardre.readiness.limitation_codes import LimitationCode  # noqa: F401
```

`cardre/reporting/collector.py:20`:
```python
# before
from cardre.reporting.limitation_codes import LimitationCode
# after
from cardre.readiness.limitation_codes import LimitationCode
```

### Step 2 — Delete the three shims

- `rm cardre/store_schema.py`
- `rm cardre/reporting/readiness.py`
- `rm cardre/reporting/limitation_codes.py`

### Step 3 — Remove `_LEGACY_NODE_TYPE_METHOD`

In `cardre/store/project_store.py`, delete lines 52-55:
```python
_LEGACY_NODE_TYPE_METHOD: dict[str, tuple[str, str]] = {
    "cardre.fine_classing": ("cardre.binning", "fine_classing"),
    "cardre.auto_binning_fit": ("cardre.binning", "optbinning"),
}
```

### Step 4 — Remove `ProjectStore._migrate_step_spec()`

In `cardre/store/project_store.py`, delete the `_migrate_step_spec` static
method (lines 526-544). It is the only caller of `_LEGACY_NODE_TYPE_METHOD`.

Also remove the public delegator at `project_store.py:522-523` if it does
nothing but forward to `self.plans.get_version_steps(...)` — **read the
context first**. If `ProjectStore.get_plan_version_steps` adds any behaviour
(hash computation, caching, validation), preserve that behaviour and only
drop the `_migrate_step_spec` wrapping. When in doubt, keep the delegator and
just ensure it no longer calls `_migrate_step_spec`.

### Step 5 — Make `PlanRepository.get_version_steps()` return `StepSpec` directly

In `cardre/store/plan_repo.py:62-87`, the list comprehension currently wraps
each row in `self._store._migrate_step_spec(StepSpec(...))`. Remove the
wrapper so it returns `StepSpec(...)` directly:

```python
# before (line 73)
return [
    self._store._migrate_step_spec(StepSpec(
        step_id=r["step_id"],
        node_type=r["node_type"],
        ...
    ))
    for r in rows
]
# after
return [
    StepSpec(
        step_id=r["step_id"],
        node_type=r["node_type"],
        ...
    )
    for r in rows
]
```

**Critical:** preserve the exact `StepSpec` construction including
`params_hash=json_logical_hash(new_params)` (or whatever the current
non-legacy branch computes) — do not drop any field or hash computation.
Read the full `_migrate_step_spec` body first to copy its non-legacy
construction verbatim; the only thing being removed is the legacy-type
rewrite branch (`mapping = _LEGACY_NODE_TYPE_METHOD.get(...)`).

### Step 6 — Fix the stale ADR path reference

In `docs/adr/0003-no-legacy-plan-accommodation.md` around line 25, the ADR
references `cardre/store.py:32-35`. Update it to the current location:
`cardre/store/project_store.py`. Since `_LEGACY_NODE_TYPE_METHOD` is being
deleted in this phase, update the reference to reflect that the map no longer
exists — e.g. note that the legacy node-type map was removed by this sprint,
and point readers to the canonical node-type registry in `cardre/registry.py`.

## Verification commands

```bash
. .venv/bin/activate

# Confirm no references to the deleted symbols remain.
rg -n "store_schema|reporting\.readiness|reporting\.limitation_codes|_migrate_step_spec|_LEGACY_NODE_TYPE_METHOD" \
   cardre/ sidecar/ tests/ docs/

# Lint + preflight.
ruff check --fix
make preflight
```

`rg` must return zero matches in `cardre/`, `sidecar/`, and `tests/`. Docs
may still reference the historical names narratively — that's acceptable
provided the ADR reference is corrected per Step 6.

## Definition of done for this phase

- [ ] `cardre/store_schema.py`, `cardre/reporting/readiness.py`,
      `cardre/reporting/limitation_codes.py` are deleted.
- [ ] `cardre/reporting/schema.py` and `cardre/reporting/collector.py` import
      `LimitationCode` from `cardre.readiness.limitation_codes`.
- [ ] `_LEGACY_NODE_TYPE_METHOD` is gone from `cardre/store/project_store.py`.
- [ ] `ProjectStore._migrate_step_spec()` is gone.
- [ ] `PlanRepository.get_version_steps()` returns `StepSpec(...)` directly.
- [ ] `StepSpec` construction preserves `params_hash` / all fields exactly.
- [ ] ADR 0003 path reference corrected.
- [ ] `rg` for the deleted symbols returns no matches in `cardre/`/`sidecar/`/`tests/`.
- [ ] `ruff check` clean.
- [ ] `make preflight` green.
- [ ] PR raised via `scripts/pr-gate.sh`; CI green.

## Failure mode

- **`ImportError: No module named 'cardre.reporting.limitation_codes'`** after
  deletion: you deleted the shim before retargeting the two importers
  (Step 1). Restore the shim, apply Step 1, then delete.
- **`tests/test_reporting.py` import error**: the shim's two consumers were
  not both retargeted. Re-run `rg "reporting.limitation_codes"` and fix any
  remaining importer.
- **A non-legacy step's `params_hash` changes value**: you dropped the hash
  computation when unwrapping `_migrate_step_spec`. Re-read the original
  method's non-legacy branch and copy the `StepSpec(..., params_hash=...)`
  construction verbatim.
- **`get_plan_version_steps` delegator lost behaviour**: if
  `ProjectStore.get_plan_version_steps` did more than forward, restore the
  extra behaviour and only drop the `_migrate_step_spec` call.