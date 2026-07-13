# PR9 Implementation Guide — For the Implementer LLM

This guide is a drop-in prompt for an implementer LLM. It provides
exact file paths, line numbers, code snippets, and caller lists for
every change. Follow the steps in order — each step depends on the
previous one.

**Do not change API response shapes.** Only the construction site
moves. **Do not create
`NodeTypeRegistry`, `ProjectListService`, `ExportService` class, or
`ReportService` class.** **Do not rename `_run_mappings.py`.**

---

## Step 1 — A1: Delete ProjectStore delegate block

### File: `cardre/store/db.py`

Delete lines 268-334 (the comment header `# Convenience delegates...`
and all 16 delegate methods). After deletion, `ProjectStore` has:
`__init__`, `initialize`, `open`, `_ensure_store_meta_table`,
`_check_schema_version`, `_connect`, `close`, `__enter__`, `__exit__`,
`transaction`, `execute`, `artifact_path`, `execute_script`,
`executemany`. ~271 lines.

### Migrate 54 caller sites

Replace `store.get_X(...)` with `XRepository(store).get_X(...)` at each
site. Add the necessary import. The 5 zero-caller delegates are deleted
outright — no migration needed.

**Caller list (file:line — current form → new form):**

#### `store.get_artifact(` — 27 sites
```
cardre/_evidence/reader.py:93
  → ArtifactRepository(self._store).get(artifact_id)
cardre/execution/executor.py:403
  → ArtifactRepository(self._store).get(row["artifact_id"])
cardre/modeling/adapters.py:238,378,476
  → ArtifactRepository(store).get(...)
cardre/nodes/build/export.py:41,112
  → ArtifactRepository(store).get(...)
cardre/nodes/build/freeze.py:47,48,49,50,51
  → ArtifactRepository(store).get(...)
cardre/nodes/ensembles.py:28,41
  → ArtifactRepository(store).get(...)
cardre/nodes/explainability.py:291,393,448
  → ArtifactRepository(store).get(...)
cardre/readiness/step_requirements.py:43,85,154,193,205,217
  → ArtifactRepository(store).get(...)
cardre/reporting/sections/artifacts.py:24
  → ArtifactRepository(ctx.store).get(aid)
cardre/reporting/sections/dataset_roles.py:21
  → ArtifactRepository(ctx.store).get(row["artifact_id"])
cardre/reporting/sections/exports.py:25
  → ArtifactRepository(ctx.store).get(row["artifact_id"])
cardre/reporting/sections/manual_interventions.py:73
  → ArtifactRepository(ctx.store).get(aid)
```

#### `store.get_branch(` — 3 sites
```
cardre/branch_step_resolver.py:46
  → BranchRepository(store).get_branch(branch_id)
cardre/readiness/check.py:42
  → BranchRepository(store).get_branch(target_branch_id)
cardre/reporting/collector.py:107
  → BranchRepository(self.store).get_branch(self.target_branch_id)
```

#### `store.get_run(` — 2 sites
```
cardre/readiness/check.py:56
  → RunRepository(store).get(run_id)
cardre/reporting/collector.py:94
  → RunRepository(self.store).get(self.run_id)
```

#### `store.get_project(` — 2 sites
```
cardre/nodes/build/export.py:81
  → ProjectRepository(store).get(plan["project_id"])
cardre/reporting/collector.py:93
  → ProjectRepository(self.store).get(self.project_id)
```

#### `store.get_plan(` — 2 sites
```
cardre/nodes/build/export.py:79
  → PlanRepository(store).get_plan(plan_id)
cardre/nodes/build/features.py:347
  → PlanRepository(store).get_plan(plan_id)
```

#### `store.get_plan_version(` — 1 site
```
cardre/nodes/build/export.py:73
  → PlanRepository(store).get_version(plan_version_id)
```

#### `store.get_run_steps(` — 2 sites
```
cardre/nodes/build/export.py:83
  → RunStepRepository(store).get_for_run(run_id)
cardre/reporting/sections/reproducibility.py:18
  → RunStepRepository(ctx.store).get_for_run(ctx.run["run_id"])
```

#### `store.get_branch_step_map(` — 9 sites
```
cardre/branch_step_resolver.py:44,48
  → BranchRepository(store).get_step_map(branch_id, plan_version_id)
cardre/readiness/check.py:80,82
  → BranchRepository(store).get_step_map(...)
cardre/reporting/collector.py:116,118
  → BranchRepository(self.store).get_step_map(...)
cardre/reporting/sections/manual_interventions.py:29
  → BranchRepository(ctx.store).get_step_map(...)
cardre/reporting/sections/model.py:98
  → BranchRepository(ctx.store).get_step_map(...)
cardre/reporting/sections/redundancy.py:24
  → BranchRepository(ctx.store).get_step_map(...)
```

#### `store.get_plan_version_steps(` — 3 sites
```
cardre/readiness/step_requirements.py:275
  → PlanRepository(store).get_version_steps(plan_version_id)
cardre/reporting/sections/pathway.py:20
  → PlanRepository(ctx.store).get_version_steps(ctx.plan_version_id)
cardre/reporting/sections/manual_interventions.py:37
  → PlanRepository(ctx.store).get_version_steps(ctx.plan_version_id)
```

#### `store.get_plan_id_for_version(` — 5 sites
```
cardre/nodes/build/export.py:77
  → PlanRepository(store).get_plan_id_for_version(plan_version_id)
cardre/nodes/build/features.py:345
  → PlanRepository(store).get_plan_id_for_version(context.plan_version_id)
cardre/readiness/check.py:71
  → PlanRepository(store).get_plan_id_for_version(plan_version_id)
cardre/reporting/sections/champion.py:15
  → PlanRepository(ctx.store).get_plan_id_for_version(ctx.plan_version_id)
cardre/reporting/sections/pathway.py:41
  → PlanRepository(ctx.store).get_plan_id_for_version(ctx.plan_version_id)
```

#### `store.get_champion_assignment(` — 3 sites
```
cardre/readiness/step_requirements.py:237,244
  → ChampionRepository(store).get_champion_assignment(...)
cardre/reporting/sections/champion.py:20
  → ChampionRepository(ctx.store).get_champion_assignment(plan_id)
```

#### Zero-caller delegates (delete outright — no migration):
- `store.get_latest_successful_run_id(` — 0 callers
- `store.get_latest_successful_run_id_for_plan(` — 0 callers
- `store.get_latest_successful_run_step(` — 0 callers
- `store.get_comparison_snapshot(` — 0 callers
- `store.get_champion_assignment_by_branch(` — 0 callers

### Import additions needed at each caller

Add the appropriate import at the top of each file:
```python
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.branch_repo import BranchRepository
from cardre.store.champion_repo import ChampionRepository  # created in Step 2
from cardre.store.plan_repo import PlanRepository
from cardre.store.project_repo import ProjectRepository
from cardre.store.run_repo import RunRepository
from cardre.store.run_step_repo import RunStepRepository
```

### Tests

- `tests/test_store_repos.py` — exercises repos directly, not via
  `ProjectStore` delegates. Unaffected.
- `make preflight` — catches any missed import or `AttributeError`.

---

## Step 2 — A2: Repository base + _branch_filter + ChampionRepository

### 2a — Create `cardre/store/_base.py`

```python
"""Shared repository base class and helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class Repository:
    """Minimal base for store repositories.

    Subclasses set ``table`` and ``pk``. Override ``_row_to_obj``
    where they hydrate typed domain objects. Override ``get``/``list``
    where SQL differs (joins, custom WHERE clauses).
    """

    table: str
    pk: str

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def get(self, id: str) -> dict[str, Any] | None:
        row = self._store.execute(
            f"SELECT * FROM {self.table} WHERE {self.pk} = ?", (id,)
        ).fetchone()
        return None if row is None else self._row_to_obj(row)

    def list(self, *, order_by: str | None = None) -> list[dict[str, Any]]:
        sql = f"SELECT * FROM {self.table}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        rows = self._store.execute(sql).fetchall()
        return [self._row_to_obj(r) for r in rows]

    def _row_to_obj(self, row: dict[str, Any]) -> dict[str, Any]:
        return dict(row)


def _branch_filter(branch_id: str | None) -> tuple[str, list[Any]]:
    """Return SQL fragment and params for ``branch_id IS NULL`` / ``= ?``.

    Usage::

        clause, params = _branch_filter(branch_id)
        sql = f"SELECT ... WHERE ... {clause}"
        cursor.execute(sql, params)
    """
    if branch_id is None:
        return "AND branch_id IS NULL", []
    return "AND branch_id = ?", [branch_id]
```

### 2b — Refactor each `*_repo.py` to inherit from `Repository`

For each repo, add `(Repository)` to the class declaration, remove the
duplicated `__init__`, and set `table`/`pk` class attributes. Keep
custom methods as-is.

**Repos that override `_row_to_obj`** (already hydrate typed objects):
- `ArtifactRepository` — already has `_row_to_artifact_ref`; rename to
  `_row_to_obj` or keep as-is and override `get`/`list` directly.
- `EvidenceRepository` — already has `_row_to_edge`/`_row_to_artifact`;
  these are used in custom query methods, not `get`/`list`. Keep as-is.
- `RunStepRepository` — already has `_row_to_run_step`; same pattern.
- `StepRepository` — already has `_row_to_step_spec`.
- `ManualBinningRepository` — already has `row_to_review`.

**Repos that keep their own `get`/`list`** (custom SQL with joins):
- `BranchRepository` — `get_branch` has custom SQL; `list` has dynamic
  WHERE clauses. Keep both, just remove `__init__`.
- `RunRepository` — `get` has custom SQL; `list_for_plan_version` and
  `list_for_project` have joins. Keep all, just remove `__init__`.
- `PlanRepository` — `get_plan`/`get_version` have custom SQL; `list`
  methods have joins. Keep all, just remove `__init__`.
- `ProjectRepository` — `get` has custom SQL (pops `metadata_json`).
  Keep, just remove `__init__`.
- `ComparisonRepository` — `get_comparison` has custom SQL; `list`
  methods have joins. Keep, just remove `__init__`.

**Example diff for `ProjectRepository`:**
```python
# Before
class ProjectRepository:
    def __init__(self, store: ProjectStore) -> None:
        self._store = store

# After
class ProjectRepository(Repository):
    table = "projects"
    pk = "project_id"
    # __init__ inherited from Repository
```

### 2c — Apply `_branch_filter` at 5 SQL sites

Replace the `if branch_id is None: ... else: ...` pattern with
`_branch_filter(branch_id)`.

**Site 1 — `cardre/store/run_repo.py:179-189` (`get_latest_successful_id`):**
```python
def get_latest_successful_id(self, plan_version_id: str, branch_id: str | None = None) -> str | None:
    clause, params = _branch_filter(branch_id)
    sql = "SELECT run_id FROM runs WHERE plan_version_id = ? AND status = 'succeeded'"
    params = [plan_version_id] + params
    sql += f" {clause} ORDER BY started_at DESC LIMIT 1"
    row = self._store.execute(sql, tuple(params)).fetchone()
    return None if row is None else row["run_id"]
```

**Site 2 — `cardre/store/run_repo.py:191-200` (`get_latest_successful_id_for_plan`):**
This one always uses `branch_id IS NULL` (no branch_id parameter).
Leave as-is — it's not a conditional branch.

**Site 3 — `cardre/store/run_repo.py:202-218` (`get_latest_successful_step_across_plan`):**
```python
def get_latest_successful_step_across_plan(self, plan_id: str, step_id: str, branch_id: str | None = None) -> dict[str, Any] | None:
    clause, params = _branch_filter(branch_id)
    sql = (
        "SELECT rs.* FROM run_steps rs JOIN runs r ON rs.run_id = r.run_id "
        "JOIN plan_versions pv ON rs.plan_version_id = pv.plan_version_id "
        "WHERE pv.plan_id = ? AND rs.step_id = ? AND rs.status = 'succeeded'"
    )
    params = [plan_id, step_id] + params
    sql += f" {clause} ORDER BY rs.started_at DESC LIMIT 1"
    row = self._store.execute(sql, tuple(params)).fetchone()
    if row is None:
        return None
    return dict(row)
```

**Site 4 — `cardre/store/run_step_repo.py:55-79` (`get_latest_successful_step`):**
```python
def get_latest_successful_step(self, plan_version_id: str, step_id: str, branch_id: str | None = None) -> RunStep | None:
    clause, params = _branch_filter(branch_id)
    sql = (
        "SELECT rs.* FROM run_steps rs "
        "JOIN runs r ON rs.run_id = r.run_id "
        "WHERE rs.plan_version_id = ? AND rs.step_id = ? AND rs.status = 'succeeded'"
    )
    params = [plan_version_id, step_id] + params
    sql += f" {clause} ORDER BY rs.started_at DESC LIMIT 1"
    row = self._store.execute(sql, tuple(params)).fetchone()
    if row is None:
        return None
    return self._row_to_run_step(row)
```

**Site 5 — `cardre/store/evidence_repo.py:94-132` (`get_edges_for_plan_step_branch`):**
```python
def get_edges_for_plan_step_branch(self, plan_version_id: str, step_id: str, branch_id: str | None = None) -> list[EvidenceEdge]:
    clause, params = _branch_filter(branch_id)
    sql = (
        "SELECT ee.* FROM evidence_edges ee "
        "JOIN runs r ON ee.run_id = r.run_id "
        "JOIN run_steps rs ON ee.run_step_id = rs.run_step_id "
        "WHERE ee.plan_version_id = ? AND ee.step_id = ? "
        "AND r.status = 'succeeded' AND rs.status = 'succeeded'"
    )
    params = [plan_version_id, step_id] + params
    sql += f" {clause} ORDER BY ee.created_at, ee.evidence_edge_id"
    rows = self._store.execute(sql, tuple(params)).fetchall()
    return [self._row_to_edge(r) for r in rows]
```

### 2d — Create `cardre/store/champion_repo.py`

Move the 3 champion read accessors from `branch_repo.py:143-170`:

```python
"""Champion repository — read-only access to champion_assignments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cardre.domain.diagnostics import JsonDict

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class ChampionRepository:
    """Repository for champion assignment reads."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def get_champion_assignment_for_project(self, project_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM champion_assignments "
            "WHERE project_id = ? AND superseded_at IS NULL "
            "ORDER BY assigned_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_champion_assignment(self, plan_id: str, champion_branch_id: str | None = None) -> JsonDict | None:
        if champion_branch_id:
            row = self._store.execute(
                "SELECT * FROM champion_assignments WHERE plan_id = ? AND champion_branch_id = ? AND superseded_at IS NULL",
                (plan_id, champion_branch_id),
            ).fetchone()
        else:
            row = self._store.execute(
                "SELECT * FROM champion_assignments WHERE plan_id = ? AND superseded_at IS NULL",
                (plan_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def get_champion_assignment_by_branch(self, branch_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM champion_assignments WHERE champion_branch_id = ? AND superseded_at IS NULL",
            (branch_id,),
        ).fetchone()
        return None if row is None else dict(row)
```

Delete the 3 champion methods from `branch_repo.py` (lines 143-170).

**Update callers:**
- `cardre/api/routes/champion.py:10,24,33,35` — change import from
  `BranchRepository` to `ChampionRepository`; change `repo = BranchRepository(store)`
  to `repo = ChampionRepository(store)`.
- `cardre/services/champion_service.py:14,39,187,188` — change import
  from `BranchRepository` to `ChampionRepository`; change
  `branches_repo = BranchRepository(store)` to
  `champion_repo = ChampionRepository(store)`; update method calls.
- `cardre/readiness/step_requirements.py:237,244` — already migrated
  in Step 1 to `ChampionRepository(store).get_champion_assignment(...)`.
- `cardre/reporting/sections/champion.py:20` — already migrated in
  Step 1 to `ChampionRepository(ctx.store).get_champion_assignment(...)`.

### 2e — Delete duplicate `get_comparison` in `branch_repo.py`

Delete `branch_repo.py:172-177` (`def get_comparison`). The canonical
copy is `comparison_repo.py:45-49`. Verify no caller uses
`BranchRepository(...).get_comparison(...)` directly (grep for
`BranchRepository.*get_comparison` — should be 0 after Step 1 deletes
the delegate).

### 2f — Move comparison snapshot accessors to `comparison_repo.py`

Move `get_comparison_snapshot` and `get_comparison_snapshots` from
`branch_repo.py:179-191` to `comparison_repo.py`. Add them after
`get_snapshot_plan_versions` (line 136).

**Update callers:**
- `cardre/services/export_service.py:259` — change
  `branch_repo.get_comparison_snapshot(...)` to
  `ComparisonRepository(store).get_comparison_snapshot(...)`.
- `cardre/services/champion_service.py:83` — change
  `branches_repo.get_comparison_snapshot(...)` to
  `ComparisonRepository(store).get_comparison_snapshot(...)`.

### 2g — Update `cardre/store/__init__.py`

Add `ChampionRepository` to the imports and `__all__`.

### Tests

- `tests/test_store_repos.py` — existing tests should pass unchanged
  (repos return same data).
- Add a test for `_branch_filter(None)` → `("AND branch_id IS NULL", [])`
  and `_branch_filter("x")` → `("AND branch_id = ?", ["x"])`.
- Add a test that `ChampionRepository` returns the same results as the
  old `BranchRepository` accessors (use a fixture with champion data).

---

## Step 2b — A7: active_step_id column + schema migration

### 2b-1 — Update `cardre/store/schema.py`

Bump `V2_STORE_SCHEMA_VERSION` from 100 to 101 and add `active_step_id
TEXT` to the `runs` table DDL (before `metadata_json`):

```python
V2_STORE_SCHEMA_VERSION = 101
```

```sql
CREATE TABLE IF NOT EXISTS runs (
    ...
    heartbeat_at TEXT,
    active_step_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

Update the module docstring to describe version history:
- Version 100: original v2 schema (hard break from v1).
- Version 101: added `active_step_id` column to `runs`.

### 2b-2 — Create `cardre/store/_schema_version.py`

Extract the schema version check and migration runner from `db.py` into
a new module. The `check_and_migrate(conn)` function:

1. Ensures `store_meta` table exists.
2. Validates `schema_family == "cardre-v2"`.
3. Accepts `stored_version <= V2_STORE_SCHEMA_VERSION`.
4. If `stored_version < V2_STORE_SCHEMA_VERSION`, runs `_run_migrations`.
5. Updates `store_meta.schema_version` to current.

The `_run_migrations(conn, from_version)` function has a
`dict[int, list[str]]` mapping version → SQL statements. Migration
100→101: `["ALTER TABLE runs ADD COLUMN active_step_id TEXT"]`.

### 2b-3 — Update `cardre/store/db.py`

Replace the old `_check_schema_version` / `_ensure_store_meta_table` /
`_run_migrations` methods with a call to `_check_and_migrate(conn)`:

```python
from cardre.store._schema_version import check_and_migrate as _check_and_migrate

# In open():
conn = self._connect()
_check_and_migrate(conn)
```

Delete `_ensure_store_meta_table`, `_check_schema_version`, and
`_run_migrations` from `db.py`.

### 2b-4 — Update `cardre/store/run_repo.py`

Replace `get_active_step` and `set_active_step` to use the column
directly instead of the `metadata_json` blob:

```python
def set_active_step(self, run_id: str, step_id: str | None) -> None:
    self._store.execute(
        "UPDATE runs SET active_step_id = ? WHERE run_id = ?",
        (step_id, run_id),
    )

def get_active_step(self, run_id: str) -> str | None:
    row = self._store.execute(
        "SELECT active_step_id FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    return row["active_step_id"]  # type: ignore[no-any-return]
```

Remove the unused `cast` import if no other code uses it.

### 2b-5 — Add migration regression test

In `tests/test_store_repos.py`, add `TestSchemaMigration` class:

```python
class TestSchemaMigration:
    def test_v100_store_migrated_to_v101_adds_active_step_id(self, tmp_path):
        """A store created at schema version 100 is migrated to 101 on open,
        adding the ``active_step_id`` column to the ``runs`` table."""
        # 1. Create a v100 store manually with a runs row
        # 2. Open it with ProjectStore (triggers migration)
        # 3. Verify active_step_id column works (set + get)
```

The test creates a v100 store with `schema_version='100'`, inserts a
`runs` row (without `active_step_id` column), opens it with
`ProjectStore` (which triggers the migration), and verifies
`get_active_step`/`set_active_step` work on the migrated store.

### Tests

- `tests/test_store_repos.py` — existing `test_run_repo_set_active_step`
  passes unchanged (uses the new column).
- New `TestSchemaMigration::test_v100_store_migrated_to_v101` proves
  migration works.

---

## Step 3 — A4: errors.py dedup

### 3a — Delete shadowing constants

In `cardre/api/errors.py`, delete lines 67-101 (35 `NAME = ErrorCode.NAME`
lines). Update `__all__` (lines 164-191) to remove all bare constant
names. Keep `ErrorCode`, `CardreApiError`, `cardre_api_error_handler`,
`cardre_error_handler`, `error_response`.

### 3b — Migrate 14 import sites

Each import changes from bare-constant form to `ErrorCode.X` form:

| File | Current import | New import |
|---|---|---|
| `cardre/services/project_resolver.py:7` | `from cardre.api.errors import PROJECT_NOT_FOUND` | `from cardre.api.errors import ErrorCode` |
| `cardre/services/run_coordinator.py:21` | `from cardre.api.errors import RUN_EXECUTION_FAILED` | `from cardre.api.errors import ErrorCode` |
| `cardre/api/dependencies.py:11-16` | `from cardre.api.errors import (GOVERNANCE_DISABLED, MISSING_PROJECT_ID, PROJECT_NOT_FOUND, RAW_PROJECT_PATH_DISABLED)` | `from cardre.api.errors import ErrorCode` |
| `cardre/api/routes/evidence.py:8-13` | `from cardre.api.errors import (MISSING_PARAMETER, PLAN_VERSION_NOT_FOUND, STEP_NOT_FOUND, CardreApiError)` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/runs.py:8` | `from cardre.api.errors import PLAN_VERSION_NOT_FOUND, RUN_NOT_FOUND, CardreApiError` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/projects.py:15-20` | `from cardre.api.errors import (INVALID_PROJECT_PATH, PROJECT_NOT_FOUND, STORE_ALREADY_EXISTS, CardreApiError)` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/manual_binning.py:10` | `from cardre.api.errors import REVIEW_NOT_FOUND, CardreApiError` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/champion.py:27` | `from cardre.api.errors import PLAN_NOT_FOUND, CardreApiError` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/reports.py:8` | `from cardre.api.errors import RUN_NOT_FOUND, CardreApiError` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/plans.py:14-19` | `from cardre.api.errors import (PLAN_NOT_FOUND, PLAN_VERSION_IMMUTABLE, PLAN_VERSION_NOT_FOUND, CardreApiError)` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/branches.py:8-13` | `from cardre.api.errors import (BRANCH_NOT_FOUND, PLAN_NOT_FOUND, PLAN_VERSION_NOT_FOUND, CardreApiError)` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/artifacts.py:8` | `from cardre.api.errors import ARTIFACT_NOT_FOUND, CardreApiError` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/routes/comparisons.py:42,49` | `from cardre.api.errors import COMPARISON_NOT_FOUND, CardreApiError` | `from cardre.api.errors import ErrorCode, CardreApiError` |
| `cardre/api/app.py:14` | `from cardre.api.errors import CardreApiError, cardre_api_error_handler, cardre_error_handler` | **Unchanged** (no bare constants) |

### 3c — Migrate ~123 bare-constant usages to `ErrorCode.X`

Replace every `code=PLAN_VERSION_NOT_FOUND` with
`code=ErrorCode.PLAN_VERSION_NOT_FOUND`, etc. This is a mechanical
search-and-replace across the files listed above.

**Special case — `dependencies.py`:** The bare constants are used as
dict values, not `code=` kwargs:
- `dependencies.py:45` — `"code": RAW_PROJECT_PATH_DISABLED` →
  `"code": ErrorCode.RAW_PROJECT_PATH_DISABLED`
- `dependencies.py:57` — `"code": PROJECT_NOT_FOUND` →
  `"code": ErrorCode.PROJECT_NOT_FOUND`
- `dependencies.py:72` — `"code": MISSING_PROJECT_ID` →
  `"code": ErrorCode.MISSING_PROJECT_ID`
- `dependencies.py:101` — `"code": GOVERNANCE_DISABLED` →
  `"code": ErrorCode.GOVERNANCE_DISABLED`

**Special case — `champion.py:27`:** The import is inline (inside the
`if plan_id:` block). Change to `from cardre.api.errors import ErrorCode,
CardreApiError` and update the `code=PLAN_NOT_FOUND` usage.

**Special case — `comparisons.py:42,49`:** Two inline imports. Same
pattern.

### 3d — Update `__all__` in `errors.py`

Replace the list of bare constant names with just:
```python
__all__ = [
    "ErrorCode",
    "CardreApiError",
    "cardre_api_error_handler",
    "cardre_error_handler",
    "error_response",
]
```

### Tests

- `tests/test_error_code_sync.py` — imports `ErrorCode` directly
  (line 13). Unaffected. Run to confirm TS↔Python sync still passes.
- `make preflight` — Ruff catches any remaining bare-constant references.

---

## Step 4 — A6: Centralise 3 inline mappers

### 4a — Add 3 mapping functions to `_run_mappings.py`

Add these after `project_to_response` (line 133):

```python
def champion_assignment_to_response(assignment: Mapping[str, Any]) -> ChampionAssignmentResponse:
    return ChampionAssignmentResponse(
        champion_assignment_id=assignment["champion_assignment_id"],
        project_id=assignment["project_id"],
        plan_id=assignment["plan_id"],
        champion_branch_id=assignment["champion_branch_id"],
        selected_plan_version_id=assignment["selected_plan_version_id"],
        assigned_at=assignment.get("assigned_at", ""),
        superseded_at=assignment.get("superseded_at"),
    )


def artifact_to_response(artifact: ArtifactRef) -> ArtifactResponse:
    return ArtifactResponse(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        role=artifact.role,
        path=artifact.path,
        physical_hash=artifact.physical_hash,
        logical_hash=artifact.logical_hash,
        media_type=artifact.media_type,
        created_at=artifact.created_at,
    )


def manual_binning_review_to_response(review: ManualBinningReview) -> ManualBinningReviewResponse:
    return ManualBinningReviewResponse(
        review_id=review.review_id,
        plan_version_id=review.plan_version_id,
        step_id=review.step_id,
        status=review.status,
        reviewer_notes=review.reviewer_notes,
        affected_downstream_step_ids=list(review.affected_downstream_step_ids),
        created_at=review.created_at,
        updated_at=review.updated_at,
    )
```

Add imports for the new response types at the top of `_run_mappings.py`:
```python
from cardre.api.schemas import (
    ...existing imports...,
    ArtifactResponse,
    ChampionAssignmentResponse,
    ManualBinningReviewResponse,
)
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.manual_binning import ManualBinningReview
```

### 4b — Replace inline mapping in `champion.py:40-49`

```python
# Before
return ChampionResponse(
    assignment=ChampionAssignmentResponse(
        champion_assignment_id=assignment["champion_assignment_id"],
        ...
    )
)

# After
from cardre.api.routes._run_mappings import champion_assignment_to_response
return ChampionResponse(
    assignment=champion_assignment_to_response(assignment)
)
```

### 4c — Replace inline mapping in `artifacts.py:31-39`

```python
# Before
return ArtifactResponse(
    artifact_id=artifact.artifact_id,
    ...
)

# After
from cardre.api.routes._run_mappings import artifact_to_response
return artifact_to_response(artifact)
```

### 4d — Replace inline mapping in `manual_binning.py:35-47`

Delete the local `_review_to_response` helper (lines 35-47). Replace
calls with:
```python
from cardre.api.routes._run_mappings import manual_binning_review_to_response
return manual_binning_review_to_response(review)
```

### Tests

- Existing route tests (response shapes unchanged).
- Add a unit test for each new mapper in `tests/test_api_mappers.py`.

---

## Step 5 — A8 + A9: Version hardcode + sidecar argv

### 5a — A8: Delete `cardre_version="0.2.0"` hardcode

**File:** `cardre/api/routes/projects.py:145`

```python
# Before
return project_to_response(project, cardre_version="0.2.0")

# After
return project_to_response(project)
```

`ProjectRepository.create` already writes `__version__` to the row
(`project_repo.py:22`), and `project_to_response` falls back to
`__version__` (`_run_mappings.py:132`). The hardcode is fully redundant.

### 5b — A9: Clean up sidecar argv

**File:** `sidecar/__main__.py`

```python
# Before (31 lines)
def main(argv: list[str] | None = None) -> None:
    args = sys.argv if argv is None else argv
    config = CardreConfig.from_env()
    port = config.api_port
    if len(args) > 1:
        try:
            port = int(args[1])
        except ValueError as exc:
            raise SystemExit(f"Invalid port argument: {args[1]!r}") from exc
    uvicorn.run(
        app,
        host=config.api_host,
        port=port,
        log_level="info",
    )

# After (~8 lines)
def main() -> None:
    config = CardreConfig.from_env()
    uvicorn.run(
        app,
        host=config.api_host,
        port=config.api_port,
        log_level="info",
    )
```

Remove the unused `import sys` at the top.

**Update test:** `tests/test_sidecar_entrypoint.py:25`

```python
# Before
sidecar_main.main(["cardre-api", "18000"])
assert captured["port"] == 18000

# After
sidecar_main.main()
assert captured["port"] == 8752  # the monkeypatched CardreConfig.api_port
```

### Tests

- `tests/test_sidecar_entrypoint.py` — updated as above.
- Existing project-creation tests — verify `create_project` returns
  the correct `cardre_version` (should match `__version__`).

---

## Step 6 — A3 (scoped): Relocate 3 route handlers

### 6a — `list_run_evidence` → `EvidenceRepository.list_for_run_ordered`

**Add to `cardre/store/evidence_repo.py`** (after `get_artifacts_for_run`,
line 170):

```python
def list_for_run_ordered(self, run_id: str) -> list[tuple[EvidenceEdge, list[EvidenceArtifact]]]:
    """Return evidence edges + artifacts ordered by run_step_id.

    Groups artifacts by edge and orders edges by the run's step order.
    """
    from cardre.store.run_step_repo import RunStepRepository

    rs_repo = RunStepRepository(self._store)
    run_step_ids = [rs.run_step_id for rs in rs_repo.get_for_run(run_id)]

    edges = self.get_edges_for_run(run_id)
    artifacts = self.get_artifacts_for_run(run_id)

    artifacts_by_edge_id: dict[str, list[EvidenceArtifact]] = {}
    for artifact in artifacts:
        artifacts_by_edge_id.setdefault(artifact.evidence_edge_id, []).append(artifact)

    edges_by_step: dict[str, list[EvidenceEdge]] = {}
    for edge in edges:
        edges_by_step.setdefault(edge.run_step_id, []).append(edge)

    result: list[tuple[EvidenceEdge, list[EvidenceArtifact]]] = []
    for run_step_id in run_step_ids:
        for edge in edges_by_step.get(run_step_id, []):
            result.append((edge, artifacts_by_edge_id.get(edge.evidence_edge_id, [])))
    return result
```

**Update `cardre/api/routes/runs.py:111-145`:**

```python
@router.get("/runs/{run_id}/evidence", response_model=list[RunEvidenceEdgeResponse])
async def list_run_evidence(
    project_id: str,
    run_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> list[RunEvidenceEdgeResponse]:
    """List all evidence edges for a run."""
    if not run_belongs_to_project(store, project_id, run_id):
        raise CardreApiError(
            code=ErrorCode.RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    evidence_repo = EvidenceRepository(store)
    return [
        evidence_edge_to_response(edge, arts)
        for edge, arts in evidence_repo.list_for_run_ordered(run_id)
    ]
```

Remove unused imports: `RunStepRepository`, `EvidenceArtifact`,
`EvidenceEdge` (if no longer used elsewhere in the file).

### 6b — Shared exports/reports listing helper

**New file: `cardre/services/export_listing.py`**

```python
"""Shared export/report directory listing.

The ``exports/`` directory under a project root contains:
- ``export-{run_id}-{suffix}/`` — export directories
- ``manifest-{run_id}/`` — report directories

This module provides a single function to list them, used by the
exports and reports route handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


@dataclass
class ExportDirInfo:
    """Info about a single export or report directory."""
    name: str
    run_id: str
    path: str
    size_bytes: int = 0


def list_export_dirs(
    store: ProjectStore,
    *,
    prefix: str = "export-",
    run_id: str | None = None,
) -> list[ExportDirInfo]:
    """List export/report directories under ``store.root / exports/``.

    Args:
        store: The project store.
        prefix: Directory name prefix to match (``"export-"`` or ``"manifest-"``).
        run_id: If set, only return directories whose run_id matches.

    Returns:
        Sorted list of ``ExportDirInfo``.
    """
    exports_dir = store.root / "exports"
    if not exports_dir.exists():
        return []

    results: list[ExportDirInfo] = []
    for item in sorted(exports_dir.iterdir()):
        if not item.is_dir() or not item.name.startswith(prefix):
            continue
        parts = item.name.split("-", 2) if prefix == "export-" else item.name.split("-", 1)
        dir_run_id = parts[1] if len(parts) > 1 else ""
        if run_id and dir_run_id != run_id:
            continue
        size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) if prefix == "export-" else 0
        results.append(ExportDirInfo(
            name=item.name,
            run_id=dir_run_id,
            path=str(item),
            size_bytes=size,
        ))
    return results
```

**Update `cardre/api/routes/exports.py:14-41`:**

```python
@router.get("/exports", response_model=ExportListResponse)
async def list_exports(
    project_id: str,
    run_id: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> ExportListResponse:
    """List exports for a project, optionally filtered by run."""
    from cardre.services.export_listing import list_export_dirs

    dirs = list_export_dirs(store, prefix="export-", run_id=run_id)
    return ExportListResponse(exports=[
        ExportResponse(
            export_id=d.name,
            run_id=d.run_id,
            export_type="scoring_code",
            path=d.path,
            created_at="",
            size_bytes=d.size_bytes,
        )
        for d in dirs
    ])
```

**Update `cardre/api/routes/reports.py:16-36` (`list_reports`):**

```python
@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ReportListResponse:
    """List all reports for a project."""
    from cardre.services.export_listing import list_export_dirs

    dirs = list_export_dirs(store, prefix="manifest-")
    return ReportListResponse(reports=[
        ReportResponse(
            report_id=d.name,
            run_id=d.run_id,
            report_type="manifest",
            path=str(Path(d.path) / "manifest.json") if (Path(d.path) / "manifest.json").exists() else d.path,
            created_at="",
        )
        for d in dirs
    ])
```

**Update `cardre/api/routes/reports.py:39-63` (`list_run_reports`):**

```python
@router.get("/runs/{run_id}/reports", response_model=ReportListResponse)
async def list_run_reports(
    project_id: str,
    run_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ReportListResponse:
    """List reports for a specific run."""
    if not run_belongs_to_project(store, project_id, run_id):
        raise CardreApiError(
            code=ErrorCode.RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    from cardre.services.export_listing import list_export_dirs

    dirs = list_export_dirs(store, prefix="manifest-", run_id=run_id)
    return ReportListResponse(reports=[
        ReportResponse(
            report_id=d.name,
            run_id=d.run_id,
            report_type="manifest",
            path=str(Path(d.path) / "manifest.json") if (Path(d.path) / "manifest.json").exists() else d.path,
            created_at="",
        )
        for d in dirs
    ])
```

### 6c — `list_runs` → `RunCoordinator.list_for_project`

**Add to `cardre/services/run_coordinator.py`** (after `get_summary`,
line 549):

```python
def list_for_project(self, project_id: str) -> list[RunSummary]:
    """List all runs for a project as RunSummary objects."""
    from cardre.store.run_repo import RunRepository

    run_repo = RunRepository(self._store)
    runs = run_repo.list_for_project(project_id)
    return [
        RunSummary(
            run_id=r["run_id"],
            plan_version_id=r["plan_version_id"],
            status=r["status"],
            started_at=r["started_at"],
            finished_at=r.get("finished_at"),
            branch_id=r.get("branch_id"),
        )
        for r in runs
    ]
```

**Update `cardre/api/routes/runs.py:32-54`:**

```python
@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> RunListResponse:
    """List all runs for a project."""
    summaries = coordinator.list_for_project(project_id)
    return RunListResponse(
        runs=[run_summary_to_response(s) for s in summaries]
    )
```

Remove unused imports: `RunRepository`, `RunSummary` (if no longer
used elsewhere in the file).

### Tests

- `tests/test_evidence_repo.py` — add `test_list_for_run_ordered`
  (creates a run with steps, edges, artifacts; asserts ordered output).
- `tests/test_run_coordinator.py` — add `test_list_for_project`
  (creates runs via the coordinator; asserts `RunSummary` list).
- `tests/test_export_listing.py` — new file. Test `list_export_dirs`
  with a temp directory structure: `exports/export-run1-foo/`,
  `exports/manifest-run1/`, `exports/other/`. Assert prefix filtering,
  run_id filtering, size summation.
- Existing route tests — response shapes unchanged.

---

## Step 7 — A5 (scoped): Delete `_value` polymorphic helper

### 7a — Delete `_value` in `_run_mappings.py`

Delete lines 32-35 (`def _value`).

### 7b — Update `plan_to_response` and `plan_version_to_response`

**`plan_to_response` (line 72):**
```python
# Before
def plan_to_response(plan: Plan | Mapping[str, Any]) -> PlanResponse:
    return PlanResponse(
        plan_id=_value(plan, "plan_id"),
        project_id=_value(plan, "project_id"),
        name=_value(plan, "name"),
        created_at=_value(plan, "created_at"),
    )

# After
def plan_to_response(plan: Mapping[str, Any]) -> PlanResponse:
    return PlanResponse(
        plan_id=plan["plan_id"],
        project_id=plan["project_id"],
        name=plan["name"],
        created_at=plan["created_at"],
    )
```

**`plan_version_to_response` (line 81):**
```python
# Before
def plan_version_to_response(plan_version: PlanVersion | Mapping[str, Any]) -> PlanVersionResponse:
    return PlanVersionResponse(
        plan_version_id=_value(plan_version, "plan_version_id"),
        plan_id=_value(plan_version, "plan_id"),
        version_number=_value(plan_version, "version_number"),
        is_committed=bool(_value(plan_version, "is_committed", False)),
        created_at=_value(plan_version, "created_at"),
        description=_value(plan_version, "description", ""),
    )

# After
def plan_version_to_response(plan_version: Mapping[str, Any]) -> PlanVersionResponse:
    return PlanVersionResponse(
        plan_version_id=plan_version["plan_version_id"],
        plan_id=plan_version["plan_id"],
        version_number=plan_version["version_number"],
        is_committed=bool(plan_version.get("is_committed", False)),
        created_at=plan_version["created_at"],
        description=plan_version.get("description", ""),
    )
```

### 7c — Update test

**`tests/test_api_mappers.py:17,27,33`** — pass dicts instead of typed
objects:

```python
def test_plan_mappers_return_expected_shapes() -> None:
    plan = Plan(plan_id="plan-1", project_id="proj-1", name="Plan", created_at="now")
    version = PlanVersion(
        plan_version_id="pv-1",
        plan_id="plan-1",
        version_number=2,
        is_committed=True,
        created_at="now",
        description="Base",
    )

    assert plan_to_response(plan.to_dict()).model_dump() == {
        "plan_id": "plan-1",
        "project_id": "proj-1",
        "name": "Plan",
        "created_at": "now",
    }
    assert plan_version_to_response(version.to_dict()).model_dump() == {
        "plan_version_id": "pv-1",
        "plan_id": "plan-1",
        "version_number": 2,
        "is_committed": True,
        "created_at": "now",
        "description": "Base",
    }
```

### 7d — Verify all callers pass dicts

Grep for `plan_to_response(` and `plan_version_to_response(`:
- `cardre/api/routes/plans.py:57,82,96,120,150,191,220` — all pass
  repo results (dicts). Unaffected.
- `cardre/api/routes/projects.py:67,107,145` — all pass repo results
  (dicts). Unaffected.

The only typed-object callers were in the test, now updated.

### Tests

- `tests/test_api_mappers.py` — updated as above.
- `make preflight` — Ruff catches any remaining `_value` references.

---

## Verification checklist

Run after all steps:

```bash
. .venv/bin/activate
ruff check --fix
make preflight
```

**Grep checks:**
```bash
# A1 — no delegate methods in db.py
rg 'def get_branch\b|def get_run\b|def get_artifact\b' cardre/store/db.py
# → 0 matches

# A1 — no store.get_X callers outside db.py
rg 'store\.get_branch\(|store\.get_run\(|store\.get_artifact\(' cardre/ sidecar/
# → 0 matches

# A2 — Repository base exists
rg 'class Repository' cardre/store/_base.py
# → 1 match

# A2 — branch_id IS NULL in store (should be 0 or 1)
rg 'branch_id IS NULL' cardre/store/
# → 0 or 1 (the helper)

# A2 — no get_comparison in branch_repo
rg 'def get_comparison' cardre/store/branch_repo.py
# → 0 matches

# A2 — champion_repo exists
ls cardre/store/champion_repo.py
# → exists

# A4 — no bare constants in errors.py
rg 'GOVERNANCE_DISABLED = ErrorCode' cardre/api/errors.py
# → 0 matches

# A5 — no _value helper
rg 'def _value' cardre/api/routes/_run_mappings.py
# → 0 matches

# A6 — no _review_to_response in manual_binning.py
rg '_review_to_response' cardre/api/routes/manual_binning.py
# → 0 matches

# A8 — no "0.2.0" hardcode
rg '"0.2.0"' cardre/api/routes/projects.py
# → 0 matches

# A9 — no main(argv)
rg 'def main\(argv' sidecar/__main__.py
# → 0 matches

# A3 — no store.root in exports/reports routes
rg 'store\.root' cardre/api/routes/exports.py cardre/api/routes/reports.py
# → 0 matches

# A3 — no RunSummary( in runs.py
rg 'RunSummary\(' cardre/api/routes/runs.py
# → 0 matches
```

**Test suite:**
```bash
pytest tests/ -q
# → green

# Golden report bundle diff
pytest tests/test_golden_report_bundle.py -q
# → green
```
