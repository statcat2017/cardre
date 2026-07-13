# PR4 Reuse Decision

## Decision: Option A

Reuse is not part of launch.

PR4 will delete the unreachable evidence-reuse subsystem, including
`EvidenceResolver`, and make the unsupported paths impossible to call.

## Architectural stance

`cardre/services/evidence_resolver.py` should be fully erased, not kept as a
shim.

Why:

- It is a recent module, introduced on `2026-07-02`, so there is no meaningful
  long-tail compatibility burden.
- It is a fake boundary: most of its surface duplicates or wraps logic that
  already belongs in `cardre/evidence_locator.py`.
- Its public names imply support for reuse, branch evidence preparation, and
  `to_node` execution that the product does not actually launch.
- Keeping a compatibility shim would preserve exactly the ambiguity PR4 is meant
  to remove.

This does not weaken the repo. It strengthens it by collapsing evidence lookup
back onto one real seam.

## Target architecture after PR4

- `EvidenceLocator` is the single evidence-read primitive.
- `RunCoordinator` does not own evidence policy logic directly.
- The only surviving short-circuit check is a small branch-current check exposed
  from the locator-side seam.
- No production code path refers to `EvidenceResolver`, `BranchRunEvidence`,
  `ShortCircuitResult`, reuse actions, or `run_to_node` execution.

The preferred minimal shape is:

```python
@dataclass
class EvidenceCheckResult:
    status: Literal["current", "stale", "missing", "error"]
    run_id: str | None = None
    diagnostics: list[Any] = field(default_factory=list)


class EvidenceLocator:
    def check_branch_current(
        self,
        plan_version_id: str,
        branch_id: str,
    ) -> EvidenceCheckResult: ...
```

If that feels too awkward inside `evidence_locator.py`, a tiny adjacent module is
acceptable, but `evidence_resolver.py` itself should not survive.

## Outcome contract

When PR4 is complete:

1. `cardre/services/evidence_resolver.py` no longer exists.
2. `ExecutionActionPlanner` only models `"execute"` actions.
3. `PlanExecutor` has no `run_to_node`, `_reuse_run_step`, or
   `precomputed_outputs` / `precomputed_records` surface.
4. `run_step_writer.py` exposes only `write_run_step`.
5. `RunCoordinator` imports the surviving branch-current check from the new
   location, not from a resolver shim.
6. Tests that exercised dead reuse behaviour are deleted or rewritten; none are
   left silently preserving dead concepts.
7. Docs and ADRs describe execute-only launch semantics honestly.

## Execution plan

### Phase 1: Delete dead executor planning and persistence paths

- In `cardre/execution/action_planner.py`, collapse `_StepAction.action` to
  `"execute"` only.
- Delete `_StepAction.evidence_source` and `before_execute`.
- Delete `plan_to_node()`.
- In `cardre/execution/executor.py`, delete `run_to_node`, the reuse/skip
  branches in `_execute_actions`, `_reuse_run_step`, and the
  `precomputed_outputs` / `precomputed_records` parameters.
- In `cardre/execution/run_step_writer.py`, delete `write_reused_run_step`.

### Phase 2: Erase `EvidenceResolver`

- Move `EvidenceCheckResult` and the surviving branch-current check to the
  locator-side seam.
- Delete `EvidenceResolver`, `BranchRunEvidence`, `ShortCircuitResult`,
  `prepare_branch_evidence`, `resolve_parent_evidence`, and
  `check_to_node_current`.
- Update `cardre/services/__init__.py` exports.
- Update `cardre/services/run_coordinator.py` imports and call sites.

### Phase 3: Test triage

- Delete `tests/test_evidence_resolver.py`.
- Delete reuse and `to_node` tests in:
  - `tests/test_evidence_resolver_edge_cases.py`
  - `tests/test_run_step_writer.py`
  - `tests/test_executor_characterization.py`
  - `tests/test_action_planning.py`
- Rewrite tests that still cover live branch-current behaviour:
  - `tests/test_evidence_policy.py`
  - `tests/test_run_coordinator.py`

### Phase 4: Documentation honesty pass

- Update:
  - `docs/adr/0004-single-run-lifecycle-atomic-finalisation.md`
  - `docs/adr/0005-canonical-evidence-resolution-contract.md`
  - `docs/adr/0013-evidence-locator-implementation.md`
  - `docs/architecture/execution-and-staleness.md`
  - `docs/plans/branch-evidence-policy-unification.md`
  - `README.md`

Historical docs may still mention old ideas, but active architecture docs must
not present reuse as a live capability.

### Phase 5: Verification

- `rg 'EvidenceResolver|BranchRunEvidence|ShortCircuitResult|prepare_branch_evidence|resolve_parent_evidence|check_to_node_current' cardre --type py`
- `rg 'write_reused_run_step|_reuse_run_step|precomputed_outputs|precomputed_records' cardre --type py`
- `rg 'action="reuse"|action="skip"' cardre --type py`
- `python scripts/audit_quality.py --json`
- `ruff check`
- `pytest tests/ -q`

All grep checks above must return zero matches in product code.

## Non-goals

- Do not clean up `runs.run_scope`, `target_step_id`, or evidence provenance
  schema fields in PR4. They are broader than the dead reuse deletion and may
  still be used by rejection paths, manifests, or historical data.
- Do not inline branch-current logic into `RunCoordinator`.
- Do not add a backward-compatibility shim for `evidence_resolver.py`.
