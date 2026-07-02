# v2 Acceptance Completion — Refactor Plan

A focused round of refactoring to close the gaps between PR 196 (current
`v2` head `3b472b2`) and the original v2 refactor plan
(`docs/plans/v2/cardre-v2-refactor-plan.md`). Scope: turn the v2 skeleton
into the finished merge-gate the original plan promised.

This plan is written for a smaller LLM executor. Each batch is
self-contained, TDD-ordered (red → green → refactor), and lists exact files,
symbols, and acceptance commands. Batches A, B, and C can run in parallel;
D depends on C; E depends on A+B+C+D.

## Goals (from the alternative-view reconciliation)

1. Real scorecard launch acceptance test driven through the project-scoped
   API (not `PlanExecutor` directly).
2. `POST /projects` creates a fresh `.cardre` store from a path in the
   request (enables #1).
3. `runs` table stores request fields as real columns; `execute_created_run`
   loads them from columns, not `metadata_json`.
4. Reports + audit bundle export proven from the same evidence rows.
5. Decision logs written retroactively for phases 1–8; principle 12 made
   honest.
6. `affected_downstream_step_ids_json` documented as UI-hint-only or
   promoted to a table; no quiet queryable-JSON exception.

## Non-goals

- Do not add new node types. All 13 launch nodes are already registered
  (`cardre/nodes/registry.py:172-228`). This round wires the acceptance
   test through them; it does not build them.
- Do not touch deferred nodes, fairness, XGBoost, champion/challenger.
- Do not rewrite the evidence schema. The two-level model is correct and
   landed.
- Do not delete the small `test_launch_pathway.py` smoke test. It stays as
   a fast executor-level check; the new API-level test is additive.

## Conventions for every batch

- **TDD order.** Write the failing test first, run it, watch it fail for
   the right reason, then implement, then watch it pass. Do not implement
   then test.
- **Pre-push gate per batch.** Before declaring a batch done, run:
   ```
   . .venv/bin/activate
   ruff check --fix
   make preflight
   ```
   `make preflight` includes governance-mode pytest (`CARDRE_GOVERNANCE=1`)
   and `frontend` build/typecheck. Do not skip it.
- **No comments in code** unless an existing comment is being fixed.
- **No new hand-written types** on the frontend. Generate, or extend the
   OpenAPI surface, then regenerate `frontend/src/api/schema.d.ts` via
   `python3 scripts/generate-openapi-types.py` and commit the diff.
- **One commit per red→green cycle** when feasible; never bundle unrelated
   batches into one commit.
- **Decision logs** — see Batch E. Every batch should record what it
   decided in `docs/plans/v2/decision-logs/phase-N.md` (retroactively for
   1–6; newly for the batches that cover the work here).

## Parallelism map

```
Batch A (runs-table columns)         ─┐
Batch B (POST /projects bootstrap)    ─┤  parallel, no shared files
Batch C (manual-binning review flow) ─┘
Batch D (full scorecard API acceptance test)  ← depends on A + B + C
Batch E (decision logs + doc cleanup) ← depends on A+B+C+D, mostly docs
```

A, B, C touch disjoint files (verified below). Run them as three
concurrent `implement` subagents. D runs after A/B/C land. E is doc work,
runs last, safe to do sequentially.

## Disjoint-file check (for parallel safety)

- **A**: `cardre/store/schema.py` (runs table), `cardre/store/run_repo.py`,
  `cardre/services/run_coordinator.py`, `tests/test_run_coordinator.py`,
  `tests/test_store_*.py` (runs).
- **B**: `cardre/api/routes/projects.py`, `cardre/api/dependencies.py`,
  `cardre/api/schemas.py`, `tests/test_api_projects.py`.
- **C**: `cardre/services/plan_mutation_service.py`,
  `cardre/api/routes/manual_binning.py`, `cardre/store/manual_binning_repo.py`,
  `tests/test_plan_mutation_service.py`, `tests/test_api_manual_binning.py`.

No overlap. D reads from all three; E writes only to `docs/`.

---

## Batch A — `runs` table: real request columns

**Why.** The original plan (Phase 3 DoD) requires `execute_created_run(run_id)`
to recover `run_scope`, `branch_id`, `target_step_id`, `force`,
`requested_by`, `request_id`, `created_at`, `queued_at`, `started_at` from
the `runs` row, not from `metadata_json`. Current state
(`schema.py:77-88`) has `run_id, plan_version_id, status, started_at,
finished_at, branch_id, target_step_id, force, heartbeat_at, metadata_json`.
`run_scope`, `requested_by`, `request_id`, `queued_at`, `created_at` are
absent; `execute_created_run` (`run_coordinator.py:183-191`) reads
`run_scope` and `requested_by` out of `metadata_json`. The recovery test
(`test_run_coordinator.py:157-194`) asserts recovery *works* but doesn't
assert the source is a real column — that's the gap.

### A1 — Red: assert columns exist

Add `tests/test_store_runs_request_columns.py`:

```python
def test_runs_table_has_request_columns(store):
    cols = {r[1] for r in store.execute("PRAGMA table_info(runs)").fetchall()}
    required = {
        "run_id", "plan_version_id", "status",
        "run_scope", "branch_id", "target_step_id", "force",
        "requested_by", "request_id",
        "created_at", "queued_at", "started_at", "finished_at",
        "heartbeat_at",
    }
    missing = required - cols
    assert not missing, f"runs table missing columns: {sorted(missing)}"
```

Run: `pytest tests/test_store_runs_request_columns.py -q`. Fails (missing
`run_scope`, `requested_by`, `request_id`, `queued_at`, `created_at`).

### A2 — Green: add columns to schema

Edit `cardre/store/schema.py` `runs` table:

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    run_scope TEXT NOT NULL DEFAULT 'full_plan',
    branch_id TEXT,
    target_step_id TEXT,
    force INTEGER NOT NULL DEFAULT 0,
    requested_by TEXT,
    request_id TEXT,
    created_at TEXT NOT NULL,
    queued_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

`STORE_SCHEMA_VERSION` stays `100` (no shipped users; the v2 branch is
pre-merge). All existing tests that `INSERT INTO runs (...)` must be
updated to include `created_at` (NOT NULL, no default). Grep:

```
grep -rn "INSERT INTO runs" tests/ cardre/
```

Add `created_at` to every such insert. For tests that build the row via
`RunRepository.create`, no change needed once A3 is done.

Run the column-existence test → green.

### A3 — Red: `RunRepository.create` writes the new columns

Add to `tests/test_run_coordinator.py` (or a new
`tests/test_run_repo_request_fields.py`):

```python
def test_create_run_persists_request_fields(store):
    from cardre.store.run_repo import RunRepository
    repo = RunRepository(store)
    # need a committed plan_version; reuse store_with_evidence fixture shape
    pv_id = ...  # reuse a helper that creates a committed plan_version
    run_id = repo.create(
        pv_id,
        run_scope="branch",
        branch_id="br-1",
        requested_by="alice",
        request_id="req-1",
    )
    row = repo.get(run_id)
    assert row["run_scope"] == "branch"
    assert row["branch_id"] == "br-1"
    assert row["requested_by"] == "alice"
    assert row["request_id"] == "req-1"
    assert row["created_at"]
    assert row["queued_at"] is None  # set on dispatch
```

Fails: `RunRepository.create` signature is `(plan_version_id, branch_id)`.
Extend it.

### A4 — Green: extend `RunRepository.create`

`cardre/store/run_repo.py`:

```python
def create(
    self,
    plan_version_id: str,
    run_scope: str = "full_plan",
    branch_id: str | None = None,
    target_step_id: str | None = None,
    force: bool = False,
    requested_by: str | None = None,
    request_id: str | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    now = utc_now_iso()
    self._store.execute(
        """INSERT INTO runs
           (run_id, plan_version_id, status, run_scope, branch_id,
            target_step_id, force, requested_by, request_id,
            created_at, started_at, heartbeat_at)
           VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, plan_version_id, run_scope, branch_id, target_step_id,
         int(force), requested_by, request_id, now, now, now),
    )
    return run_id
```

Drop the `_run_columns()` introspection dance for the new columns — they
are now guaranteed. Keep `heartbeat_at` set to `now` (existing behaviour).

Update every caller of `RunRepository.create` to pass the new kwargs.
Grep: `grep -rn "RunRepository(.*\.create\|run_repo.create\|repo.create(" cardre/ tests/`.
Most call sites pass only `plan_version_id`; the new defaults preserve
them. `RunCoordinator.run` must pass `run_scope`, `branch_id`,
`target_step_id`, `force`, `requested_by`, `request_id` through.

### A5 — Red: `execute_created_run` reads from columns, not metadata

Add to `tests/test_run_coordinator.py`:

```python
def test_execute_created_run_reads_columns_not_metadata(store, monkeypatch):
    # Build a run with run_scope='branch', requested_by='bob' in real columns,
    # and *misleading* values in metadata_json to prove metadata is ignored.
    run_id = _create_run(store, run_scope="branch", requested_by="bob",
                        metadata={"run_scope": "full_plan", "requested_by": "evil"})
    coordinator = RunCoordinator(store, config=...)  # governance on for branch
    summary = coordinator.execute_created_run(run_id)
    # Assert the coordinator used the column values, not the metadata decoys.
    assert summary.run_scope == "branch"
    # And the executed run reflects branch scope (use a spy or inspect side-effects)
```

Fails: current `execute_created_run` reads `metadata.get("run_scope", ...)`
first.

### A6 — Green: rewrite recovery to read columns

`cardre/services/run_coordinator.py` `execute_created_run`:

```python
def execute_created_run(self, run_id: str) -> RunSummary:
    from cardre.store.run_repo import RunRepository
    run = RunRepository(self._store).get(run_id)
    if run is None:
        raise CardreError(f"Run {run_id} not found", code="RUN_NOT_FOUND", ...)
    if run["status"] != "running":
        raise CardreError(f"Run {run_id} is not running.", code="RUN_NOT_RUNNING", ...)
    return self._execute_existing_running_run(
        run_id=run["run_id"],
        plan_version_id=run["plan_version_id"],
        run_scope=run["run_scope"],
        branch_id=run["branch_id"],
        target_step_id=run["target_step_id"],
        force=bool(run["force"]),
    )
```

`metadata_json` is now execution metadata only (active_step_id, runtime
warnings, diagnostic payload) — never a source for request fields. Add a
module docstring note to that effect; remove the
`# Recover request fields from metadata_json` comment block.

`requested_by` and `request_id` are persisted for audit/recovery identity
but not needed by `_execute_existing_running_run` (they don't change
execution). Leave them readable on the row; don't pass them down.

### A7 — Refactor: update existing tests that asserted metadata recovery

`tests/test_run_coordinator.py` has tests at lines 157–194 that read
`metadata_json` to verify `requested_by`/`run_scope` persisted. Rewrite
those assertions to read the columns. The test at line 199 that injects
`run_scope` via `metadata_json` INSERT must now inject via the real
column (or the test is testing legacy behaviour and should be deleted —
prefer the former).

### A8 — Batch A verification

```
ruff check --fix cardre/store/schema.py cardre/store/run_repo.py cardre/services/run_coordinator.py
pytest tests/test_store_runs_request_columns.py tests/test_run_coordinator.py tests/test_run_repo_request_fields.py -q
```

Then full `make preflight`. Expect governance-mode pytest to stay green.

---

## Batch B — `POST /projects` creates a fresh `.cardre` store

**Why.** Current `POST /projects` (`projects.py:58-73`) calls
`ProjectRepository.create(name)` *inside an already-open store* resolved
from `X-Project-Path`. `ProjectStore.initialize()` (`db.py:37-65`) does the
right thing (mkdir, schema, `store_meta`) but is never called from the
API. The original plan's acceptance seam requires creating a project to be
a first-class fresh-store bootstrap, not "insert a row into a store the
test harness already opened."

### B1 — Red: API creates a fresh store from a path in the body

Add `tests/test_api_projects.py`:

```python
def test_create_project_bootstraps_fresh_store(api_client, tmp_path):
    project_dir = tmp_path / "new-project.cardre"
    resp = api_client.post(
        "/projects",
        json={"name": "My Project", "path": str(project_dir)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "My Project"
    assert body["project_id"]
    # The store was actually created on disk with v2 schema.
    assert (project_dir / "cardre.sqlite").exists()
    assert (project_dir / "datasets").is_dir()
    # store_meta says v2.
    from cardre.store.db import ProjectStore
    s = ProjectStore(project_dir)
    s.open()
    family = s.execute("SELECT value FROM store_meta WHERE key='schema_family'").fetchone()
    assert family["value"] == "cardre-v2"
    s.close()
```

Fails: current `POST /projects` requires `X-Project-Path` header (already-
open store) and has no `path` field in the body.

### B2 — Green: extend the schema and the route

`cardre/api/schemas.py` — add/extend:

```python
class ProjectCreateRequest(BaseModel):
    name: str
    path: str  # NEW: filesystem path where the .cardre dir will be created
```

`cardre/api/routes/projects.py`:

```python
@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreateRequest):
    """Create a new project by bootstrapping a fresh v2 store at body.path."""
    from cardre.store.db import ProjectStore
    root = Path(body.path)
    store = ProjectStore(root)
    store.initialize()           # hard-errors if sqlite already exists
    try:
        repo = ProjectRepository(store)
        project_id = repo.create(name=body.name)
        project = repo.get(project_id)
        assert project is not None
        return ProjectResponse(
            project_id=project["project_id"],
            name=project["name"],
            created_at=project["created_at"],
            cardre_version=project.get("cardre_version", "0.2.0"),
        )
    finally:
        store.close()
```

Note: `create_project` no longer takes `store: ProjectStore = Depends(get_project_store)`.
The dependency is for *opening existing* stores; creation bootstraps its
own. Keep `get_project_store` for the GET routes.

Regenerate frontend types:
```
python3 scripts/generate-openapi-types.py
git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/schema.d.ts
```
Commit the regenerated diff.

### B3 — Red: error cases

Add to `tests/test_api_projects.py`:

```python
def test_create_project_rejects_existing_store(api_client, tmp_path):
    p = tmp_path / "exists.cardre"
    ProjectStore(p).initialize()
    resp = api_client.post("/projects", json={"name": "X", "path": str(p)})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "STORE_VERSION_INCOMPATIBLE"  # or a new STORE_ALREADY_EXISTS

def test_create_project_rejects_non_cardre_path(api_client, tmp_path):
    # path must end in .cardre? Decide and enforce. Prefer: allow any path,
    # but document. If enforcing, add a 400 here.
    ...
```

### B4 — Green: handle `SchemaVersionError` from `initialize()`

`initialize()` already raises `SchemaVersionError` if the sqlite file
exists. Map it to a 409 in the route:

```python
from cardre.domain.errors import SchemaVersionError

try:
    store.initialize()
except SchemaVersionError as e:
    raise CardreApiError(
        code="STORE_ALREADY_EXISTS",
        message=str(e),
        status_code=409,
    )
```

Add `STORE_ALREADY_EXISTS` to the canonical error code set
(`cardre/api/errors.py` and `frontend/src/api/errorCodes.ts` — see
Batch E note about errorCodes generation; for now add it consistently to
both and regenerate OpenAPI).

### B5 — Red: GET /projects still works via X-Project-Path

Add (or confirm) a test that `GET /projects/{id}` with `X-Project-Path`
pointing at a store created by `POST /projects` returns the project.
This is the backwards-compat check that the dependency path is unchanged.

### B6 — Batch B verification

```
ruff check --fix cardre/api/routes/projects.py cardre/api/schemas.py cardre/api/errors.py
pytest tests/test_api_projects.py -q
python3 scripts/generate-openapi-types.py
git diff --exit-code -- frontend/src/api/
make preflight
```

---

## Batch C — Manual-binning review flow proven end-to-end

**Why.** The mutation service creates a draft plan version + review row in
one transaction (good), but the end-to-end flow — create review, list
affected downstream, commit the draft, see stale evidence on downstream
steps via `StalenessService` — is not proven by a single test. The
`affected_downstream_step_ids_json` column is a UI hint per the plan's
Phase 2 note, but nothing currently documents that boundary or prevents
it becoming a queryable relationship. Close the loop with one integration
test and one doc comment.

### C1 — Red: full review lifecycle via API

Add `tests/test_api_manual_binning.py`:

```python
def test_manual_binning_review_lifecycle(api_client, tmp_path):
    # 1. Bootstrap a store with a committed plan that has fine-classing →
    #    manual-binning → apply-woe (reuse store_with_evidence shape from
    #    conftest, but drive it through POST /projects once Batch B lands).
    # 2. Run the plan once → evidence exists for apply-woe.
    # 3. POST .../manual-binning/reviews with an edit command that changes
    #    the manual-binning step's params (new bin overrides).
    # 4. Assert: a new draft plan_version exists, is_committed=0.
    # 5. Assert: a manual_binning_reviews row exists pointing at the draft.
    # 6. Assert: affected_downstream_step_ids on the review row includes
    #    "apply-woe".
    # 7. GET .../steps/apply-woe/evidence (staleness) on the *draft* version
    #    → status == "missing" or "stale" (no run has executed the draft).
    # 8. PATCH the review to status="approved".
    # 9. POST .../plan-versions/{draft_id}/commit → is_committed=1.
    # 10. Re-run staleness on the now-committed version → still "missing"
    #     (no run yet) — proves staleness is computed from evidence, not
    #     written onto rows.
```

Fails: steps 6–10 likely have no API coverage today. Walk the failures one
at a time.

### C2 — Green: fill route gaps

Likely gaps (verify by running C1 and reading the failures):
- `PATCH .../manual-binning/reviews/{review_id}` for status transitions —
  may need adding to `cardre/api/routes/manual_binning.py`.
- `GET .../plan-versions/{pv_id}` staleness-by-step route may need wiring
  to `StalenessService.explain_step` in `cardre/api/routes/evidence.py`.
- `POST .../plan-versions/{pv_id}/commit` — confirm it exists in
  `cardre/api/routes/plans.py`; if not, add it.

Each gap gets its own red→green micro-cycle inside this batch. Do not
implement features the test doesn't drive.

### C3 — Red: assert historical evidence rows are not mutated

Add to `tests/test_plan_mutation_service.py`:

```python
def test_apply_manual_binning_edit_does_not_mutate_historical_evidence(
    store_with_evidence,
):
    store, project_id, plan_id, base_pv_id, mb_step_id = store_with_evidence
    # Snapshot evidence_edges for the base plan version.
    before = store.execute(
        "SELECT * FROM evidence_edges WHERE plan_version_id = ?",
        (base_pv_id,),
    ).fetchall()
    # Apply an edit.
    PlanMutationService(store).apply_manual_binning_edit(...)
    after = store.execute(
        "SELECT * FROM evidence_edges WHERE plan_version_id = ?",
        (base_pv_id,),
    ).fetchall()
    assert before == after  # historical rows untouched
```

This is the Phase 2 abort criterion made executable.

### C4 — Green: confirm or fix

If it passes already, leave it as a regression guard. If it fails, the
mutation service is mutating historical rows — stop and fix the service
before continuing.

### C5 — Document the `affected_downstream_step_ids_json` boundary

In `cardre/store/manual_binning_repo.py`, add a module-level docstring
note (this is a doc fix, not a comment in code — put it in the docstring):

> `affected_downstream_step_ids_json` is a non-authoritative UI hint.
> The authoritative answer for "which downstream steps are affected" is
> `StalenessService.explain_step` against the draft plan version. Do not
> add SQL filters or joins on this column; treat it as opaque display
> payload. If it ever needs to be queried, promote it to a
> `manual_binning_affected_steps` table first.

This makes the plan's Phase 2 "UI hint, not evidence truth" caveat
machine-discoverable for the next reader.

### C6 — Batch C verification

```
ruff check --fix cardre/api/routes/manual_binning.py cardre/api/routes/evidence.py cardre/services/plan_mutation_service.py
pytest tests/test_api_manual_binning.py tests/test_plan_mutation_service.py tests/test_manual_binning_preview.py -q
make preflight
```

---

## Batch D — Full scorecard launch acceptance test through the API

**Depends on A + B + C merged.** This is the headline deliverable: the
acceptance test the original plan's Phase 5 DoD + abort criterion demanded,
driven through the project-scoped API rather than `PlanExecutor` directly.

### D1 — Red: write the full pathway test

Add `tests/test_api_scorecard_launch_pathway.py`. This is the single most
important file in this round. It must:

1. `POST /projects` with a fresh path (Batch B).
2. `POST .../plans` + `POST .../plan-versions` (committed) with the full
   13-node scorecard graph:
   ```
   import-data → profile → validate-target → split-train-test-oot →
   fine-classing → calculate-woe-iv → variable-selection →
   manual-binning → woe-transform-train → logistic-regression →
   score-scaling → validation-metrics → cutoff-analysis →
   technical-manifest-export
   ```
   Use the node_type strings from `cardre/nodes/registry.py:203-228`.
   Use a tiny CSV (the German-credit stub already used by
   `test_launch_pathway.py` is fine, or generate a 50-row synthetic
   binary-classification CSV inline).
3. `POST .../runs` `{plan_version_id, sync: true, force: true}`.
4. Poll/GET until status == "succeeded".
5. Assert, via the API only:
   - `GET .../runs/{run_id}/steps` → 14 steps, all "succeeded".
   - `GET .../runs/{run_id}/evidence` → ≥ 13 evidence_edges (one per non-
     root step), each with `is_stale == 0`.
   - `GET .../steps/{step_id}/evidence` for `woe-transform-train` →
     staleness explanation `status == "fresh"` (just ran).
   - `GET .../runs/{run_id}/reports` → a model-development report exists.
   - `GET .../projects/{project_id}/exports` → an audit bundle artifact
     exists and references evidence rows from this run.
6. Open the store directly *only* for a final integrity assertion: every
   non-root run step has at least one `evidence_edges` row, and every
   `evidence_edge` has at least one `evidence_artifacts` row. This is the
   Phase 5 abort criterion made executable.

Run it. Expect multiple failures (route gaps, node param mismatches,
report/export not wired). This is the discovery phase — do not fix yet.

### D2 — Green: fix failures one at a time

Likely fixes (confirm against actual failures):
- Node param schemas: some launch nodes may require params the test
  doesn't supply. Read each node's `params_schema` (in
  `cardre/nodes/build/` and `cardre/nodes/validate/`) and supply real
  defaults. Prefer the smallest valid params; this test is about wiring,
  not model quality.
- `GET .../runs/{run_id}/reports` and `GET .../projects/{id}/exports` —
  if these routes don't return the expected shape, wire them to
  `ReportService` / `ExportService`. These services exist
  (`cardre/services/report_service.py`, `export_service.py`); the gap is
  route→service wiring, not service logic.
- Staleness route for a *just-succeeded* run must return "fresh", not
  "stale". If it returns stale, `StalenessService` is misreading
  `evidence_edges.is_stale` — confirm it computes from params hash + plan
  version match, not from a stored flag.

Each fix is its own red→green commit. Keep commits small.

### D3 — Refactor: extract a pathway builder helper

Once green, if the test file is long, extract a
`_build_scorecard_plan_version(api_client, project_id, csv_path)` helper
into `tests/_scorecard_pathway.py` so future tests (e.g. a future
champion/challenger acceptance test) can reuse it. This is optional and
only if the test file exceeds ~400 lines.

### D4 — Batch D verification

```
ruff check --fix tests/test_api_scorecard_launch_pathway.py
pytest tests/test_api_scorecard_launch_pathway.py -q
make preflight
```

The full `make preflight` is the merge gate. If it's green after D, the v2
branch is, by the original plan's definition, ready to merge to main.

---

## Batch E — Decision logs + documentation honesty

**Depends on A+B+C+D.** Mostly docs; safe to do last and sequentially.

### E1 — Write retroactive decision logs

For each of phases 1–6, write `docs/plans/v2/decision-logs/phase-N.md`
using `phase-template.md`. Source material: the commit messages on `v2`
(`git log v2 --oneline | grep "phase-N"`) and the diff for those commits.
Each file answers the template's four questions. Keep each ≤ 60 lines —
these are handoff notes, not essays.

For the work done in this round, write `phase-7.md` (project scope
guards + launch restoration — the existing phase-7 commits) and
`phase-8.md` (this round's batches A–D). Phase 8's log records:
- the `runs`-column decision (A),
- the `POST /projects` bootstrap decision (B),
- the manual-binning end-to-end proof (C),
- the full scorecard API acceptance test (D),
- any schema/route changes forced by D.

### E2 — Update `PHASES.md` to reflect reality

Current `PHASES.md` lists 7 phases ending at "merge gate". Add phase 8
(this round) and mark phases 1–6 as done, 7 as done, 8 as done-after-
gate. Or, if cleaner, rewrite `PHASES.md` as a retrospective completion
table pointing at the decision logs. Pick the clearer option; don't
leave it describing a 7-phase plan that actually shipped 8.

### E3 — Update the original plan doc

Add a `## Post-merge corrections` section to
`docs/plans/v2/cardre-v2-refactor-plan.md` recording:
- Phases 7 and 8 were added post-hoc to fix launch execution and the
  acceptance seam.
- Principle 12 (decision logs) was not honored during the original build;
  logs are written retroactively in E1.
- The `runs`-table request columns (A) and `POST /projects` bootstrap
  (B) were Phase 3/4 DoD items that slipped to this round.
- `test_launch_pathway.py` is the executor-level smoke test; the API-
  level acceptance test is `test_api_scorecard_launch_pathway.py` (D).

Do not rewrite history in the plan — append a correction section so the
original text stays auditable.

### E4 — `errorCodes.ts` policy decision

Decide one of:
- **(a)** Generate `frontend/src/api/errorCodes.ts` from the backend
  canonical set (add a script or extend `generate-openapi-types.py`).
- **(b)** Document `errorCodes.ts` as an accepted hand-written second
  source, with a comment in the file and a note in the plan's
  correction section.

Prefer (a) if cheap; fall back to (b) with a clear note. Do not leave it
undecided.

### E5 — Batch E verification

```
python3 scripts/check_doc_references.py
python3 scripts/check-line-counts.py
make preflight  # docs changes shouldn't break it, but confirm
```

---

## Final merge gate (after all batches)

```
. .venv/bin/activate
ruff check --fix
make preflight
scripts/pr-gate.sh --base main
```

`pr-gate.sh` pushes, opens/locates the PR, and polls CI. Do not request
human review until it prints the `CI GREEN` banner. If it goes red,
read `.opencode/pr-gate-logs/<pr-number>/<job>.log`, fix, push, rerun.
Do not run `gh pr ...` directly — the plugin blocks it for a reason.

## Risk register for this round

| Batch | Risk | Signal | Mitigation |
|---|---|---|---|
| A | Adding NOT NULL `created_at` breaks many tests | Many `INSERT INTO runs` tests fail to compile | Grep all inserts first; update in one sub-commit before running tests |
| B | `ProjectCreateRequest.path` breaks frontend callers that don't send it | Frontend typecheck fails | Regenerate `schema.d.ts`, update `api.createProject` call site in `ProjectView.tsx`/`WelcomeScreen.tsx` |
| C | Staleness route returns "fresh" for a draft with no runs (should be "missing") | C1 step 7 fails | `StalenessService.explain_step` must treat "no evidence_edges for this plan_version" as `status="missing"`, not `="fresh"` |
| D | A launch node needs params the test doesn't know | D1 fails on a node param validation error | Read the node's `params_schema`; supply minimal valid params; do not weaken the node |
| D | `evidence_edges` count < 13 (some steps produce no edge) | D1 step 5 fails | Root step (import-data) has no edge; that's correct. Other steps with no parent in the graph also have none. Assert `len(edges) == len(steps) - count_of_root_steps`, not a hard 13 |
| D | Report/export services exist but aren't wired to routes | D1 step 5 reports/exports fail | Wire routes to existing services; do not rewrite services |
| E | Retroactive decision logs are inaccurate (we're guessing commit intent) | Reviewer flags a log as wrong | Keep logs to observable facts (schema shape, files added); avoid claiming intent we can't source |

## What "done" looks like

- `test_api_scorecard_launch_pathway.py` is green and exercises the full
  13-node pathway through the project-scoped API, including reports and
  audit bundle export.
- `POST /projects` creates a real `.cardre` dir; no test needs to
  pre-create a store.
- `execute_created_run(run_id)` reads `run_scope`, `branch_id`,
  `target_step_id`, `force` from `runs` columns; `metadata_json` holds
  only execution metadata.
- `docs/plans/v2/decision-logs/phase-{1..8}.md` all exist.
- `PHASES.md` and the original plan doc have correction sections
  reflecting what actually happened.
- `make preflight` green.
- `scripts/pr-gate.sh --base main` green.