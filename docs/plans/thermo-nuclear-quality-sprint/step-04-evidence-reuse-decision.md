# PR4 — Decide evidence reuse: delete or implement

**Findings:** T3, K1
**Batch:** B (parallel with PR1)
**Depends on:** PR0 (safety net), **product decision required**
**Behaviour change:** Decision required (see below)

## Prerequisite: product decision

Before any code is written for PR4, a product decision must be recorded in
`docs/plans/thermo-nuclear-quality-sprint/reuse-decision.md`:

**Option A: reuse is not part of launch.** Delete the unreachable paths,
remove or rewrite tests/docs/ADRs that imply support, and make unsupported
behaviour impossible to call.

**Option B: reuse is part of near-term branch semantics.** Do not delete.
Instead, make the planner actually emit `reuse`/`skip`, add integration
tests, and make failure modes explicit.

The decision must be made before opening the PR. The instructions below
cover Option A (deletion, the recommended default). If Option B is chosen,
do not follow these instructions — instead, wire the planner + executor +
tests and update the docs to match.

## Goal (Option A: delete dead reuse subsystem)

Delete the ~600 LOC of evidence-reuse machinery that is unreachable from
production. `ExecutionActionPlanner` only ever emits `action="execute"`;
the `"reuse"`/`"skip"` branches, `EvidenceResolver`, `BranchRunEvidence`,
and the `precomputed_*` parameters are dead. Then merge
`EvidenceLocator` and the surviving `EvidencePolicyService.check_branch_current`
into a single locator (K1).

## Tasks

### T3 — Delete dead reuse subsystem

1. In `cardre/execution/action_planner.py`:
   - Confirm `_StepAction.action` is only ever `"execute"` in production
     (grep for `action="reuse"`, `action="skip"` — only tests construct
     these).
   - Remove `evidence_source`, `before_execute`, and any reuse-specific
     fields from `_StepAction`. The action enum collapses to a single mode.
2. In `cardre/execution/executor.py`:
   - Delete the `if action.action == "reuse":` branch (lines 228-264).
   - Delete `_reuse_run_step` (lines 422-498).
   - Delete the `precomputed_outputs`/`precomputed_records` parameters
     from `run_plan_version`/`_execute_actions` (lines 164-165, 212-213,
     219-220).
   - Delete the dead `run_to_node` method (lines 177-199) — only tests
     call it.
   - Simplify `_execute_actions` to a flat loop.
3. In `cardre/execution/run_step_writer.py`:
   - Delete `write_reused_run_step` (lines 178-285).
4. In `cardre/services/evidence_resolver.py`:
   - Delete `EvidenceResolver` (the entire class, ~165 LOC).
   - Delete `EvidencePolicyService.prepare_branch_evidence`,
     `resolve_parent_evidence`, `check_to_node_current`.
   - Delete `BranchRunEvidence`, `ShortCircuitResult`.
   - Keep `EvidencePolicyService.check_branch_current` ONLY (live for the
     short-circuit decision in `run_coordinator._plan_decision`), or fold
     it into `StalenessService` (see K1).
5. Remove the dead `step_map = []` and unused `branch_id` parameter from
   any surviving code.

### Test triage (NOT blanket deletion)

1. Grep the 4 test files for reuse-specific assertions:
   - `tests/test_evidence_resolver.py` (254 LOC, 19 reuse refs)
   - `tests/test_evidence_resolver_edge_cases.py` (235 LOC, 24 refs)
   - `tests/test_run_step_writer.py` (6 refs)
   - `tests/test_executor_characterization.py` (4 refs)
2. For each test:
   - If it tests deleted behaviour (e.g. `EvidenceResolver.resolve` with
     policies, `write_reused_run_step`, `action="reuse"`): **delete the
     test** with a commit message referencing T3.
   - If it tests live behaviour that happens to import a deleted name:
     **rewrite** to use the surviving API.
   - If it's unclear: **mark with `# review-013-T3: dead code, removal
     pending` and leave for triage** — do not keep it alive silently.
3. Do not leave tests in a halfway state. Each test is either deleted,
   rewritten, or explicitly marked pending.

### Doc / ADR update

1. Update `docs/adr/0004-single-run-lifecycle-atomic-finalisation.md` —
   if it describes branch evidence reuse, add a note that reuse was
   removed (or was never implemented) and the ADR is historical.
2. Update `docs/adr/0005-canonical-evidence-resolution-contract.md` —
   same.
3. Update `docs/adr/0013-evidence-locator-implementation.md` — same.
4. Update `docs/architecture/execution-and-staleness.md` — remove any
   description of the reuse/skip action paths; describe the execute-only
   flow.
5. Add a note to `docs/plans/branch-evidence-policy-unification.md`
   pointing to `reuse-decision.md`.

### K1 — Merge `EvidenceLocator` + `EvidenceResolver`

1. After the deletions above, `cardre/services/evidence_resolver.py` is
   down to just `check_branch_current` (if kept). Fold this into
   `cardre/evidence_locator.py` (or `StalenessService`).
2. Delete the duplicated `_plan_id_for_version` in
   `cardre/services/evidence_resolver.py:230-235`.
3. Update `cardre/services/run_coordinator.py:_plan_decision` to call the
   new location.
4. If `evidence_resolver.py` is now empty or a thin shim, delete it.
5. Update `cardre/services/__init__.py` and any imports.

## Acceptance criteria

- [ ] `reuse-decision.md` exists and records the decision (Option A or B).
- [ ] `rg 'EvidenceResolver' cardre --type py` returns 0 (class gone).
- [ ] `rg 'BranchRunEvidence|ShortCircuitResult|prepare_branch_evidence|
  resolve_parent_evidence|check_to_node_current' cardre --type py`
  returns 0.
- [ ] `rg 'write_reused_run_step|_reuse_run_step' cardre --type py`
  returns 0.
- [ ] `rg 'precomputed_outputs|precomputed_records' cardre --type py`
  returns 0.
- [ ] `rg 'action="reuse"|action="skip"' cardre --type py` returns 0.
- [ ] `ExecutionActionPlanner` only emits `"execute"`.
- [ ] `cardre/services/evidence_resolver.py` deleted or reduced to a
  thin shim.
- [ ] Tests triaged: deleted, rewritten, or explicitly marked pending.
  No tests left in a halfway state.
- [ ] ADRs 0004, 0005, 0013 updated.
- [ ] `docs/architecture/execution-and-staleness.md` updated.
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] `scripts/audit_quality.py --json` shows reuse-subsystem references
  at 0.

## Do not

- Do not delete tests without triage. Each test must be explicitly
  deleted, rewritten, or marked pending.
- Do not touch `executor.py`'s `branch_id` resolution or `_json_ready`
  (those are PR1 and PR8). You only delete the dead reuse/`run_to_node`/
  `precomputed_*` surface.
- Do not touch `run_coordinator.py`'s stale-recovery logic (that's PR8).