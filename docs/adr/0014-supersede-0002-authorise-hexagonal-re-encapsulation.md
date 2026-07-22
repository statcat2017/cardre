# ADR 0014 — Supersede ADR-0002; Authorise the Hexagonal Re-encapsulation

ADR-0002 ("Extend PlanExecutor — Do Not Rewrite the Execution Core") rejected a
greenfield execution rewrite under `cardre/engine/execution/` that would have
introduced competing vocabulary (`node instance`, `node run`, `execution run`),
new DB tables (`execution_runs`, `node_runs`, `node_latest_outputs`), a
single-hash artifact model, and the removal of `role`/`category` from the node
contract. At the time, the existing `PlanExecutor` core was judged to already
deliver most of the proposed acceptance criteria, and the cost of a parallel
execution stack with dual terminology was deemed unjustified.

That decision held for the incremental "deepening" programme that followed
(ADRs 0004–0008, 0013; the merged `deepen-*` and `pr*` branches). The deepening
work improved local seams — manifest hashing, scoring IR, node module
decomposition, the frontend boundary, supervised-training preparation, run
terminal handling, the branch evidence locator — but it did not change the
dependency direction. `ProjectStore` remains a load-bearing god-object; ambient
`CardreConfig.from_env()` is still read in 11 sites; artifact publication is
still not atomic with DB registration; node contracts are still advisory; routes
still construct repositories and perform ownership checks; transactions still
span long-running computation in places.

A 2026-07-21 architecture validation (see
`docs/architecture-rewrite/00-validation-report.md`) confirmed all ten core
structural hypotheses against concrete repository evidence. The conclusion is
that the structural problems are the dependency direction itself, and they are
not fixable by further incremental extraction that keeps `ProjectStore` as the
central object.

## Decision

**ADR-0002 is superseded.** A clean hexagonal re-encapsulation is authorised,
implemented as the 9-batch sprint in `docs/architecture-rewrite/06-sprint-plan.md`.

This is **not** a revival of the rewrite ADR-0002 rejected. The rejected
proposal invented competing vocabulary and dropped role enforcement. This
decision explicitly preserves the design commitments ADR-0002 protected:

1. **Dual hashing** (`physical_hash` + `logical_hash`) — preserved.
2. **Computed staleness** (derived, never a stored column) — preserved.
3. **Build/validate two-stream + role enforcement** (`category`, `input_roles`,
   `output_roles`, `LEAKAGE_SENSITIVE_CATEGORIES`) — preserved and strengthened
   by `OutputPublisher` validation of declared output contracts.
4. **Settled vocabulary** (`StepSpec`, `RunStep`/`RunStepRecord`, `run`/`run_id`,
   `plan_version_id`) — preserved. No `node instance`/`node run`/`execution run`.
5. **Single execution path** — preserved (every run goes through `ExecuteRun`).

What changes is the **ownership and direction of dependencies**, not the
domain model:

- `ProjectStore` is replaced by a `UnitOfWork` (owns connection + transaction
  only) + SQLite query objects behind ports. Path resolution moves to
  `ArtifactStore` (filesystem adapter) and `ProjectRegistryPort`.
- `ExecutionContext.store` is replaced by `NodeContext` carrying only
  `inputs: InputCollection`, `outputs: OutputPublisher`, `params`, `runtime`,
  `logger`. Nodes cannot reach `sqlite3`, `ProjectStore`, `os.environ`, or
  arbitrary artifacts.
- `CardreConfig.from_env()` is replaced by `bootstrap/settings.py:Settings`
  read once in `build_app()`. No env access outside bootstrap.
- Artifact publication becomes atomic: stage → validate → publish (fs) →
  register (db) → lineage (db) → evidence (db) inside one `UnitOfWork`.
- Routes become thin handlers calling use cases; no repo construction, no
  ownership checks, no `X-Project-Id`/`X-Project-Path` headers.
- The clean SQLite schema (v1, no migration chain) drops dead states
  (`created`/`queued`/`pending`/`skipped`) and adds `cancel_requested` +
  CHECK constraints. No migration from v2 schema 101 is required (ADR-0003
  confirms no persisted plans exist).
- The node contract becomes enforceable: `NodeDefinition` declares input/output
  `ArtifactContract` with `ArtifactRoleSpec` (role, required, kinds,
  media_types); `OutputPublisher` rejects undeclared roles
  (`OUTPUT_CONTRACT_VIOLATION`); `StepRunner` checks required outputs produced.
- Architecture enforcement becomes blocking via `importlinter` + extended
  forbidden-symbol AST tests from the first batch.

## Considered Options

- **Continue the deepening programme** (ADR-0002's choice): keep extending
  `PlanExecutor`/`ProjectStore` incrementally. Rejected: the validation shows
  the problems are the dependency direction, not local seams; deepening has
  reached diminishing returns and does not resolve the inward flow of
  infrastructure into nodes/services/execution.

- **Compatibility refactor** (dual schemas, dual APIs, transitional node
  contexts, `ProjectStore` facade over the new UoW): rejected. ADR-0003
  confirms no external consumers and no persisted plans; the cost of dual
  maintenance is paid for no benefit. A wrapper that exposes `store` until
  every node is migrated defeats the node contract.

- **Hexagonal re-encapsulation** (this decision): clean cut, 9 batches,
  preserves domain vocabulary and validated behaviour, restructures dependency
  direction and ownership. The cost is one new schema (no migration), one new
  API (no external consumers), one regenerated frontend client, ~51 node ports
  (mechanical), ~12 use cases (mechanical), ~11 SQLite adapters (mechanical),
  one artifact store, one bootstrap. No dual maintenance.

## Preserved design commitments (carried from ADR-0002)

These remain non-negotiable and are restated for clarity:

1. **Dual hashing** — `ArtifactRef` keeps `physical_hash` + `logical_hash`.
2. **Computed staleness** — `is_stale` stays derived, never stored.
3. **Build/validate role enforcement** — `NodeDefinition.input_contract` /
   `output_contract` carry roles + kinds; `StepRunner` enforces; leakage rules
   preserved.
4. **Settled vocabulary** — no competing terminology.
5. **Single execution path** — `ExecuteRun` is the only seam.

## Consequences

- The `cardre/engine/execution/` tree is **still not created** (ADR-0002's
  specific objection to that tree stands). The new execution runtime lives in
  `application/runs/` + `application/execution/` + `adapters/dispatch/`.
- The `cardre/store/` package is deleted (replaced by `adapters/sqlite/`).
- `cardre/services/` is deleted (replaced by `application/**` use cases).
- `cardre/execution/` is deleted (replaced by `application/execution/` +
  `adapters/dispatch/`).
- `cardre/config.py` is deleted (replaced by `bootstrap/settings.py`).
- `cardre/artifacts.py` is deleted (replaced by `adapters/filesystem/`).
- `cardre/_evidence/` is split: `domain/evidence/` (kinds, schemas) +
  `adapters/evidence/` (profiles, parsers).
- `cardre/engine/binning/` is moved to `domain/binning/` or `nodes/build/_woe.py`
  (the one piece of `cardre/engine/` that survives; ADR-0002 noted it remained
  alongside `executor.py` — it now moves to its proper layer).
- The SQLite schema is recreated (v1); no migration runner ships until first
  real deployment (ADR-0003).
- The frontend client is regenerated once from the new OpenAPI; `openapi-fetch`
  transport + `ApiError` codes preserved (ADR-0006).
- All parity/characterization tests
  (`test_scoring_export_parity.py`, `test_logistic_regression_known_input.py`,
  `test_score_scaling_known_input.py`, `test_golden_fixtures_roundtrip.py`,
  `test_golden_report_bundle.py`, `test_run_audit_integrity.py`) are preserved
  as behavioural oracles; imports update, outputs must not change.
- The application does not remain runnable after every intermediate batch;
  broken intermediate states are documented in
  `06-sprint-plan.md §Point at which old architecture disappears`.

## Relationship to prior ADRs

- **ADR-0001** (build/validate two-stream): preserved. Role enforcement
  strengthened.
- **ADR-0003** (no legacy plan accommodation): upheld; enables the clean cut.
- **ADR-0004** (single run lifecycle, atomic finalisation): preserved and
  deepened — manifest write + status transition now inside one `UnitOfWork`.
- **ADR-0005** (canonical evidence resolution): preserved — 4-stage fallback
  chain moves from `EvidenceLocator(store)` to
  `application/evidence/evidence_resolver.py` using ports.
- **ADR-0006** (generated API contract as frontend boundary): preserved —
  openapi-fetch + generated `paths`/`components` retained; regenerated once.
- **ADR-0007** (modelling sample-role and leakage policy): preserved —
  `_training_utils.prepare_supervised_training_data` ported to take
  `InputCollection`.
- **ADR-0013** (evidence locator implementation): preserved — logic moves to
  `application/evidence/`.

## Status

Accepted. Supersedes ADR-0002 in full. ADR-0002's preserved design commitments
(§"Preserved design commitments") are reaffirmed here and carried forward
unchanged; only the "extend, do not rewrite" conclusion is overturned.