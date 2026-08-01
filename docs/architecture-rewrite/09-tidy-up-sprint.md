# 09 — Post-Refactor Tidy-Up Sprint (R-series)

## Source of truth

This sprint is driven by the **thermonuclear review report**:

- `docs/architecture-rewrite/thermonuclear-review-a130608-to-a7bd161.html` (local only, gitignored)
- Static audit of the full rewrite range `a130608..a7bd161`; **NINE findings: three P1, six P2**; status **REQUEST CHANGES**.

The report is the centrepiece of this sprint. Every R-batch below is scoped directly from one of its nine findings, and every finding's proof tests are carried into the batch's acceptance criteria unchanged. A passing happy path is **not** sufficient — each finding must land with its proving tests.

The report is a working artifact and is regenerated per refactor range; a fresh run supersedes an old one. Do not commit it; `.gitignore` already excludes `docs/architecture-rewrite/thermonuclear-review-*.html`.

## Sprint goal

Make the boundaries the review identifies mandatory rather than compensating for their absence:

- one real transaction boundary per mutation,
- one async execution model that honours the request contract,
- one artifact-descriptor model with a separate physical blob layer,
- one canonical home for persistence logic.

## Findings at a glance

| Priority | # | Finding | R-batch | Status |
|----------|---|---------|---------|--------|
| P1 | 1 | Step persistence is not transactional or recoverable | R1 (transactional core) + R2 (durable publication) | **done** |
| P1 | 2 | `sync: false` runs inline | R3 | **done** |
| P1 | 3 | Physical-byte deduplication loses semantic identity | R4 | **done** |
| P2 | 4 | Heartbeat and cancellation state is not fenced | R3 | **done** |
| P2 | 5 | Concurrent-run guard is TOCTOU | R3 | **done** |
| P2 | 6 | Query UoWs leak connections | R1 | **done** |
| P2 | 7 | Output contracts validate only role presence | R4 | **done** |
| P2 | 8 | Governance use cases own adapter SQL and giant orchestration | R5 | **done** |
| P2 | 9 | Terminal DB state and manifests can split-brain | R2 | **done** |

## Sequencing

Follows the report's recommended order. Each tranche is one PR unless noted.

1. **Runtime-integrity tranche (R1 + R2):** findings 1 and 9. Make step persistence atomic *and* recoverable, and make terminal state agree with its manifest. R1 landed the transaction core and query-UoW ownership; R2 completes the durable publication/outbox protocol and the terminal-state split-brain fix.
2. **Dispatch and fencing tranche (R3):** findings 2, 4, and 5. One async dispatch model, lease-renewing heartbeats, cancellation re-checked before success finalization, and an atomic concurrent-run guard.
3. **Identity and contract tranche (R4):** findings 3 and 7. Separate semantic descriptors from physical blobs; enforce full output contracts before publication.
4. **Cleanup tranche (R5):** finding 8. Move governance SQL behind typed repository operations and decompose `RefreshComparison`.

Do not treat these as independent local patches. Each batch must keep the repo's parity/characterization tests green (`test_scoring_export_parity`, `test_logistic_regression_known_input`, `test_score_scaling_known_input`, `test_golden_fixtures_roundtrip`, `test_golden_report_bundle`, `test_run_audit_integrity`).

---

## R1 — Transactional mutation UoWs, read-only query boundary, close query UoWs

**Status: done** (branch `batch-r1-transaction-uow-ownership`, commit `4710e8b`).

### Objective

Findings 1 and 6: make the mutation boundary impossible to skip and stop query use cases leaking connections.

### Scope delivered

- `SqliteUnitOfWork` begins `BEGIN IMMEDIATE` eagerly in `__init__`; `commit()`/`rollback()`/`close()` always act on a live transaction, so a failed step-persistence mutation rolls back every artifact, run-step, lineage, and evidence row.
- Port contract split into `ReadOnlyUnitOfWork` (no `commit`/`rollback`) and `UnitOfWork`. Query use cases are wired to the read-only factory and cannot silently begin a write transaction.
- `ExplainStaleness` owns its UoW via the context manager; plan read use cases use the read-only factory.
- Deleted dead query use cases (`GetRun`, `GetRunSteps`, `GetRunEvidence`, `ListRuns`) that were unreferenced and leaked connections.
- Added failure-injection and connection-spy proof tests (`tests/application/test_uow_ownership.py`).

### Not in R1

The durable publication half of finding 1 (files leave staging before the DB commit; a later failure leaves unreachable objects) is still open and is owned by R2. Cancellation/heartbeat fencing is R3.

---

## R2 — Durable publication and terminal-state consistency

**Status: done** (commit `HEAD~`; proof tests in `tests/application/runs/test_publication_durability.py`)

### Objective

Findings 1 (publication half) and 9: no artifact object may outlive its durable descriptor, and a terminal manifest must not contradict its run row.

### Scope

- **Durable publication protocol.** Keep files in staging until the DB transaction commits, then finalize them; or commit an outbox/pending-publication row with the DB mutation and finalize/retry it separately. A rollback must either remove a published object or leave a durable reconciliation record.
- **Terminal-state outbox.** Persist the terminal run transition and a manifest/outbox record (canonical payload + hash + publication state) in one transaction. Publish the manifest after commit, then mark the outbox record published. Startup/reconciliation retries incomplete publications. Do not suppress exceptions while building audit-integrity data.

### Proof tests (from the report)

- Inject failures independently at artifact registration, run-step insert, output lineage, input lineage, and evidence-edge insert. Assert the database contains none of the step's rows after each failure.
- For every failure point, assert no file exists in `objects/` without a durable artifact descriptor or pending-publication record.
- Run the same test through the real SQLite adapter, not a fake that hides transaction behaviour.
- Force the manifest publisher to fail. Assert the DB run is terminal with a pending/failed outbox record and no false published manifest.
- Force the DB commit/outbox update to fail after a publisher attempt. Assert reconciliation makes the final state consistent and idempotent.
- Restart against a pending outbox record and assert exactly one canonical manifest is published and the run/manifest hashes agree.

### Acceptance

- All proof tests above pass against the real adapter.
- `make preflight` passes before the PR gate is run.

---

## R3 — Async dispatch, lease fencing, cancellation, concurrent-run guard

**Status: done** (proof tests in `tests/application/runs/test_dispatch_fencing_concurrency.py`)

### Objective

Findings 2, 4, and 5: one process-owned async execution model that honours `sync`, a worker lease that cannot be stolen while a node runs, and an atomic non-forced concurrent-run guard.

### Scope

- **Async dispatch (finding 2).** Create one process-owned asynchronous dispatcher in the composition root with an explicit lifecycle and bounded worker policy. A worker resolves the correct project-scoped `ExecuteRun` instance; the HTTP transport must not construct a dispatcher per request. Keep inline execution only for `sync=true` and deterministic tests.
- **Lease heartbeats (finding 4).** Renew heartbeats during node execution, not just between nodes. Re-read cancellation after every completed node and immediately before success finalization. Fence persistence and terminal transition on lease ownership/current status so a worker cannot write output after a stale recovery or cancellation won the state transition.
- **Concurrent-run guard (finding 5).** Replace the read-then-create guard with one typed repository operation (e.g. `create_if_no_active_run`) under one `BEGIN IMMEDIATE` write transaction; add a partial unique index as a second line of defence where SQLite can express it.

### Proof tests (from the report)

- Submit `sync=false` with an execute callable blocked on an event. Assert the route returns promptly with a non-terminal run and the worker starts independently; poll until the release event is set and assert the run transitions to its terminal state exactly once. Submit `sync=true` with the same callable and assert the response is terminal only after execution completes. Assert container shutdown drains or rejects outstanding work per an explicit contract.
- Block a node longer than 300 seconds using a fake clock while a heartbeat worker continues renewing; submit another run and assert the original is not interrupted. Cancel a run while its final node is blocked, release it, and assert terminal status is cancelled, never succeeded. Simulate lease loss while a node is blocked and assert no post-loss lineage/evidence/output writes are accepted.
- Use a two-thread barrier so both submissions reach the guard concurrently; assert exactly one non-forced submission succeeds and one returns the concurrent-run error. Repeat with `force=true` and assert documented forced-run behaviour. Inspect the database after each case and assert there is never more than one active non-forced run for the guarded scope.

### Acceptance

- All proof tests above pass.
- `make preflight` passes before the PR gate is run.

---

## R4 — Semantic artifact identity and full output-contract enforcement

**Status: done** (proof tests in `tests/application/execution/test_contract_and_identity.py`)

### Objective

Findings 3 and 7: separate byte storage from semantic identity, and enforce the declared output contract before anything is published.

### Scope

- **Blob/descriptor split (finding 3).** A blob table keyed by physical hash holds bytes; an artifact descriptor has its own ID and stores type, role, media type, schema version, logical hash, and metadata. Multiple descriptors may reference one blob. Deduplicate descriptor rows only by complete semantic identity when that is an intentional domain rule. Keep lineage attached to descriptors, not raw blobs.
- **Contract enforcement (finding 7).** Validate every staged output against its matching `ArtifactRoleSpec`, including role, declared kind/schema, and media type. Reject undeclared roles when a node has an explicit output contract; an empty contract remains the only opt-out. Centralize validation in a pure contract validator shared by every node.

### Proof tests (from the report)

- Register two descriptors with the same bytes but different role/type/schema. Assert there is one blob, two descriptors, and lineage resolves each descriptor correctly. Run typed evidence lookup for both descriptors and assert each uses its own parser/profile. Register an exact duplicate descriptor and assert it is idempotent without creating a second descriptor or blob.
- Create deliberately malformed test nodes that emit a required role with an incorrect schema/kind, incorrect media type, and an undeclared role. Assert each fails before publication. Use a valid multi-role node to prove correct contracts still publish all descriptors and lineage. Assert no artifact object or DB row is written when output validation fails.

### Acceptance

- All proof tests above pass.
- `make preflight` passes before the PR gate is run.

---

## R5 — Governance persistence and content decomposition

**Status: done** (proof tests in `tests/application/governance/test_governance_ports.py`)

### Objective

Finding 8: the application layer stops owning adapter SQL and `RefreshComparison` stops being a giant orchestration.

### Scope

- Add typed repository operations for branch creation, snapshot persistence, and champion assignment. The SQLite adapter owns SQL and connection details; the application layer owns the UoW boundary and typed intent. No `uow._conn` access from `cardre/application/**`.
- Split comparison computation into focused pure builders for WOE/IV, model, validation, and cutoff content, fed a typed evidence/input model instead of `dict[str, Any]`.
- Reduce `RefreshComparison` to readiness decision, builder invocation, artifact publication request, and one snapshot persistence call.

### Proof tests (from the report)

- Run each governance use case against a fake UoW whose repositories implement the typed write methods; no fake needs a `_conn` attribute.
- Add an architecture test that forbids `._conn` access from `cardre/application/**`.
- Unit-test each comparison-content builder with typed fixtures and no database/filesystem dependencies.
- Integration-test that a snapshot write is atomic: a forced persistence failure leaves neither the comparison artifact descriptor nor snapshot rows visible.

### Acceptance

- All proof tests above pass.
- `make preflight` passes before the PR gate is run.

---

## Review strategy

- Run `make preflight` before every push; it catches ruff, mypy, line-counts, artifact-reads, governance tests, OpenAPI drift, and frontend checks.
- Each R-batch PR must pass the PR gate (`scripts/pr-gate.sh`) with green CI before requesting review.
- Each batch must land its finding's proof tests — a passing happy path is not enough (report §"Audit scope").
- Preserve the parity/characterization oracles; imports update, behaviour must not.
