# 09a — Tidy-Up Sprint Verification Pass

Second-pass review of `09-tidy-up-sprint.md` against the thermonuclear review
report and the **current repository state** (HEAD `4710e8b`,
branch `batch-r1-transaction-uow-ownership`).

Purpose: confirm each finding still describes real code, record the exact code
that must change, and name the tests that must be introduced so a fix is
provable (not merely a passing happy path).

## Method

For every finding I read the file:line the report cites against the working
tree, recorded whether the report's claim still holds, and noted any drift
between the report (written against `a130608..a7bd161`) and the post-R1 repo.
R1 (`4710e8b`) landed *after* the report's HEAD (`a7bd161`), so two findings
are partially or fully closed by R1; the rest are unchanged.

## Verdict per finding

| # | Finding | Report status vs. HEAD `4710e8b` | R-batch |
|---|--------|----------------------------------|---------|
| 1 | Step persistence not transactional/recoverable | **Core fixed by R1**; publication half **still open** | R2 |
| 2 | `sync: false` runs inline | **Still open** — but a fix adapter already exists | R3 |
| 3 | Physical-byte dedup loses semantic identity | **Still open** — root cause is a schema `UNIQUE` constraint, not only the repo query | R4 |
| 4 | Heartbeat/cancellation not fenced | **Still open** | R3 |
| 5 | Concurrent-run guard is TOCTOU | **Still open** — separate UoWs, no unique index | R3 |
| 6 | Query UoWs leak connections | **Closed by R1** — report's file references are now stale | (R1 done) |
| 7 | Output contracts validate only role presence | **Still open** — contract fields already exist, validator ignores them | R4 |
| 8 | Governance owns adapter SQL + giant orchestration | **Still open** | R5 |
| 9 | Terminal DB state / manifest split-brain | **Still open** — and the file's own docstring now contradicts the bug | R2 |

The sprint's finding→batch mapping in `09` is correct. Below is the
per-finding confirmation with the concrete code and the tests to introduce.

---

## Finding 1 — step persistence transactionality & recoverability

### What the report claimed
`SqliteUnitOfWork` only committed when `__enter__()` had set `_begun`;
`ExecuteRun` instantiated the UoW directly (no `with`), so each repository
statement autocommitted and `commit()` was a no-op.

### Current state — core FIXED, publication half OPEN

`cardre/adapters/sqlite/connection.py:39-42` now begins `BEGIN IMMEDIATE`
eagerly in `__init__`; `commit()` raises if there is no open transaction
(`:96-100`); `close()` rolls back any uncommitted work (`:108-112`).
`ExecuteRun` persists each step inside one `persist_uow` that
`commit()`s or `rollback()`s on failure (`execute_run.py:136-229`).
R1's `tests/application/test_uow_ownership.py` proves the atomic rollback at
four injection points.

The **publication half is still open**. `execute_run.py:141` calls
`artifact_store.publish(staged)` *before* any DB write, and
`FsArtifactStore.publish()` (`artifact_store.py:76-80`) does
`staged.staging_path.replace(dest)` — the file leaves staging and lands in
`objects/` before the artifact descriptor row exists. If `register()`,
`run_steps.insert()`, lineage, or evidence then fails, R1's rollback
correctly discards the **DB rows** but leaves an **unreachable object file**
in `objects/`. The report's "no file exists in `objects/` without a durable
descriptor" proof test is therefore not yet satisfied.

### Code to write (R2)
- A staging-finalize protocol: `publish()` returns a *pending* handle; the
  file is moved into `objects/` only after the DB transaction commits, OR an
  outbox/pending-publication row is committed atomically with the descriptor
  and finalized/retried separately.
- `ExecuteRun`'s persist block must hand the file move to the protocol rather
  than calling `publish()` inline before `register()`.

### Tests to introduce (R2)
- Extend `test_uow_ownership.py` (or a new `tests/application/test_publication_durability.py`):
  - Inject failure at `register`, `run_steps.insert`, `register_lineage`,
    `evidence.insert_edge` *after* `publish()` has run. Assert **no file** in
    `objects/` for that physical hash without a durable descriptor /
    pending-publication row.
  - Run through the real SQLite adapter (no fake), mirroring the existing
    `_provision` helper.
- See Finding 9 for the manifest half of the outbox tests.

---

## Finding 2 — `sync: false` runs inline

### What the report claimed
The container constructs a `SyncRunDispatcher` per request; its `dispatch()`
calls `ExecuteRun` in the request thread, so `sync: false` blocks the API
and returns a terminal result instead of a live run.

### Current state — still open, BUT the fix adapter already exists

`container.py:135-139` still builds `SyncRunDispatcher(lambda cmd: exec_run(cmd))`
inside `submit_run_factory`. `sync_dispatcher.py:14-15` still runs
`self._execute_run(...)` inline. `submit_run.py:103-105` only uses inline
`self._execute_run` for `sync=True`, and dispatches for `sync=False`
(`:106-108`) — but the dispatched "async" path is the blocking dispatcher.

**However**, `cardre/adapters/dispatch/thread_dispatcher.py` already
implements a process-owned `ThreadRunDispatcher` (bounded `max_workers`,
duplicate-rejection, `shutdown()`), and `tests/adapters/dispatch/test_thread_dispatcher.py`
already proves non-blocking dispatch + status polling with the
`_BlockingHarness` event pattern. The fix is therefore **wiring**, not
building: the composition root must construct one `ThreadRunDispatcher` with
an explicit lifecycle and route `sync=false` to it; `sync=true` keeps the
inline path.

### Code to write (R3)
- `container.py`: hoist one `ThreadRunDispatcher` out of `submit_run_factory`
  to a container-owned lifecycle (construct once, `shutdown()` on app
  teardown). `submit_run_factory` injects it for the `sync=false` branch.
- Do **not** delete `SyncRunDispatcher` — keep it for `sync=true` and
  deterministic tests (report remedy 3).
- Container teardown must drain/reject outstanding work per an explicit
  contract.

### Tests to introduce (R3)
- New `tests/application/runs/test_sync_false_returns_promptly.py`:
  - `sync=false` with a `_BlockingHarness`-style execute callable blocked on
    a release event → route returns promptly with a non-terminal run; worker
    starts independently; poll until release → exactly one terminal
    transition.
  - `sync=true` with the same callable → response terminal only after
    execution completes.
  - Container `shutdown()` with outstanding work → drains or rejects per the
    documented contract (assert no leaked worker threads).
- Reuse the existing `_BlockingHarness` event triplet for determinism.

---

## Finding 3 — physical-byte dedup loses semantic identity

### What the report claimed
`register()` returns the first artifact with identical bytes, so a second
descriptor silently becomes the first's type/role/schema/metadata.

### Current state — still open; root cause has TWO parts

1. **Repo query** — `artifact_repo.py:17-21`: `SELECT artifact_id FROM
   artifacts WHERE physical_hash = ?` then returns the existing id. The
   provisional id at `artifact_store.py:40` (`{type}:{role}:{phys}`) is
   discarded.
2. **Schema constraint** — `schema.py:113` declares `UNIQUE(physical_hash)`.
   Even if the query were fixed, SQLite would reject a second descriptor
   with the same bytes. The schema **forces** one-descriptor-per-blob.

So the report's blob/descriptor split is required at both layers: a `blobs`
table keyed by `physical_hash`, and `artifacts` referencing the blob with its
own descriptor id (type/role/media/schema/logical/metadata). The
`UNIQUE(physical_hash)` on `artifacts` must move to the blob table.

### Code to write (R4)
- New `blobs` table (`physical_hash PRIMARY KEY`, `storage_key`, bytes
  metadata); `artifacts` keeps `artifact_id` PK + `physical_hash` FK to
  `blobs`, dropping `UNIQUE(physical_hash)`.
- `ArtifactRepo.register()`: insert/ignore the blob, then insert/ignore the
  descriptor keyed by full semantic identity; return the descriptor id.
  Idempotent on exact duplicate descriptor.
- Lineage stays on `artifact_id` (descriptors), not on blob hash.
- A schema migration (the repo provisions fresh DBs in tests, but
  production projects need the split applied — confirm whether a migration
  path is required or whether un-launched status lets us recreate).

### Tests to introduce (R4)
- New `tests/adapters/test_artifact_descriptor_identity.py` (against the real
  adapter + a fresh provisioned DB):
  - Register two descriptors, same bytes, different role/type/schema → one
    blob row, two descriptor rows, lineage resolves each descriptor
    correctly.
  - Typed evidence lookup for both descriptors → each uses its own
    parser/profile (use two `EvidenceKind`s).
  - Register an exact duplicate descriptor → idempotent: no second
    descriptor, no second blob.
- Add an architecture/schema test: `artifacts` no longer has
  `UNIQUE(physical_hash)`; `blobs` does.

---

## Finding 4 — heartbeat / cancellation not fenced

### What the report claimed
Heartbeats happen only before a node begins; a second submission can mark a
long-running node stale and terminalize it. Cancellation is checked only
before a step; a cancellation during the final node is followed by
unconditional success finalization.

### Current state — still open

- `execute_run.py:108-110`: `cancel_requested` checked once at the top of
  the step loop; `:123-130` heartbeats once before `run_step()`; `:235`
  finalizes `"succeeded"` unconditionally after the loop.
- `submit_run.py:188-222` `_sweep_stale`: 300 s threshold, no lease
  ownership check — any caller can terminalize a legitimately-running worker.
- `heartbeat.py` is a one-line `uow.runs.heartbeat(run_id)`; no lease token,
  no renewal during node execution.
- `cancel_run.py:39` sets the flag but nothing fences the worker against
  post-cancel writes.

### Code to write (R3)
- A lease: `runs.heartbeat()` returns/accepts a lease token; the worker
  renews it during node execution (a heartbeat thread or per-node renewals),
  not only between nodes.
- Re-read `cancel_requested` after every completed node **and** immediately
  before `_finalize_run("succeeded")`.
- Fence terminal transition on lease ownership/current status: a worker
  whose lease was lost cannot write output or transition to terminal.
  `runs.transition()` must accept the lease token and reject a stale worker.

### Tests to introduce (R3)
- New `tests/application/runs/test_lease_fencing.py`:
  - Fake clock; block a node > 300 s while a heartbeat worker keeps renewing
    → a second `_sweep_stale` submission does **not** terminalize the run.
  - Cancel a run while its final node is blocked, then release → terminal
    status is `cancelled`, never `succeeded`.
  - Simulate lease loss mid-node → assert no post-loss lineage/evidence/output
    writes are accepted (a fenced `transition()` rejects the stale worker).
- Use a fake clock fixture so the 300 s boundary is deterministic.

---

## Finding 5 — concurrent-run guard is TOCTOU

### What the report claimed
The active-run query and run creation happen in separate UoWs; two callers
can both observe no active run and both insert. No uniqueness constraint
backs the guard.

### Current state — still open

`submit_run.py:73-101` confirms it exactly: `uow2` lists active runs and
raises (`:79-86`), then `uow3` creates the run (`:88-96`) — two separate
transactions. `schema.py:71-87` has no partial unique index on active runs
(the only run indexes are non-unique status/cancel indexes at
`:319-321`).

### Code to write (R3)
- One typed repo operation `runs.create_if_no_active_run(plan_version_id, ...)`
  that does the existence check + insert under one `BEGIN IMMEDIATE`
  transaction (the mutation UoW already begins eagerly from R1 — use it),
  returning a typed concurrent-run result.
- Partial unique index as second line of defence, e.g.
  `CREATE UNIQUE INDEX ... ON runs(plan_version_id) WHERE status IN
  ('created','queued','running')` (where SQLite supports partial indexes —
  it does). `force=true` runs must be exempt, so the index must exclude
  forced runs (`WHERE force = 0`).
- `submit_run` calls the new operation; remove the read-then-create split.

### Tests to introduce (R3)
- New `tests/application/runs/test_concurrent_run_guard.py`:
  - Two-thread barrier so both submissions reach the guard concurrently →
    exactly one succeeds, one returns the concurrent-run error.
  - Repeat with `force=true` → both allowed (forced-run behaviour preserved).
  - Inspect the DB after each case → never more than one active non-forced
    run for the guarded scope.
- Assert the partial unique index exists in a schema test.

---

## Finding 6 — query UoWs leak connections

### What the report claimed
`GetRun`/`GetRunSteps`/`GetRunEvidence` acquire a UoW and return without
closing; `ExplainStaleness` constructed a UoW per staleness request and
never closed it; the evidence route owned a UoW indirectly.

### Current state — CLOSED by R1

- `ExplainStaleness.__call__` now uses `with self._uow_factory() as uow:`
  (`explain_staleness.py:45`); the evidence route passes
  `container.uow_factory.read_only(project_id)` (`evidence.py:28`), and the
  use case owns the lifecycle.
- The dead `GetRun`/`GetRunSteps`/`GetRunEvidence`/`ListRuns` use cases were
  **deleted** in `4710e8b` (so the report's references to
  `get_run.py:14-20` etc. are now stale — note this if the report is
  regenerated).
- `tests/application/test_uow_ownership.py` proves the close-on-success,
  close-on-exception, and `ExplainStaleness` close behaviour with a
  `_CloseSpy`.

No further work. R1 satisfies the report's proof tests for this finding.

---

## Finding 7 — output contracts validate only role presence

### What the report claimed
The contract declares role/kind/media constraints; the validator only checks
required roles are present. Wrong kind/media and undeclared roles pass.

### Current state — still open; the contract fields ALREADY EXIST

`StepRunner._validate_output_roles` (`step_runner.py:260-277`) only computes
`required_roles - produced_roles`. It never reads `ArtifactRoleSpec.kinds`
  or `.media_types`.

Crucially, `ArtifactRoleSpec` **already** carries `kinds` and `media_types`
(`contracts.py:17-22`), and nodes already declare them (e.g.
`explainability.py:109-116`, `freeze.py:35-43`, `models.py:344-350`). So the
fix is to **enforce existing fields**, not to add them. The `StagedArtifact`
already carries `kind`/`media_type`/`schema_version`
(`artifact_store.py:41-50`), so the validator has everything it needs.

### Code to write (R4)
- A pure `validate_output_contract(contract, staged, spec)` that checks, per
  staged output: role is declared; `kind` ∈ `spec.kinds` (if non-empty);
  `media_type` ∈ `spec.media_types` (if non-empty); reject undeclared roles
  when the contract is non-empty. An empty contract remains the only opt-out.
- `StepRunner` calls it instead of `_validate_output_roles`.
- Failure must raise **before** `publish()` (i.e. before any object/DB
  write) — coordinate with R2's publication ordering so contract failure
  produces no file and no row.

### Tests to introduce (R4)
- New `tests/application/execution/test_output_contract_enforcement.py`:
  - Malformed nodes: required role with wrong kind/schema, wrong media type,
    and an undeclared role → each raises before publication.
  - Valid multi-role node → all descriptors + lineage still publish.
  - Assert **no** artifact object and **no** DB row written on validation
    failure (grep `objects/` and the `artifacts`/`artifact_lineage` tables).
- Pure unit tests for `validate_output_contract` with typed fixtures (no
  DB/filesystem).

---

## Finding 8 — governance owns adapter SQL and giant orchestration

### What the report claimed
Governance use cases reach through the port to `uow._conn` and issue SQLite
SQL; `RefreshComparison` combines readiness, evidence interpretation,
report-content construction, publication, snapshot SQL, and state updates
in one 607-line class.

### Current state — still open, confirmed at full size

`refresh_comparison.py:148` `conn = uow._conn`; raw `INSERT INTO
branch_comparison_snapshots` (`:185-196`), `INSERT INTO
comparison_snapshot_plan_versions` (`:198-209`), and
`UPDATE branch_comparisons` (`:214-218`). The file is **607 lines** and
`_build_content` (`:271-313`) bundles WOE/IV, model, validation, and cutoff
builders that each take `dict[str, Any]`.

### Code to write (R5)
- Typed repo operations on `ComparisonRepo`/`BranchRepo`:
  `create_snapshot(...)`, `add_snapshot_plan_version(...)`,
  `set_latest_snapshot(...)`, `create_branch(...)` (move the SQL in
  `create_branch.py:250-321` too — the report cites it). The adapter owns
  SQL; `RefreshComparison` calls typed methods.
- Split `_build_woe_iv`/`_build_model`/`_build_validation`/`_build_cutoff`
  into focused pure builders taking a typed evidence/input model, not
  `dict[str, Any]`.
- Reduce `RefreshComparison` to: readiness decision, builder invocation,
  artifact publication request, one snapshot persistence call.

### Tests to introduce (R5)
- New `tests/application/governance/test_refresh_comparison_ports.py`:
  - Run each governance use case against a fake UoW whose repos implement the
    typed write methods → **no fake needs a `_conn` attribute**.
- New architecture test (extend `tests/test_architecture_boundaries.py`):
  forbid `._conn` access from `cardre/application/**` (grep/AST rule).
- New `tests/application/governance/test_comparison_builders.py`:
  unit-test each builder with typed fixtures, no DB/filesystem.
- Extend the snapshot integration test: a forced persistence failure leaves
  neither the comparison artifact descriptor nor snapshot rows visible
  (atomicity, building on R2's transactional boundary).

---

## Finding 9 — terminal DB state and manifests split-brain

### What the report claimed
Finalization transitions the run status, publishes an immutable manifest,
then relies on context exit to commit. A DB commit failure leaves a
terminal manifest with a non-terminal run row.

### Current state — still open; the file's own docstring now contradicts it

`finalize_run.py:1-8` docstring claims "the manifest is only published after
the status transition succeeds, ensuring the database and manifest always
agree." The code at `:65-74` does `transition(...)` then
`self._manifest_publisher.publish(run_id, payload)` **inside the same
`with uow:` block**; `__exit__` (`connection.py:117-124`) commits only
**after** the publish succeeds. So if `publish()` succeeds but the subsequent
`commit()` fails, the run row is **non-terminal** while an immutable
manifest exists on disk. The docstring's guarantee is exactly what's broken.

### Code to write (R2)
- An outbox: persist the terminal transition **and** a manifest/outbox row
  (canonical payload + hash + publication state) in **one** transaction.
  Commit that transaction first.
- Publish the manifest **after** commit, then mark the outbox row published.
  Startup/reconciliation retries incomplete publications.
- Do not suppress exceptions while building audit-integrity data.

### Tests to introduce (R2)
- Extend `tests/application/runs/test_finalize_run_manifest.py` (real
  adapter, real `FsManifestPublisher`):
  - Force the manifest publisher to fail → DB run is terminal with a
    pending/failed outbox row and no false published manifest.
  - Force the DB commit/outbox update to fail after a publisher attempt →
    reconciliation makes the final state consistent and idempotent.
  - Restart against a pending outbox record → exactly one canonical manifest
    published and the run/manifest hashes agree.
- Fix or remove the misleading `finalize_run.py:1-8` docstring as part of R2.

---

## Cross-cutting notes for the sprint

- **Parity oracles to preserve** (named in `09` and the 06 sprint plan):
  `test_scoring_export_parity`, `test_logistic_regression_known_input`,
  `test_score_scaling_known_input`, `test_golden_fixtures_roundtrip`,
  `test_golden_report_bundle`, `test_run_audit_integrity`. Each R-batch must
  keep these green.
- **R1 is the only closed batch.** R2–R5 remain. The report's recommended
  ordering (1+9 → 2+4+5 → 3+7 → 6+8) maps to R2 → R3 → R4 → (R1 done) → R5.
- **Two report references are now stale** and should be ignored if the
  report is regenerated: the `get_run.py`/`get_run_steps.py`/etc. files
  (deleted in R1) for Finding 6, and the implication that an async
  dispatcher must be *built* for Finding 2 (one already exists at
  `thread_dispatcher.py`).
- **Schema changes cluster in R3 and R4**: R3 adds a partial unique index
  (Finding 5); R4 splits `artifacts` into `blobs` + descriptors and moves the
  `UNIQUE(physical_hash)` (Finding 3). Land R3's index before R4's table
  split so the two migrations don't collide. Confirm the un-launched status
  still permits schema recreation vs. migration (ADR-0003 posture).
- Every fix must run `make preflight` and pass `scripts/pr-gate.sh` before
  review; a passing happy path is insufficient for any finding (report §Audit
  scope).

## Conclusion

All nine findings are accurate against `4710e8b`. The `09-tidy-up-sprint.md`
finding→batch mapping is correct. R1 closes Finding 6 and the transactional
core of Finding 1. R2–R5 are open with the concrete code locations and the
tests to introduce listed above. Two report references are stale (deleted
files; existing async dispatcher) and are noted for the next report
regeneration.