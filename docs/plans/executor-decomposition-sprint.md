# Executor Decomposition Sprint

Resolve the main architectural seam in Cardre: `PlanExecutor` owns too many
responsibilities (failure classification, fingerprint construction, role
validation, leakage protection, artifact file validation) inline alongside
orchestration. The goal is **not** to split arbitrarily — the goal is the
safest behaviour-preserving decomposition that reduces change-risk.

## The Problem In One Sentence

`PlanExecutor` (~970 lines, architectural seam at threshold 1400) handles
plan topology, run-mode orchestration, step action planning, node
instantiation, parameter validation, parent artifact resolution, role
filtering, role access validation, leakage protection, artifact file/hash
validation, heartbeat watchdogs, node execution, fingerprint construction,
failure classification, run-step recording, replay mechanics, and
carry-forward — making it the highest-risk file to modify in the codebase.

## Target Architecture

```
cardre/
  executor.py                     # thinner: orchestration + compat wrappers
  execution/
    __init__.py                   # package marker + re-exports
    failure_classification.py     # A1: classify_step_failure
    fingerprints.py               # A2: build_execution_fingerprint
    validation.py                 # A3: role + leakage + artifact validation
```

- `PlanExecutor` retains orchestration (`run_plan_version`, `run_branch`,
  `run_to_node`, `replay_from_step`, `_execute_actions`, `_execute_step`,
  `_record_run_step`, `_reuse_run_step`, `_HeartbeatWatchdog`,
  `validate_plan_executability`).
- `execution/failure_classification.py` owns the `_CATEGORY_MAP` / `_CODE_MAP`
  mapping and `classify_step_failure()` — pure function, no store.
- `execution/fingerprints.py` owns `build_execution_fingerprint()` and the
  helper functions for parent-output hashes — pure data construction.
- `execution/validation.py` owns role filtering, role-access validation,
  leakage protection, and artifact file/hash validation — plus the
  `RoleAccessError` and `LeakageProtectionError` exception classes moved
  here to break a circular import.

## Design Principles

- **Minimum viable extraction.** Within each extraction target, extract the
  smallest coherent set of pure functions. _CATEGORY_MAP + _CODE_MAP are
  extracted together because they must stay in sync.
- **Characterization tests first.** Every behaviour change is locked by a
  test before the refactor. TDD: RED first, GREEN second.
- **Backward compatibility.** `PlanExecutor._validate_input_artifact_files`,
  `_filter_inputs_by_role`, etc. remain as compatibility wrappers that
  delegate to the extracted functions. Direct test calls (`test_executor.py:263`)
  keep working.
- **Public API unchanged.** `PlanExecutor`, `RoleAccessError` remain
  importable from `cardre.executor` and `cardre`.
- **No dependency-injection framework.** Regular function calls.
- **One PR at the end**, raised via `scripts/pr-gate.sh` per `AGENTS.md`.

## Pre-Requisites (must hold before Phase 1)

- `make preflight` passes on `main`.
- The venv is bootstrapped: `. .venv/bin/activate && pip install -e ".[sidecar,dev,test]"`.
- Branch `feat/executor-decomposition` exists off `main`.
- Governance tests can run: `CARDRE_GOVERNANCE=1 pytest -m governance -q` is green on `main`.

## Phase Sequence

| Phase | Title | Depends on | Behaviour change? |
|-------|-------|------------|-------------------|
| 1 | Characterization contract tests (RED) | — | No (tests only) |
| 2 | Extract failure classification | 1 | No (extract + wrapper) |
| 3 | Extract validation (role + leakage + artifact) | 2 | **Yes** — moves exception classes to break cycle |
| 4 | Extract fingerprint construction | 3 | No (extract + wrapper) |
| 5 | Integration verification + line-count pass | 4 | No (validation only) |

Each phase has a dedicated document in `docs/plans/executor-decomposition/`:
- `phase-1-characterization-tests.md`
- `phase-2-failure-classification.md`
- `phase-3-validation.md`
- `phase-4-fingerprints.md`
- `phase-5-integration-finalise.md`

## Definition Of Done

The sprint is resolved only when **all** of the following hold:

- [ ] 6 characterization tests in `tests/test_executor_characterization.py`
      pass both before and after the refactor.
- [ ] `classify_step_failure()` lives in `cardre/execution/failure_classification.py`
      with focused unit tests in `tests/test_execution_failure_classification.py`.
- [ ] `build_execution_fingerprint()`, `output_logical_hashes()`,
      `build_parent_output_hashes()` live in `cardre/execution/fingerprints.py`
      with focused unit tests in `tests/test_execution_fingerprints.py`.
- [ ] `filter_inputs_by_role()`, `validate_role_access()`,
      `validate_node_input_roles()`, `validate_leakage_rules()`,
      `validate_input_artifact_files()`, `RoleAccessError`,
      `LeakageProtectionError`, `LEAKAGE_SENSITIVE_CATEGORIES` live in
      `cardre/execution/validation.py` with focused unit tests in
      `tests/test_execution_validation.py`.
- [ ] `PlanExecutor` compatibility wrappers exist for any private method
      that tests call directly.
- [ ] `cardre/__init__.py` still exports `PlanExecutor` and `RoleAccessError`
      from `cardre.executor`.
- [ ] Existing executor/branch/replay/staleness/manifest tests all pass
      without modification.
- [ ] `ErrorScenario` matrix in `tests/test_executor_error_classification.py`
      still passes — diagnostic codes unchanged.
- [ ] `scripts/check-line-counts.py` passes (executor drops from ~970 to
      ~720 lines; new files each well under 1000).
- [ ] `ruff check` clean.
- [ ] `make preflight` green.
- [ ] PR raised via `scripts/pr-gate.sh` and CI green.

## Out Of Scope (Deliberate)

- Moving `_StepAction` dataclass to `execution/action_plan.py`.
- Moving `_HeartbeatWatchdog` out of `PlanExecutor`.
- Moving `_resolve_inputs` (parent artifact resolution) — seam trigger says
  future evidence service.
- Moving `_record_run_step` or `_reuse_run_step`.
- Moving `STATUS_*` constants out of `executor.py`.
- Rewriting `ProjectStore` or changing any store method.
- Changing `RunLifecycle` or manifest writer / schema.
- Changing staleness semantics (`cardre/staleness.py`).
- Changing branch evidence fallback policy (`services/evidence_policy.py`).
- Changing node type names, registry, or availability tier policy.
- Changing `cardre_version` literal or manifest schema.
- Introducing a dependency-injection framework.
- Changing public API routes or response shapes.

## Risks

1. **Circular import:** `failure_classification.py` needs to import
   `RoleAccessError` and `LeakageProtectionError`, which are defined in
   `executor.py`. The plan moves the exception classes to `validation.py`
   to break the cycle. If something breaks, fall back to lazy imports inside
   the function body.
2. **Test patch churn.** Sixteen test files import `PlanExecutor` directly.
   None should need rewriting (the class is unchanged), but the import
   verification in Phase 5 is essential.
3. **`_validate_input_artifact_files` is called directly by tests**
   (`tests/test_executor.py:263,276`). The wrapper must stay on
   `PlanExecutor` or those tests break.
4. **`_StepAction` is imported by tests** (`tests/test_branch_consistency.py:472,512`).
   Out of scope for this sprint — it stays in `executor.py`.

## How To Run This Sprint

Each phase document is self-contained and follows the same structure:

1. **Goal** — one sentence.
2. **Files** — exact files to read, modify, create.
3. **Tests to write first (RED)** — concrete test names + assertions.
4. **Implementation** — the minimal change to pass tests.
5. **Verification commands** — exact shell commands to run.
6. **Definition of done for this phase** — checkbox list.
7. **Failure mode** — what to do if tests fail unexpectedly.

Run one phase at a time, in order. After each phase, commit with
`feat(exec-decomp-N): <title>`. Do **not** push or open a PR until
Phase 5 is complete. At the end, run `scripts/pr-gate.sh` per `AGENTS.md`.

## Reference: Current Responsibilities of PlanExecutor

| # | Responsibility | Lines |
|---|---|---|
| R1 | `validate_plan_executability` (availability gate) | 136-162 |
| R2 | `run_plan_version` orchestration | 168-195 |
| R3 | `run_branch` orchestration | 197-258 |
| R4 | `run_to_node` orchestration | 260-327 |
| R5 | `_build_branch_actions`, `_build_to_node_actions` (action planning) | 333-368 |
| R6 | `_execute_actions` main loop | 374-451 |
| R7 | `_compute_final_status` | 453-463 |
| R8 | `_execute_step` (node instantiation, validation, run, error handling) | 469-628 |
| R9 | `_resolve_inputs` (parent artifact resolution) | 630-646 |
| R10 | `_validate_topology` (delegates to `topology.py`) | 648-649 |
| R11 | `_filter_inputs_by_role` | 655-663 |
| R12 | `_validate_role_access` | 665-692 |
| R13 | `_validate_node_input_roles` | 694-713 |
| R14 | `validate_leakage_rules` | 715-731 |
| R15 | `_build_execution_fingerprint` | 737-757 |
| R16 | `_validate_input_artifact_files` | 759-776 |
| R17 | `_record_run_step` | 782-809 |
| R18 | `replay_from_step` | 815-887 |
| R19 | `_reuse_run_step` (carry-forward) | 893-944 |
| R20 | `_HeartbeatWatchdog` (inner class) | 52-107 |
| R21 | Module constants (`STATUS_*`, `LEAKAGE_SENSITIVE_CATEGORIES`) | 110-116 |
| R22 | `RoleAccessError`, `LeakageProtectionError` exception classes | 947-957 |
| R23 | `_output_logical_hashes`, `_build_parent_output_hashes` (module fns) | 960-970 |

**Extracted in this sprint:** R11-R16, R22 (moved), R23, plus the inline
failure-classification block in R8.
