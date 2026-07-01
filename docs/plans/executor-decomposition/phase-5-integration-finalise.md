# Phase 5: Integration Verification + Line-Count Pass

**Goal:** Confirm the full refactored system is stable. Run every relevant
test suite, the line-count policy, lint, and the governance gate.

## Files

- **No production file edits** in this phase.
- **Read only:** verify `cardre/executor.py`, `cardre/execution/__init__.py`,
  and all test files are consistent.

## Verification Sequence

Run each command and confirm exit 0 before proceeding to the next.

### 1. Targeted unit tests (fast)

```bash
python3 -m pytest tests/test_execution_failure_classification.py -q --tb=short
python3 -m pytest tests/test_execution_validation.py -q --tb=short
python3 -m pytest tests/test_execution_fingerprints.py -q --tb=short
```

Expected: 3 files, all green.

### 2. Characterization tests

```bash
python3 -m pytest tests/test_executor_characterization.py -q --tb=short
```

Expected: 6 tests, all green.

### 3. Existing executor tests

```bash
python3 -m pytest tests/test_executor.py tests/test_executor_error_classification.py tests/test_executor_branch_execution.py -q --tb=short
```

Expected: all green. The `test_structured_error_categories` test must still
assert exactly `"RoleAccessError"` as the category.

### 4. Staleness + manifest + branch + lifecycle tests

```bash
python3 -m pytest tests/test_staleness.py tests/test_manifest.py tests/test_branch_consistency.py tests/test_branch_evidence_unified.py tests/test_run_lifecycle.py tests/test_run_heartbeat_watchdog.py -q --tb=short
```

### 5. Broad keyword filter

```bash
python3 -m pytest tests/ -q --tb=short -k "executor or replay or staleness or leakage or role or manifest or branch or to_node or launch"
```

### 6. Full suite

```bash
python3 -m pytest tests/ -q --tb=short
```

### 7. Line-count policy

```bash
python3 scripts/check-line-counts.py
```

Expected output (no FAIL lines):
- `cardre/executor.py` may show a seam warning if it is between 1000-1400
  (expected ~720, so likely no warning at all).
- No violations.

### 8. Lint

```bash
ruff check
```

### 9. Governance gate

```bash
CARDRE_GOVERNANCE=1 python3 -m pytest -m governance -q --tb=short --no-cov
```

### 10. Preflight

```bash
make preflight
```

## Troubleshooting Common Failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `ImportError: cannot import name 'RoleAccessError' from 'cardre.executor'` | `cardre/__init__.py` import chain broken | Verify `executor.py` has `from cardre.execution.validation import RoleAccessError` at top level |
| `ImportError: cannot import name 'leakage_protection'` (or similar) | Renamed function still referenced | Check `executor.py` for stale method calls; use grepping |
| `AttributeError: 'PlanExecutor' object has no attribute '_filter_inputs_by_role'` | Wrapper not added to class | Add the compatibility wrapper (see Phase 3) |
| `tests/test_executor.py::test_structured_error_categories` fails with `assert error["category"] == "RoleAccessError"` | `_CATEGORY_MAP` order changed or `RoleAccessError` not in map | Verify `failure_classification.py`'s `_CATEGORY_MAP` includes `(RoleAccessError, "RoleAccessError")` |
| `tests/test_staleness.py` fails — hash mismatch | Fingerprint key missing or renamed | Check `build_execution_fingerprint` produces all keys staleness expects |
| `ruff check` fails | Unused imports or trailing whitespace | `ruff check --fix` |

## Final Commit

```bash
git add cardre/execution/ cardre/executor.py tests/test_execution_*.py tests/test_executor_characterization.py
git commit -m "feat(exec-decomp): extract failure classification, validation, fingerprint helpers

- classify_step_failure in cardre/execution/failure_classification.py
- RoleAccessError/LeakageProtectionError + validation in validation.py
- build_execution_fingerprint in fingerprints.py
- PlanExecutor retains orchestration + compat wrappers
- 3 new focused test modules + 6 characterization tests
- All existing tests pass unchanged"
```

## Push and PR Gate

```bash
scripts/pr-gate.sh --base main
```

Follow the PR gate instructions in `AGENTS.md`. If CI is red, read logs
from `.opencode/pr-gate-logs/<pr-number>/`, fix, push, rerun gate.

## Definition Of Done

- [ ] All verification commands exit 0.
- [ ] `scripts/check-line-counts.py` passes (no FAIL lines).
- [ ] `ruff check` is clean.
- [ ] `make preflight` is green.
- [ ] PR raised via `scripts/pr-gate.sh` with green CI.
- [ ] Follow-up issues identified (see below).

## Follow-Up Refactors (Not Done In This Sprint)

1. **Extract `_StepAction`** to `cardre/execution/action_plan.py` once
   `tests/test_branch_consistency.py` is updated (or re-export is accepted).
2. **Centralise `CARDRE_VERSION`** into `cardre/_version.py` consumed by
   both `fingerprints.py` and `run_lifecycle.py`.
3. **Extract `_resolve_inputs`** into an evidence-resolution service
   alongside `cardre/evidence_locator.py`.
4. **Extract `_record_run_step` into a `RunStepRecorder`** once
   `test_branch_consistency.py` monkeypatching is migrated to a seam interface.
5. **Make `failure_classification` pluggable** by accepting a registry of
   exception->category mappings so plugins can extend classification.
