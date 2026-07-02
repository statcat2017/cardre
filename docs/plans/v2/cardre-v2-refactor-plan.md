# Cardre v2 — Big-bang refactor plan

A clean v2 branch, no compat shims, no migration code, no deprecation
windows. v1 stays on `main` as-is for reference; v2 is built on a `v2` branch
and replaces `main` when done.

## Context and constraints

- **No existing user projects.** Cardre never launched. There is no backwards
  compatibility requirement at all.
- **Fresh-projects-only on disk.** A v2 `.cardre` dir is created from scratch;
  v1 `.cardre` dirs cannot be opened (hard error, no migration).
- **Full v2 shape.** Five first-class domain concepts (`Project`, `PlanVersion`,
  `Step`, `Run`, `Evidence`), new package layout, `evidence_edges` +
  `evidence_artifacts` tables, project-scoped routes, manual-binning review
  object.
- **Manual binning early.** Paired with the store layer in Phase 2, not late
  after the launch pathway. v1's hard lesson was leaving manual binning late;
  v2 does not repeat it. Phase 2 may need a second pass after Phase 3 — that is
  an expected outcome, not a failure.
- **Big-bang chosen** because with no users, the main argument for in-place
  (main stays shippable) is gone. Big-bang removes all compat-shim accounting
  and lets each phase be a clean delete-and-rewrite.

## Guiding principles

1. **Preserve v1 achievements.** `RunService`, `EvidenceResolver`,
   `staleness.py`, `fetchJson`, `useRunProgress`, `CardreConfig`,
   `artifact_lineage` already exist and work. We rename/move them; we do not
   rewrite their logic. Porting discipline is auditable via line-number
   references.
2. **No shim owns behaviour.** v2 never creates `run_orchestrator.py`.
3. **No compat re-exports.** v2 deletes and rewrites; tests go red during a
   phase and are fixed within the same phase.
4. **No migration code, but a hard version check.** No `run_migrations()`
   body, no backfill. `store_meta` records `schema_family` and
   `schema_version`; opening an incompatible store is a hard error. This is
   project safety, not legacy migration.
5. **No JSON arrays for queryable relationships — no exceptions.** Lineage,
   evidence, branch ownership, plan graph edges, comparison challengers,
   snapshot sources, manual-binning review status, champion assignment,
   diagnostics are all in typed columns with indexes. JSON is only for true
   open-ended metadata, node params, preview payloads, and rendered report
   metadata.
6. **Tests move with the code.** A module ported from v1 takes its
   characterization test cases from `tests_v1/` (the v1 tests retained as a
   reference directory) and ports them forward.
7. **One phase = one PR to `v2`.** Phase-local CI, not full preflight, until
   Phase 6. CI green before merge to `v2`. Full `make preflight` is the
   end-of-Phase-6 gate before `v2` merges to `main`.
8. **No conditional route registration.** Governance gating is via a
   `Depends(require_governance)` dependency that returns 403, not via
   `if governance_enabled: app.include_router(...)`.
9. **No test reads env vars directly.** Tests go through
   `CardreConfig.from_env()` or
   `monkeypatch.setattr(CardreConfig, "from_env", ...)`. No direct
   `os.environ.get` in tests.
10. **Staleness is computed, never written onto historical evidence.**
    Evidence rows describe what happened in a historical run; they are never
    rewritten because a new draft exists. Staleness is derived from plan
    version + step params hash + parent graph + source run evidence + logical
    hashes + manual-binning review state.
11. **Domain kernel has no I/O dependencies.** `cardre/domain/` is importable
    without the node registry, store, FastAPI, or optional modelling
    dependencies. `NodeType` (an executable plugin interface) lives in
    `cardre/nodes/contracts.py`, not in domain. `CardreConfig` (reads env
    vars) lives at `cardre/config.py`, not in domain.
12. **Each phase's agent session reads a decision log first.** Beyond ADRs,
    each phase produces a short decision-log entry that the next phase's
    agent session reads before starting. This guards against context-coherence
    drift in long phases (3 and 5).

## Setup

1. Create `v2` branch from `main`.
2. Delete everything except:
   - `cardre/nodes/` — engine implementations are reusable (repoint imports).
   - `cardre/engine/` — binning engine, reusable.
   - `cardre/modeling/` — model adapters, builders, serialization.
   - `cardre/reporting/` — collectors, renderers, templates, readiness checks.
   - `cardre/_evidence/` — readers, profiles, schemas (reusable infrastructure).
   - `cardre/readiness/` — readiness checks.
   - `frontend/src-tauri/` — Rust shell, unchanged.
   - `frontend/package.json` / `vite.config` / `tsconfig` — build config.
   - `pyproject.toml` — dependencies.
   - `docs/adr/` — decisions carry over.
   - `CONTEXT.md` — domain glossary carries over, updated at end.
   - `Makefile`, `scripts/pr-gate.sh`, `.github/`, `AGENTS.md`, `opencode.json`,
     `.gitignore`, `skills-lock.json`, `SECURITY.md`, `CONTRIBUTING.md`.
3. Keep `tests/` as a reference directory renamed `tests_v1/` — not run, not
   maintained, used as a source of characterization test cases to port forward
   selectively.
4. v2 starts with a near-empty `cardre/` and `sidecar/` and `frontend/src/`.
   The only v1 code that survives is pure engine/modeling/reporting
   infrastructure with no dependency on v1's `audit.py`, `ProjectStore`,
   `RunService`, or route layer. Anything that imported those is rewritten.

## CI rules

The plan's earlier draft said both "test sweep going red is fine" and "CI
green before merge" — those conflict unless CI is phase-aware. Resolve:

- **During v2 build (Phases 1–5):** phase-local CI. Each phase's PR runs only
  the tests for the modules that phase introduces. A temporary
  `make v2-phase-check PHASE=N` gate (or equivalent CI filter) runs the
  phase's allowed test subset. Deleting shared v1 modules *will* break
  unrelated v1 tests; that is expected and not a CI failure during the build.
- **Before `v2` → `main` merge (end of Phase 6):** full `make preflight` +
  `scripts/pr-gate.sh`. This is the only point the full suite must be green.

Do not pretend full `make preflight` stays green after deleting shared v1
modules in Phase 1.

## Phase order (6 phases, sequential)

### Phase 1 — Domain kernel + relational store (~3-4 days)

**Build fresh — domain kernel (no I/O dependencies):**

- `cardre/domain/project.py` — `Project`.
- `cardre/domain/plan.py` — `Plan`, `PlanVersion` with `is_committed: bool`
  baked in from day one (draft vs committed).
- `cardre/domain/step.py` — `StepSpec` only. **No `NodeType` here** — it is an
  executable plugin interface with registry/param-schema coupling and belongs
  in `cardre/nodes/contracts.py`.
- `cardre/domain/run.py` — `Run`, `RunStep`, `RunScope`, `RunStepStatus` enum,
  run state machine (`created → queued → running → succeeded | failed |
  cancelled | interrupted`). `RunStep` does **not** own
  `input_artifact_ids`/`output_artifact_ids` arrays — those are derived via
  `RunStepEvidenceView` from `evidence_artifacts` + `artifact_lineage`.
- `cardre/domain/evidence.py` — `EvidenceEdge`, `EvidenceArtifact`,
  `ResolvedEvidence` (the two-level model; see schema below).
- `cardre/domain/manual_binning.py` — `ManualBinningReview`.
- `cardre/domain/artifacts.py` — `ArtifactRef`, `physical_hash`,
  `json_logical_hash`, `table_logical_hash`, `relative_path`. Copy from v1
  `audit.py:41-60` verbatim — pure functions.
- `cardre/domain/errors.py` — `CardreError`, `Diagnostic`,
  `GovernanceNotEnabled`, `GraphValidationError`,
  `PlanContainsUnavailableNodesError`. Copy from v1 `errors.py`.
- `cardre/domain/diagnostics.py` — `utc_now_iso`, `parse_iso`, `JsonDict`.
- `cardre/domain/__init__.py` — re-exports the five first-class concepts.

**Build fresh — outside domain (have I/O dependencies):**

- `cardre/config.py` — `CardreConfig` (copy from v1 `config.py:14-44`). **Not
  in `cardre/domain/`** — it reads env vars; domain must not.
- `cardre/capabilities.py` — derived capabilities from config (launch mode,
  governance). Not `AppProfile` — just the two booleans, routed through one
  place. Tests use `monkeypatch.setattr(CardreConfig, "from_env", ...)`, never
  `os.environ.get`.
- `cardre/nodes/contracts.py` — `NodeType` (the executable plugin interface),
  `ArtifactContract`, `RolePolicy`. Port from v1.
- `cardre/execution/context.py` — `ExecutionContext`, `NodeOutput`. Port from
  v1 `audit.py`. These have execution coupling and belong in the execution
  layer, not domain.

**Build fresh store — clean relational schema, no queryable JSON arrays:**

- `cardre/store/schema.py` — `STORE_SCHEMA_VERSION = 100` (hard break).
  Tables listed below. No `MIGRATIONS_SQL`, no backfill.
- `cardre/store/db.py` — `ProjectStore` connection +
  `@contextmanager transaction()`. Thin.
- `cardre/store/project_repo.py`, `plan_repo.py`, `step_repo.py`,
  `run_repo.py`, `run_step_repo.py`, `artifact_repo.py`,
  `evidence_repo.py`, `branch_repo.py`, `manual_binning_repo.py`,
  `comparison_repo.py`. One repo per table group. Query-only; no business
  logic.
- `cardre/store/__init__.py` — `ProjectStore` facade.

**Key schema decisions:**

`plan_step_edges` — replaces v1's `plan_steps.parent_step_ids_json`. Plan
graph edges are queryable relationships; they must be rows.

```sql
CREATE TABLE IF NOT EXISTS plan_step_edges (
    plan_version_id TEXT NOT NULL,
    parent_step_id TEXT NOT NULL,
    child_step_id TEXT NOT NULL,
    edge_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_version_id, parent_step_id, child_step_id),
    FOREIGN KEY(plan_version_id, parent_step_id)
        REFERENCES plan_steps(plan_version_id, step_id) ON DELETE CASCADE,
    FOREIGN KEY(plan_version_id, child_step_id)
        REFERENCES plan_steps(plan_version_id, step_id) ON DELETE CASCADE
);
CREATE INDEX idx_plan_step_edges_child
    ON plan_step_edges(plan_version_id, child_step_id);
CREATE INDEX idx_plan_step_edges_parent
    ON plan_step_edges(plan_version_id, parent_step_id);
```

`evidence_edges` + `evidence_artifacts` — two-level model. The single-table
`evidence_resolution` from the earlier draft mixed grains: per-parent-step
staleness vs per-artifact reuse. Split cleanly.

```sql
CREATE TABLE IF NOT EXISTS evidence_edges (
    evidence_edge_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    run_step_id TEXT NOT NULL REFERENCES run_steps(run_step_id) ON DELETE CASCADE,
    plan_version_id TEXT NOT NULL,
    step_id TEXT NOT NULL,          -- consuming step
    parent_step_id TEXT NOT NULL,   -- upstream logical parent
    source_run_id TEXT NOT NULL,
    source_run_step_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    source_label TEXT NOT NULL,     -- branch | full_plan | across_plan | latest_plan_run | run
    is_reused INTEGER NOT NULL,
    is_stale INTEGER NOT NULL,
    stale_reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(run_step_id, parent_step_id, source_run_step_id)
);

CREATE TABLE IF NOT EXISTS evidence_artifacts (
    evidence_artifact_id TEXT PRIMARY KEY,
    evidence_edge_id TEXT NOT NULL REFERENCES evidence_edges(evidence_edge_id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    role TEXT NOT NULL,             -- train | test | oot | none
    created_at TEXT NOT NULL,
    UNIQUE(evidence_edge_id, artifact_id)
);

CREATE INDEX idx_evidence_edges_run_step
    ON evidence_edges(run_step_id);
CREATE INDEX idx_evidence_edges_pv_step
    ON evidence_edges(plan_version_id, step_id);
CREATE INDEX idx_evidence_edges_parent
    ON evidence_edges(plan_version_id, parent_step_id);
CREATE INDEX idx_evidence_edges_source_step
    ON evidence_edges(source_run_step_id);
CREATE INDEX idx_evidence_artifacts_artifact
    ON evidence_artifacts(artifact_id);
CREATE INDEX idx_evidence_artifacts_edge_role
    ON evidence_artifacts(evidence_edge_id, role);
```

This gives clean answers to: which parent step supplied evidence? Which run
step supplied it? Was the parent evidence stale? Which artifacts came through
that edge? Which roles were consumed? Mixed role states such as
"train reused + test stale from parent Y" are represented by separate
`evidence_edge` rows for the different freshness/reuse states, each with the
relevant `evidence_artifacts` rows hanging off it.

`comparison_challenger_branches` +
`comparison_snapshot_plan_versions` — replaces v1's
`challenger_branch_ids_json` and `source_plan_version_ids_json`.

```sql
CREATE TABLE IF NOT EXISTS comparison_challenger_branches (
    comparison_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (comparison_id, branch_id)
);
CREATE TABLE IF NOT EXISTS comparison_snapshot_plan_versions (
    comparison_snapshot_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    branch_id TEXT,
    PRIMARY KEY (comparison_snapshot_id, plan_version_id)
);
```

`store_meta` — not migration code, project safety. Hard-error on
incompatible stores.

```sql
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- On fresh project creation, write:
--   schema_family = cardre-v2
--   schema_version = 100
--   created_by_cardre_version = ...
-- On open:
--   missing store_meta            -> hard error
--   schema_family != cardre-v2    -> hard error
--   schema_version > supported    -> hard error
--   schema_version < supported    -> hard error
```

`run_steps` — no `input_artifact_ids_json` / `output_artifact_ids_json`.
Keep `execution_fingerprint_json` (renamed intent: execution metadata —
`node_type`, `node_version`, `params_hash`, `code_version`,
`library_versions`, runtime warnings, diagnostic payload). Staleness reads
`evidence_edges`/`evidence_artifacts` + params hashes, not this column.

`manual_binning_reviews` — per earlier draft.

Full table list: `projects`, `plans`, `plan_versions` (with `is_committed`),
`plan_steps`, `plan_step_edges`, `runs`, `run_steps` (no JSON artifact arrays),
`artifacts`, `artifact_lineage`, `evidence_edges`, `evidence_artifacts`,
`diagnostics`, `manual_binning_reviews`, `branches`, `branch_step_map`,
`branch_comparisons`, `comparison_challenger_branches`,
`branch_comparison_snapshots`, `comparison_snapshot_plan_versions`,
`step_annotations`, `champion_assignments`, `exports`, `store_meta`.

**Tests (fresh, porting characterization cases from `tests_v1/`):**

- `tests/test_domain_artifacts.py` — hash determinism, canonical form.
- `tests/test_domain_step.py` — `StepSpec` construction, `params_hash`
  stability.
- `tests/test_domain_plan.py` — draft/committed transitions, immutability
  after commit.
- `tests/test_domain_run.py` — state machine transitions, illegal
  transitions raise; `RunStep` does not own artifact arrays.
- `tests/test_store_schema_no_queryable_json.py` — asserts no
  `*_ids_json`/`*_ids` array columns exist on relationship tables (catches
  regressions).
- `tests/test_store_rejects_v1_project.py` — opening a store with
  `schema_family != cardre-v2` raises `STORE_VERSION_INCOMPATIBLE`.
- `tests/test_plan_step_edges.py` — graph edges are rows, queryable by
  parent and child.
- `tests/test_evidence_edges_and_artifacts.py` — write/read the two-level
  model; mixed role freshness is represented by separate edge rows with
  attached artifacts.
- `tests/test_store_manual_binning_reviews.py` — review lifecycle.
- `tests/test_store_transaction.py` — rollback on error.

**Verification (phase-local):**

```
ruff check --fix cardre/domain cardre/store cardre/config.py cardre/capabilities.py
pytest tests/test_domain_ tests/test_store_ tests/test_plan_step_edges tests/test_evidence_edges_and_artifacts tests/test_store_schema_no_queryable_json tests/test_store_rejects_v1_project -q
```

**DoD:** Domain kernel compiles with no node-registry/store/FastAPI imports;
store creates a fresh `.cardre` dir with the new schema; `store_meta`
hard-errors on v1 stores; no queryable JSON relationship arrays exist; all
phase-local tests green.

**Abort criterion:** if `evidence_edges` + `evidence_artifacts` cannot express
"step X consumed train+test from parent Y, with train reused and test stale"
as separate edge rows grouped by source/run-step freshness, the schema is
wrong — stop and redesign before proceeding. This is a paper check; the
running-code pressure test comes in Phase 5
(`test_launch_pathway.py`), ~12-16 days in. Treat that as the real schema
acceptance test, not Phase 1.

**Decision log:** Phase 1 writes a short entry recording the final schema
shape, the `NodeType`-out-of-domain decision, and the
`CardreConfig`-out-of-domain decision. Phase 2's agent session reads it first.

---

### Phase 2 — Manual-binning domain + mutation service + minimal API/UI spike (~5-7 days)

Manual binning early, paired with the domain layer it depends on. This phase
validates the `ManualBinningReview` and `PlanMutationService` designs against
a real UI before the execution layer exists.

**Downstream-invalidation mechanism (decided up front, not TBD):**

Do **not** mutate historical evidence rows to mark downstream stale. Evidence
rows describe what happened in a historical run; they are never rewritten
because a new draft exists. Instead:

1. Manual-binning edit creates a new draft plan version.
2. The new manual-binning step's `params_hash` differs from any prior step.
3. Downstream steps in the new plan version have no matching
   `evidence_edges` (no run has executed them against this plan version).
4. `StalenessService.explain_step` returns `status="missing"` or
   `"stale"` for downstream steps because no evidence exists for the new
   draft version / changed params hash.
5. If the UI needs hints about which steps are affected, store them as
   review/workflow state on `manual_binning_reviews` (e.g. an
   `affected_downstream_step_ids` field on the review row — a UI hint, not
   evidence truth). The authoritative answer is always the
   `StalenessService` query against `evidence_edges`.

This upholds the principle: staleness is computed from plan version + step
params hash + parent graph + source run evidence, never written onto old
rows.

**Build fresh:**

- `cardre/services/plan_mutation_service.py` —
  `PlanMutationService.apply_manual_binning_edit(command)`:
  1. Validate source fine-classing evidence (reads from `evidence_edges` +
     `evidence_artifacts` — but since execution doesn't exist yet, this
     phase uses a *test fixture* that inserts evidence rows directly).
  2. Create a new draft plan version from the base; insert `plan_step_edges`
     rows for the new graph.
  3. Add/update the manual-binning step on the draft.
  4. Persist `ManualBinningReview` row (with `affected_downstream_step_ids`
     as a UI hint).
  5. Return the new draft plan version + affected steps.
  All in one `transaction()`. **No mutation of historical evidence rows.**
- `cardre/services/manual_binning_service.py` — preview + validation logic
  only (extract the relevant pure functions from v1
  `manual_binning_service.py:48-73` — `_extract_woe_by_bin`, `_extract_iv`,
  `_extract_event_rate_by_bin` are pure and reusable).
- `cardre/services/plan_service.py` — `get_plan`, `get_plan_version`,
  `list_plans`, `commit_plan_version`. Step mutations go through
  `PlanMutationService`.

**Minimal API skeleton (moved up from Phase 4 so the spike is end-to-end,
not mocked):**

- `cardre/api/app.py` — minimal FastAPI app.
- `cardre/api/dependencies.py` — `get_project_store`.
- `cardre/api/routes/health.py` — `/health`.
- `cardre/api/routes/projects.py` — `/projects`, `/projects/{project_id}`.
- `cardre/api/routes/manual_binning.py` —
  `/projects/{project_id}/manual-binning/reviews`,
  `/projects/{project_id}/manual-binning/reviews/{review_id}` (GET, PATCH).
- `cardre/api/schemas.py` — Pydantic models for the above only.
- `cardre/api/errors.py` — error envelope.

Phase 4 then *expands* the API rather than introducing it from nothing.

**UI spike (end-to-end, against the minimal API):**

- `frontend/src/api/client.ts` — copy v1's `fetchJson<T>` + `ApiError`
  verbatim (597 lines of robust error handling, no reason to rewrite).
- `frontend/src/api/schema.ts` — generated from the minimal v2 OpenAPI.
- `frontend/src/components/ManualBinningEditorSpike.tsx` — minimal editor:
  variable list, bin grid, WOE/IV preview, warnings panel, reviewer notes,
  approve/reject. Calls the real (minimal) endpoint.
- `frontend/src/hooks/useManualBinningReview.ts` — load review state, submit
  the atomic command.

**Tests:**

- `tests/test_plan_mutation_service.py` — apply manual binning edit creates
  draft version, persists review, all in one transaction (rollback on error
  mid-way). Asserts historical evidence rows are **not** mutated.
- `tests/test_manual_binning_preview.py` — WOE/IV extraction from evidence.
- `tests/test_api_manual_binning.py` — the minimal route round-trips.
- `frontend/src/components/__tests__/ManualBinningEditorSpike.test.tsx` —
  full edit-to-review cycle via the spike UI against the real minimal API.

**Verification (phase-local):**

```
ruff check --fix
pytest tests/test_plan_mutation_service.py tests/test_manual_binning_preview.py tests/test_api_manual_binning.py -q
cd frontend && npm run typecheck && npm run test -- ManualBinningEditorSpike
```

**DoD:** A manual-binning edit can be performed end-to-end (command → draft
version → review row → UI renders it) against the real minimal API,
validating the domain model against real interaction. Historical evidence
rows are not mutated.

**Expected outcome, not failure:** Phase 2 may need a second pass after
Phase 3, because the spike uses fixture-inserted evidence rows, not real run
evidence. Integration issues that only surface once real evidence flows
through will appear in Phase 3 or 5. Budget for a Phase 2 revisit.

**Decision log:** Phase 2 writes a short entry recording the
downstream-invalidation decision, the minimal-API shape, and the
`ManualBinningReview` field set. Phase 3's agent session reads it first.

---

### Phase 3 — Execution layer: RunCoordinator + EvidenceResolver + StalenessService (~4-5 days)

**Build fresh (porting logic from v1 where it's correct):**

- `cardre/execution/executor.py` — `PlanExecutor`. Port from v1
  `executor.py:1-826` but:
  (a) write `evidence_edges` + `evidence_artifacts` rows **per run-step
  inside the run transaction**, not only at finalisation. If finalisation
  fails, step evidence must already be persisted inside the transaction,
  not reconstructed from memory.
  (b) write `artifact_lineage` rows.
  (c) do **not** write `input_artifact_ids_json`/`output_artifact_ids_json`
  on `run_steps` (those columns don't exist in v2 schema).
  Topological ordering, role/leakage enforcement, node execution loop carry
  over from v1 — that logic is correct.

  Execution flow:
  ```
  ActionPlanner resolves intended evidence.
  PlanExecutor executes action.
  RunStepRepository writes run_step.
  EvidenceRepository writes evidence_edge + evidence_artifacts for that run_step.
  RunLifecycle finalises run and manifest.
  ```

- `cardre/execution/run_lifecycle.py` — `RunLifecycle` with `run_lease()`,
  `finalise_run()`, manifest writing. Port from v1 `run_lifecycle.py:1-484`.
- `cardre/execution/worker.py` — `RunWorker`, `RunRequest`, `RunDispatcher`,
  `ThreadRunDispatcher`, `SyncDispatcher`. Port from v1
  `run_worker.py:1-256`.
- `cardre/execution/action_planner.py` — port from v1
  `execution/action_plan.py`.
- `cardre/execution/dispatcher.py` — dispatch substrate (sync + thread).
- `cardre/execution/__init__.py`.

- `cardre/services/run_coordinator.py` —
  `RunCoordinator.run(request: RunRequest) -> RunSummary` and
  `RunCoordinator.execute_created_run(run_id: str) -> RunSummary`.

  **Persist run request fields at run creation** so
  `execute_created_run(run_id)` is recoverable for async dispatch and crash
  recovery. The `runs` table stores: `run_scope`, `branch_id`,
  `target_step_id`, `force`, `requested_by`, `request_id`, `created_at`,
  `queued_at`, `started_at`. `execute_created_run(run_id)` loads these from
  the database rather than requiring a `RunExecutionRequest` argument. This
  is the preferred design for async recovery.

  The short-circuit logic, placeholder cancellation, sync/async dispatch,
  stale-run recovery all carry over from v1 `run_service.py:57-411`. Class
  renamed to `RunCoordinator` (free rename, clearer name).

- `cardre/services/evidence_resolver.py` — `EvidenceResolver` (the class) +
  `EvidencePolicyService` (the policy single-source-of-truth) in one module.
  Port from v1 `evidence_resolver.py:1-219` and
  `services/evidence_policy.py:1-274`. Two classes, one file. Return type
  extended to populate `EvidenceEdge` + `EvidenceArtifact` (Phase 1 domain
  objects) so the executor persists them directly into the two-level tables.

- `cardre/services/staleness_service.py` —
  `StalenessService.explain_step(plan_version_id, step_id) -> StalenessExplanation`.
  Port the pure functions from v1 `staleness.py:1-203` but **read from
  `evidence_edges` + `evidence_artifacts`, not
  `run_steps.execution_fingerprint_json`**. This is the real behaviour
  change: staleness uses the Phase 1 two-level tables, not reconstructed JSON.

**`RunStep` / `RunStepEvidenceView` split:**

v1's `RunStepRecord` directly contains `input_artifact_ids` and
`output_artifact_ids`. In v2, `RunStep` (domain) owns only execution metadata;
artifact arrays are derived:

```python
@dataclass(frozen=True)
class RunStep:
    run_step_id: str
    run_id: str
    step_id: str
    plan_version_id: str
    status: RunStepStatus
    started_at: str
    finished_at: str | None
    execution_fingerprint: dict   # metadata only — node_type, node_version, params_hash, code_version, library_versions
    warnings: list[Diagnostic]
    errors: list[Diagnostic]

@dataclass(frozen=True)
class RunStepEvidenceView:
    run_step: RunStep
    input_artifacts: list[ArtifactRef]    # derived from evidence_artifacts
    output_artifacts: list[ArtifactRef]  # derived from artifact_lineage
    evidence_edges: list[EvidenceEdge]
```

**Tests (port characterization cases from `tests_v1/`):**

- `tests/test_executor.py` — topological order, role enforcement, node
  execution; evidence rows persisted per-step inside the transaction.
- `tests/test_run_lifecycle.py` — lease, finalise, manifest.
- `tests/test_run_coordinator.py` — sync/async equivalence, short-circuit,
  placeholder cancellation, stale recovery; `execute_created_run(run_id)`
  recovers request fields from the `runs` table.
- `tests/test_evidence_resolver.py` — four policies (`run_only`,
  `branch_then_full_then_plan`, `source_branch_then_full_then_plan`,
  `across_plan`), fingerprint matching, diagnostic emission; writes
  `evidence_edges` + `evidence_artifacts`.
- `tests/test_staleness_service.py` — `explain_step` returns correct
  `status` + `upstream_changes` + `missing_evidence`, reading from
  `evidence_edges`/`evidence_artifacts`.

**Verification (phase-local):**

```
ruff check --fix
pytest tests/test_executor.py tests/test_run_lifecycle.py tests/test_run_coordinator.py tests/test_evidence_resolver.py tests/test_staleness_service.py -q
```

**DoD:** `RunCoordinator` is the single run entrypoint; sync and async produce
equivalent `RunSummary` + `evidence_edges`/`evidence_artifacts` rows +
diagnostics; staleness reads from the new tables;
`execute_created_run(run_id)` recovers from the DB; no
`run_orchestrator.py` exists.

**Abort criterion:** if sync and async runs produce non-equivalent
`evidence_edges`/`evidence_artifacts` rows, the dispatch path has a fork —
stop and unify before Phase 4.

**Decision log:** Phase 3 records the per-step evidence persistence decision,
the `RunStep`/`RunStepEvidenceView` split, and the
`execute_created_run(run_id)` recovery design. Phase 4's agent session reads
it first.

---

### Phase 4 — Full project-scoped API + generated frontend types (~3-4 days)

**Expand the minimal API from Phase 2 to the full surface:**

- `cardre/api/app.py` — all routers mounted unconditionally (no
  `if governance_enabled: app.include_router(...)`).
- `cardre/api/schemas.py` — full Pydantic model set.
- `cardre/api/errors.py` — full error envelope, `GOVERNANCE_DISABLED` 403,
  `PLAN_VERSION_IMMUTABLE`, `STORE_VERSION_INCOMPATIBLE`,
  `RUN_EXECUTION_FAILED`, etc.
- `cardre/api/dependencies.py` — `require_governance`, `get_project_store`,
  `get_run_coordinator`.
- `cardre/api/routes/` — expand to:
  - `projects.py` — `/projects`, `/projects/{project_id}`
  - `plans.py` — `/projects/{project_id}/plans`,
    `/projects/{project_id}/plans/{plan_id}`,
    `/projects/{project_id}/plans/{plan_id}/versions` (list versions),
    `/projects/{project_id}/plan-versions/{plan_version_id}` (GET, PATCH for
    draft edits, POST to commit). **Plans and plan versions are distinct
    concepts** — do not overload `/plans/{plan_version_id}`.
  - `runs.py` — `/projects/{project_id}/runs`,
    `/projects/{project_id}/runs/{run_id}`,
    `/projects/{project_id}/runs/{run_id}/steps`,
    `/projects/{project_id}/runs/{run_id}/evidence`
  - `artifacts.py` — `/projects/{project_id}/artifacts/{artifact_id}`
  - `evidence.py` — `/projects/{project_id}/steps/{step_id}/evidence`
    (staleness explanation; keyed by step, not run)
  - `manual_binning.py` — already exists from Phase 2; expand if needed.
  - `branches.py` — `/projects/{project_id}/branches`,
    `/projects/{project_id}/branches/{branch_id}` (gated via
    `require_governance`)
  - `comparisons.py` — `/projects/{project_id}/comparisons` (gated)
  - `champion.py` — `/projects/{project_id}/champion` (gated)
  - `exports.py` — `/projects/{project_id}/exports`
  - `reports.py` — `/projects/{project_id}/reports`,
    `/projects/{project_id}/runs/{run_id}/reports`
  - `node_types.py` — `/projects/{project_id}/node-types` (project-scoped)
  - `health.py` — `/health` (the one non-project-scoped route)
- `cardre/api/__init__.py`.
- `sidecar/__main__.py` — 10-line entrypoint:
  `from cardre.api.app import app; uvicorn.run(app, ...)`.

**Frontend (same phase — they move together):**

- `frontend/src/api/client.ts` — copy v1's `fetchJson` + `ApiError` (already
  in place from Phase 2). Update all call sites to project-scoped paths.
- `frontend/src/api/schema.ts` — generated from v2 OpenAPI. No
  `CARDRE_GOVERNANCE=1` hack.
- **No `frontend/src/types.ts`.** Use generated `components` types only.
  This is the "CI fails on drift" the plan wants, achieved by removing the
  second source.
- `frontend/src/hooks/useRunWatch.ts` — port from v1 `useRunProgress.ts`,
  rename, keep the central polling logic. Distinguish the 9 states (sidecar
  unreachable, timeout, malformed JSON, run failed, interrupted, stale,
  stuck, user-cancelled, backend-cancelled).

**Tests:**

- `tests/test_api_projects.py`, `test_api_plans.py`, `test_api_runs.py`,
  `test_api_evidence.py`, `test_api_manual_binning.py`,
  `test_api_branches.py` (with `require_governance` dependency overridden to
  return 403 and 200), `test_api_health.py`.
- `tests/test_api_error_envelope.py` — every error code renders the same
  envelope shape.
- `frontend/src/api/__tests__/client.test.ts` — port from v1 (the robustness
  tests AGENTS.md references: `SIDECAR_UNREACHABLE`, `REQUEST_TIMEOUT`,
  etc.).

**Verification (phase-local):**

```
ruff check --fix
pytest tests/test_api_ -q
cd frontend && npm run typecheck && npm run test -- src/api
```

**DoD:** All routes under `/projects/{project_id}/...`; plans and
plan-versions are distinct route concepts; governance routes always
mounted, 403 when disabled; `frontend/src/types.ts` gone;
`npm run typecheck` green; error envelope consistent across all routes.

**Abort criterion:** if the OpenAPI generator can't produce types for the
project-scoped routes without name collisions (e.g. two `RunResponse`
schemas), the schema generation needs rethinking — stop and unify schemas
before proceeding.

---

### Phase 5 — Launch scorecard pathway + reporting + exports (~5-7 days)

**Wire up the nodes (survived from v1, need v2-compatible contracts):**

- `cardre/nodes/registry.py` — `NodeRegistry`,
  `NodeTier = Literal["launch", "deferred"]`. Port from v1
  `registry.py:1-294`. **Keep `deferred`, do not rename to `experimental`** —
  `deferred` means visible-but-not-executable; `experimental` implies
  executable-but-unstable, which is different semantics. Add `governance`
  and `hidden` tiers only if an actual node needs them; otherwise drop. Do
  not keep enum values for a future that hasn't shown up.
- `cardre/nodes/contracts.py` — `ArtifactContract`, `RolePolicy`,
  `NodeType` (already placed here in Phase 1).
- `cardre/nodes/build/` — port from v1 `nodes/build/` (import, profile,
  split, binning, woe, selection, logistic, scaling). Repoint imports to
  `cardre.domain.*` / `cardre.execution.context`. These are the launch
  nodes.
- `cardre/nodes/validate/` — port from v1 `nodes/validate/` (apply,
  analyse).
- `cardre/nodes/__init__.py` — node registration.

**Build the launch pathway end-to-end:**

- Import → Profile → Validate target → Split train/test/OOT → Fine classing
  → WOE/IV → Variable selection → Manual binning (wired to Phase 2's
  `ManualBinningReview`) → WOE transform → Logistic regression → Score
  scaling → Validation metrics → Cutoff analysis → Audit report → Export
  scoring code.
- No XGBoost, no fairness, no champion/challenger, no advanced governance.
  Those are Phase 6.

**Reporting + exports:**

- `cardre/reporting/` — port from v1 (collectors, renderers, templates,
  readiness checks). Repoint imports.
- `cardre/services/export_service.py` — model development report, run
  manifest, scorecard JSON, Python scoring code, SQL scoring code,
  validation pack, audit evidence bundle. Port from v1 `export_service.py`.
- `cardre/services/report_service.py` — port from v1
  `report_generation_service.py`.

**Tests:**

- `tests/test_launch_pathway.py` — full import-to-export run, asserts
  `evidence_edges` + `evidence_artifacts` rows exist for every step,
  staleness explanation is correct, manifest is complete. **This is the
  running-code schema acceptance test** that Phase 1's paper check
  deferred.
- `tests/test_node_registry_tiers.py` — launch nodes executable,
  deferred nodes not executable in launch mode.
- `tests/test_reporting.py`, `tests/test_exports.py` — port from v1.

**Verification (phase-local):**

```
ruff check --fix
pytest tests/test_launch_pathway.py tests/test_node_registry_tiers.py tests/test_reporting.py tests/test_exports.py -q
```

**DoD:** A full scorecard can be built from import to export via the API;
`evidence_edges`/`evidence_artifacts` rows exist for every step; staleness
explanation renders; audit bundle exports. The two-level evidence schema is
validated against a real run, ~12-16 days in — the deferred Phase 1
acceptance test.

**Abort criterion:** if the launch pathway can't complete a full run with
`evidence_edges`/`evidence_artifacts` rows written for every step, the
executor→resolver→store wiring is wrong. If the schema can't represent
something the real run produces, this is the point to revise the Phase 1
schema (and budget a Phase 1/2 revisit). Stop and fix before Phase 6.

**Decision log:** Phase 5 records the launch pathway shape, the node tier
decisions, and any schema revisions forced by the real run. Phase 6's agent
session reads it first.

---

### Phase 6 — Governance + deferred nodes + final cleanup (~3-4 days)

**Build fresh (porting from v1):**

- `cardre/services/branch_service.py` — port from v1, repoint to v2
  `evidence_edges`/`evidence_artifacts` for branch evidence.
- `cardre/services/comparison_service.py` — port from v1, using the
  relational `comparison_challenger_branches` and
  `comparison_snapshot_plan_versions` tables from Phase 1 (not JSON arrays).
- `cardre/services/champion_service.py` — port from v1.
- `cardre/nodes/{boosting,ensembles,ml_models,tuning,explainability,fairness,reject_inference}.py`
  — port from v1, declare `tier = "deferred"`. These are the deferred ML
  nodes: visible as schemas, not executable in launch mode.
- `cardre/nodes/feature_selection.py` — port (already in v1 as
  `nodes/feature_selection.py`).

**Final cleanup:**

- Delete `tests_v1/` reference directory.
- `grep -r "from cardre.audit\|from cardre.services.run_orchestrator\|CARDRE_GOVERNANCE\|CARDRE_LAUNCH_MODE" tests/`
  — must return zero. Tests use `CardreConfig.from_env()` or
  `monkeypatch.setattr(CardreConfig, "from_env", ...)`. No direct
  `os.environ.get` in tests.
- `grep -r "input_artifact_ids_json\|output_artifact_ids_json" cardre/`
  — must return zero (columns are gone).
- `grep -r "parent_step_ids_json\|challenger_branch_ids_json\|source_plan_version_ids_json" cardre/`
  — must return zero (replaced by relational tables).
- Update `CONTEXT.md` with v2 domain language (five first-class concepts,
  draft/committed plan versions, `evidence_edges`/`evidence_artifacts` as
  the lineage source, two-level evidence model).
- Update `README.md` with v2 architecture diagram.

**Verification (full — this is the merge gate):**

```
ruff check --fix
make preflight
scripts/pr-gate.sh
```

**DoD:** Branch/comparison/champion workflows work against the two-level
evidence tables; deferred ML nodes declare `deferred` tier and are
non-executable in launch mode; `tests_v1/` gone; no test reads env vars
directly; no queryable JSON relationship arrays; full `make preflight`
green; CI green via `pr-gate.sh`; v2 is ready to merge to `main`.

---

## Parallelisation summary

```
Phase 1 (sequential, ~3-4 days) — domain + relational store
  └─ Phase 2 (sequential, ~5-7 days) — manual binning + minimal API/UI spike
      └─ Phase 3 (sequential, ~4-5 days) — execution layer
          └─ Phase 4 (sequential, ~3-4 days) — full API + frontend
              └─ Phase 5 (sequential, ~5-7 days) — launch pathway
                  └─ Phase 6 (sequential, ~3-4 days) — governance + cleanup
```

No parallelism across phases — each depends on the prior's stable
boundaries. Total: ~24-35 days, 6 PRs to `v2`; `v2` merges to `main` at the
end of Phase 6 after full preflight passes.

No intra-phase parallelism: on a fresh v2 branch, the codebase is small
enough that splitting batches costs more in coordination than it saves in
wall-clock time. Each phase is a coherent unit; one agent per phase,
sequentially. Phase 2 may revisit after Phase 3 — budget for it.

## Risks and abort criteria (consolidated)

| Phase | Risk | Abort signal | Mitigation |
|---|---|---|---|
| 1 | `evidence_edges`+`evidence_artifacts` schema can't express multi-artifact-per-parent with per-edge staleness | Paper check fails: can't represent "train reused + test stale from parent Y" as separate edge rows with attached artifacts | Redesign schema before Phase 3 builds on it |
| 1 | Schema not pressure-tested against a real run until Phase 5 (~12-16 days in) | `test_launch_pathway.py` fails on evidence assertions in Phase 5 | Budget a Phase 1/2 schema revisit if Phase 5 forces it |
| 2 | Manual-binning domain model wrong for UI | Spike UI forces revisions to `ManualBinningReview` or `apply_manual_binning_edit` | Revise here, before Phase 3 builds execution on the model |
| 2 | Fixture-inserted evidence doesn't match real run evidence shape | Phase 3/5 integration forces a Phase 2 revisit | Expected outcome, not failure — budget a second pass |
| 3 | Sync/async evidence rows diverge | `evidence_edges`/`evidence_artifacts` rows differ between sync and async runs of same plan | Unify dispatch path before Phase 4 |
| 3 | Per-step evidence persistence fails on partial run | Finalisation failure loses step evidence | Persist evidence inside the run transaction, not at finalisation |
| 4 | OpenAPI type generation collides on project-scoped routes | Generated `schema.ts` has duplicate `RunResponse`-style names | Unify schemas, don't carry forward |
| 5 | Launch pathway can't complete with evidence rows for every step | `test_launch_pathway.py` fails on evidence assertions | Fix executor→resolver→store wiring; revise Phase 1 schema if needed |
| 5 | Agent session drifts from porting discipline into ad hoc rewriting in long phases | Decision log not read; porting line references ignored | Each phase writes a decision log; next phase's agent reads it first |
| 6 | Governance services don't work against two-level evidence | Branch/comparison tests fail | These services were ported — if they fail, the port missed a v1 coupling; fix the port |

## Open questions resolved

1. **Merge `v2` → `main` at the end, or phase-by-phase?**
   **End-of-Phase-6.** No users means no pressure to integrate early; a
   half-built v2 on `main` only adds confusion.

2. **Keep `execution_fingerprint_json` on `run_steps`?**
   **Yes, but renamed in intent.** Keep as execution metadata
   (`node_type`, `node_version`, `params_hash`, `code_version`,
   `library_versions`, runtime warnings, diagnostic payload). Staleness
   and lineage read `evidence_edges`/`evidence_artifacts` + params hashes,
   not this column.

3. **`NodeTier`: drop `governance` and `hidden` if unused?**
   **Yes.** Start with only `launch` and `deferred`. Add `governance` only
   when an actual node needs governance gating (governance features are
   mostly routes/services, not node tiers). Drop `hidden` unless a node
   populates it. Do not keep enum values for a future that hasn't shown up.

4. **`RunCoordinator` vs `RunService` name?**
   **`RunCoordinator`.** Free rename on a fresh branch; the name signals the
   single-owner fix this effort is about.

## What is thrown away from v1

- `cardre/audit.py` (286 lines) — split into `cardre/domain/{artifacts,step,run,diagnostics}.py` + `cardre/execution/context.py` + `cardre/nodes/contracts.py`.
- `cardre/store/project_store.py` (934 lines) — split into
  `cardre/store/{db,project_repo,plan_repo,step_repo,run_repo,run_step_repo,artifact_repo,evidence_repo,branch_repo,manual_binning_repo,comparison_repo}.py`.
- `cardre/services/run_orchestrator.py` (81 lines) — never recreated.
- `cardre/store/project_store.py:78-145` (`run_migrations()`, backfill,
  `_LEGACY_NODE_TYPE_METHOD`, `is_carried_forward` column add) — no
  migration code.
- `cardre/store/schema.py:196-202` (`MIGRATIONS_SQL`) — gone; `store_meta`
  remains as a hard-version-check, not migration.
- `sidecar/main.py:62-67` (conditional router registration) — replaced by
  `Depends(require_governance)`.
- `scripts/generate-openapi-types.py:18`
  (`os.environ["CARDRE_GOVERNANCE"] = "1"` hack) — gone.
- `run_steps.input_artifact_ids_json` / `output_artifact_ids_json` columns —
  gone; `evidence_edges`/`evidence_artifacts` + `artifact_lineage` are the
  only lineage source.
- `plan_steps.parent_step_ids_json` — gone; replaced by `plan_step_edges`
  rows.
- `branch_comparisons.challenger_branch_ids_json` — gone; replaced by
  `comparison_challenger_branches` rows.
- `branch_comparison_snapshots.source_plan_version_ids_json` — gone;
  replaced by `comparison_snapshot_plan_versions` rows.
- `cardre/services/manual_binning_service.py` (694 lines) — split: preview
  logic stays in `manual_binning_service.py`, mutation logic moves to
  `plan_mutation_service.py`.
- `frontend/src/types.ts` (hand-written types coexisting with generated
  `components` types) — gone, generated types only.
- `tests/test_legacy_artifact_compatibility.py` and any
  `test_*_backfill*` — gone, no legacy to test.
- Direct `os.environ.get("CARDRE_GOVERNANCE"|"CARDRE_LAUNCH_MODE", ...)`
  in tests (v1 had at least 6 test files doing this) — gone, route through
  `CardreConfig.from_env()`.

## What is preserved from v1

- **Stack:** Python engine, FastAPI sidecar, React/Tauri desktop shell,
  SQLite metadata, filesystem artifacts.
- **`CardreConfig`** (`config.py:14-44`) — already centralised, copied as-is
  to `cardre/config.py` (not in `domain/`).
- **`EvidenceResolver`** (`evidence_resolver.py:1-219`) — four named
  policies, typed `Diagnostic` emission, fingerprint matching. Ported to
  `cardre/services/evidence_resolver.py`, return type extended to populate
  `EvidenceEdge` + `EvidenceArtifact`.
- **`EvidencePolicyService`** (`services/evidence_policy.py:1-274`) —
  policy single-source-of-truth. Merged into `evidence_resolver.py`.
- **`staleness.py:1-203`** pure functions — ported to
  `cardre/services/staleness_service.py`, repointed to read from
  `evidence_edges`/`evidence_artifacts`.
- **`RunService`** logic (`services/run_service.py:57-411`) — short-circuit,
  placeholder cancellation, sync/async dispatch, stale-run recovery. Ported
  to `cardre/services/run_coordinator.py`, renamed.
- **`run_lifecycle.py:1-484`** — `RunLifecycle` mechanics. Ported to
  `cardre/execution/run_lifecycle.py`.
- **`run_worker.py:1-256`** — `RunWorker`, `RunRequest`, dispatchers. Ported
  to `cardre/execution/worker.py`.
- **`executor.py:1-826`** — `PlanExecutor`. Ported to
  `cardre/execution/executor.py`, repointed to write
  `evidence_edges`/`evidence_artifacts` per-step inside the transaction.
- **`fetchJson<T>` + `ApiError`** (`frontend/src/api/client.ts:1-597`) —
  robust error handling, canonical error code set. Copied verbatim.
- **`useRunProgress`** (`frontend/src/hooks/useRunProgress.ts:39`) — central
  polling hook. Ported, renamed to `useRunWatch`.
- **`artifact_lineage` table + indexes** (`schema.py:182-228`) — correct,
  carried over.
- **Launch/deferred node tiers** — the split is good; `deferred` name kept.
- **Governance gating** — preserved as a capability, implemented via
  dependency injection (403) rather than conditional registration.
- **Physical and logical hashes** — central to the product, carried over.
- **`cardre/nodes/`, `cardre/engine/`, `cardre/modeling/`,
  `cardre/reporting/`, `cardre/_evidence/`, `cardre/readiness/`** — pure
  infrastructure, repoint imports only.

## The main design principle

v1 taught us that Cardre should not be organised around "nodes." Nodes are
plugins.

Cardre v2 is organised around:

- plan mutation (draft vs committed, atomic commands)
- run coordination (one entrypoint, sync/async unified, request fields
  persisted for recovery)
- evidence resolution (first-class two-level tables: `evidence_edges` +
  `evidence_artifacts`, not reconstructed JSON)
- staleness explanation (backend-computed from evidence tables, never
  written onto historical rows, UI-rendered)
- manual review (atomic command, governed review object, downstream
  invalidation by construction via missing evidence for the new draft)
- audit export (evidence trail as the product)

The node system is important, but it is not the architecture. The
architecture is the evidence trail.

---

## Post-merge corrections

The following corrections document what actually happened vs what the plan
above described. History is not rewritten; these notes are additive so the
original text remains auditable.

### Phases 7 and 8 were added post-hoc

The original plan specified 6 phases with a merge gate at the end of Phase 6.
In reality:

- **Phase 7** was added post-hoc (~3 commits) to fix sidecar desktop
  integration gaps: registry-safety health check, finish-run backstop to
  prevent double-finish in background exception handlers, policy/architecture
  doc alignment, and general preflight parity fixes.

- **Phase 8** ("v2 acceptance completion") closes three Phase 3/4 DoD items
  that slipped past the original build:
  - `runs`-table request columns stored as real columns (Batch A).
  - `POST /projects` bootstraps a fresh `.cardre` store from `body.path`
    (Batch B).
  - Full manual-binning lifecycle proven via the API (Batch C).
  - Full scorecard API acceptance test driven through the project-scoped API
    (Batch D) — the headline deliverable.
  - Retroactive decision logs (Batch E, this section).

### Principle 12 (decision logs) was not honored during the original build

The plan says "Each phase's agent session reads a decision log first." In
practice, no logs were written during phases 1–6. This Phase-8 round writes
`docs/plans/v2/decision-logs/phase-{1..8}.md` retroactively. Each log records
observable facts (schema shape, files added, routes wired) from commit
messages and diffs, not speculation about intent.

### Node count: 13 → 15

The original plan's DAG described 13 launch nodes. The actual registry
(`cardre/nodes/registry.py:203-228`) registers 23 launch-tier nodes, of which
15 appear in the scorecard pathway test:

- **Added beyond the original 13:** `DefineModellingMetadataNode` (registering
  modelling metadata as a node) and `FrozenScorecardBundleNode` (bundling the
  final scorecard for export). The original plan's list at Phase 5 omitted
  these even though downstream nodes required them.

The 15-node test DAG in `test_api_scorecard_launch_pathway.py` is the
authoritative list.

### `test_launch_pathway.py` vs `test_api_scorecard_launch_pathway.py`

Two acceptance tests exist and are both kept:

- **`test_launch_pathway.py`** — executor-level smoke test. Fast, tests
  `PlanExecutor` directly. Preserved as a fast red-green cycle for execution
  layer work.
- **`test_api_scorecard_launch_pathway.py`** — API-level acceptance test.
  Drives the full 15-node pathway through `POST /projects`, `POST
  /projects/{id}/runs`, etc. This is the running-code acceptance test the
  original plan's Phase 5 DoD + abort criterion demanded, but driven through
  the project-scoped API.

### `errorCodes.ts` policy

`frontend/src/api/errorCodes.ts` is an accepted **hand-written second source**.
The canonical set lives in `cardre/api/errors.py` (Python). The TypeScript
file mirrors it manually and must be kept in sync by hand until a generator
is added. This is intentionally documented rather than fixed in this round
because the set is small (~21 codes) and changes infrequently.

### Coverage threshold lowered from 75 to 43

The preflight `--cov-fail-under` threshold was lowered from 75 to 43 in
commit `09acda6` ("fix: preflight policy cleanup for v2") on the v2 branch,
before PR 197. The v2 big-bang delete removed ~76k lines of v1 code and
the surviving v2 codebase has a different shape (more nodes/engine code
that requires optional dependencies to cover). The threshold was raised
from 40 to 43 in PR 197's Phase 7 (`3dd60ff`). Current coverage is ~53%.

This is **temporary v2 debt**. The threshold should be raised back toward
75 as the v2 test suite matures. The governance test command also changed
from `pytest -m governance` to `pytest tests/test_api_*.py` — this
*expands* coverage (all governance tests live in `test_api_branches.py`,
which is matched by the glob), so no governance tests were lost.
