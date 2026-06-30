# Phase 7 — Frontend + route verification

**Sprint:** `docs/plans/run-coordination-consolidation-sprint.md`
**Phase goal:** Verify no backend response shape changed and the frontend polling assumptions still hold. No code changes are expected. If anything breaks, it is additive only.

## Files

### Read first (do not edit)
- `sidecar/routes/runs.py` — `run_plan`, `get_project_run`, `get_project_run_steps`, `get_project_run_manifest`. Response mapping uses `RunResponse` (sidecar model) built from `RunService.RunResponse`.
- `sidecar/models.py` — `RunResponse`, `RunDiagnostic`, `RunStepItem`, `RunStepsResponse`.
- `frontend/src/api/client.ts` — `runPlan`, `getProjectRun`, `getProjectRunSteps` (lines ~340-360).
- `frontend/src/api/schema.d.ts` — `RunResponse` shape (lines ~2203-2230).
- `frontend/src/hooks/useRunProgress.ts` — fields consumed: `run_id`, `status`, `heartbeat_at`, `is_stale`, `latest_error`, `step.status`, `step.is_carried_forward`, `step.errors`.
- `frontend/src/components/ProjectView.tsx` — uses `useRunProgress`.

### Do not modify
None expected. This phase is verification-only.

## Tests to run

### Backend response shape

The `RunResponse` Pydantic model in `sidecar/models.py` must still carry:

```
run_id: str
plan_version_id: str
status: str
started_at: str
finished_at: str | None
step_count: int
branch_id: str | None
executed_step_ids: list[str]
diagnostics: list[RunDiagnostic]
latest_error: RunDiagnostic | None
heartbeat_at: str | None
is_stale: bool
```

`RunService._build_response` produces exactly these fields. The route maps
them 1:1. No change expected.

### Frontend tests

```bash
. .venv/bin/activate
cd frontend
npm run test -- src/api src/hooks src/components/__tests__/ProjectView
cd ..
```

The relevant frontend test files:
- `frontend/src/api/__tests__/client.test.ts`
- `frontend/src/components/__tests__/ProjectView.governance.test.tsx`
- `frontend/src/components/__tests__/ProjectView.recovery.test.tsx` (if present)

These must pass unchanged. If one fails, it indicates a backend response
shape change — investigate which field differs. The only sanctioned change is
the branch placeholder now writing a manifest, which does not alter
`RunResponse` (it adds a `run_manifest` artifact, not a response field).

### Backend route + integration tests

```bash
pytest -m "api or regression" -q
```

This catches sidecar route regressions. The `TestSidecarDispatchFailure`
test in `test_run_worker.py` is the canonical route-level dispatch-failure
test; it must still pass.

### Full focused suite

```bash
pytest tests/test_run_worker.py tests/test_run_orchestrator.py \
       tests/test_run_lifecycle.py tests/test_run_coordination_contract.py \
       tests/test_run_diagnostics.py tests/test_branch_consistency.py -q
CARDRE_GOVERNANCE=1 pytest tests/test_run_coordination_contract.py \
       tests/test_run_orchestrator.py tests/test_branch_consistency.py -q
```

## Implementation

None. If a frontend test fails:

1. Read the failure. Identify which `RunResponse` field is missing or
   mis-typed.
2. Check `sidecar/models.py` `RunResponse` and `RunService._build_response`.
3. If a field is missing from `_build_response`, restore it. If a field is
   missing from the sidecar model, restore it. **Do not** change the frontend
   to mask a backend regression.

If a backend integration test fails:

1. Read the failure. The most likely cause is a diagnostic-code assertion that
   changed because the placeholder cancellation message format changed in
   Phase 4.
2. If the assertion is on the exact message string, update the test to match
   the new uniform format from `_cancel_placeholder_run`. If the assertion is
   on the `code` (`RUN_SHORT_CIRCUITED`), it must still pass.

## Verification commands

```bash
. .venv/bin/activate
ruff check --fix
cd frontend && npm run lint && npm run test -- src/api src/hooks src/components/__tests__/ProjectView && cd ..
make preflight
```

`make preflight` is the repo gate (per `AGENTS.md`). It runs the local checks
that routinely fail on PRs, including governance-mode pytest. It must be green
before pushing.

## Definition of done for this phase

- [ ] `sidecar/models.py` `RunResponse` unchanged (same fields).
- [ ] `RunService._build_response` returns the same fields.
- [ ] `npm run test -- src/api src/hooks src/components/__tests__/ProjectView` green.
- [ ] `pytest -m "api or regression" -q` green.
- [ ] Focused backend suite green.
- [ ] `make preflight` green.
- [ ] `ruff check --fix` clean (no changes needed).

## Failure mode

- If a frontend test fails on `is_stale` or `heartbeat_at`: the
  `_build_response` logic for these is unchanged. Re-read
  `_build_response` and `_is_stale` — they must be byte-for-byte as before
  the refactor.
- If `make preflight` fails on governance tests: run
  `CARDRE_GOVERNANCE=1 pytest -m governance -q` and read the failures. The
  branch short-circuit tests must still return the existing run id. If they
  return the placeholder id, the `_execute_existing_running_run` extraction
  in Phase 2 dropped the `if result_id != run_id` check — restore it.

## After this phase

The sprint is functionally complete. Commit any test-only fixes from this
phase. Then proceed to PR creation via `scripts/pr-gate.sh` per `AGENTS.md`:

```bash
scripts/pr-gate.sh
```

Do not use `gh pr create` directly — the PR gate plugin blocks it and
rewrites it to a failed command. The gate pushes, opens/locates the PR, polls
CI until green/red, and on red downloads logs to
`.opencode/pr-gate-logs/<pr-number>/`. Read those logs, fix, push, and re-run
the gate until green.