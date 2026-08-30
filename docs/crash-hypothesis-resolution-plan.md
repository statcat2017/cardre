# Crash Hypothesis Resolution Plan

## Status

Implemented. This document records the TDD resolution work; the remaining 45
unverified rows still need environment, resource-scale, browser/Tauri, or
cross-version testing before they become defect claims.

## Evidence and scope

The initial 100-probe evaluation produced 14 real-defect rows, 41 mitigated
rows, and 45 unverified rows. After the TDD slices, the final report produces
0 real-defect rows, 55 mitigated rows, and 45 unverified rows. The initial 14
rows were not 14 independent root causes. The report uses static evidence for
some rows, so a real-defect row can mean a reachable unsafe path rather than a
reproduced process crash.

The mitigated and unverified rows are not in this fix scope. Unverified rows
need an OS race, external process, resource-scale workload, browser/Tauri run,
or cross-version setup before they become a defect claim.

## TDD rules

1. Work in vertical slices. For each slice, write one behavior-level RED test,
   make the smallest GREEN change, then refactor only after the test passes.
2. Test through the existing public Module Interfaces. Use real SQLite and
   filesystem Adapters for persistence behavior; use small fakes only at
   existing Seams where the test needs controlled failure.
3. Preserve the Project, Plan Version, Run, Step, Artifact, and Evidence
   vocabulary. Do not make a source-text assertion the only proof of a
   behavior that can be exercised at runtime.
4. Keep each fixed defect as a regression test after refactoring. Run the
   relevant focused suite after every GREEN step, then run the full gates.

## Recommended order

### Slice 1: Reconciliation reports Project failures

**Rows:** #8 and #9
**Modules:** `application/runs/reconcile_publications.py`,
`application/runs/reconcile_dispatches.py`

**RED:** inject a read-only UnitOfWork whose pending-row read raises for one
Project, while a second Project has valid pending work. Assert that startup
reconciliation continues to the second Project and returns an observable
failed result or diagnostic for the first. Also assert that the failure does
not falsely claim the pending row was published or dispatched.

**GREEN:** preserve per-Project startup isolation, but replace the silent
`except Exception: continue` path with a recorded failure outcome and
structured logging. Keep publication and dispatch row-level failures isolated
as they are today.

**REFACTOR:** share only the error-recording behavior if both Modules still
duplicate it. Do not introduce a general-purpose error Module for two small
call sites.

**Verification:**

- `tests/application/runs/test_publication_durability.py`
- `tests/application/runs/test_durable_dispatch.py`
- new reconciliation failure tests beside those files

### Slice 2: Normalize unexpected HTTP failures

**Rows:** #20
**Module:** `cardre/api/app.py`

**RED:** register a test-only route that raises an ordinary `ValueError` and
call it through the application. Assert a structured 500 response, no HTML
body, and no raw traceback or sensitive exception detail in the response.
Assert that the exception is still logged with its traceback.

**GREEN:** add one application-level handler for unexpected exceptions. Map it
to the existing closed error vocabulary or add a deliberately documented
internal code only if the current vocabulary cannot represent the behavior.
Update the generated TypeScript error contract if a public code is added.

**REFACTOR:** keep domain-error translation and unexpected-error handling
separate. Do not add route-level `try`/`except` ladders.

**Verification:**

- `tests/application/api/test_error_code_translation.py`
- `tests/application/api/test_api_surface.py`
- new unexpected-exception handler test
- `python3 scripts/generate-error-codes.py` and its drift check if needed

### Slice 3: Give stale Runs an independent recovery trigger

**Rows:** #41
**Modules:** `application/runs/submit_run.py`,
`application/execution/heartbeat.py`, application bootstrap/lifespan

**RED:** create a running Run with an old heartbeat and no later Run
submission. Advance an injected Clock, invoke the recovery trigger, and assert
that the Run becomes `interrupted`, receives its stale diagnostic, and gets the
normal manifest/outbox treatment. Assert that a recent heartbeat is untouched.

**GREEN:** move stale-Run recovery behind an explicit periodically invoked
Module and start it from the process lifecycle, or add the recovery operation
to the existing watchdog while keeping heartbeat renewal and stale recovery
distinct. Use the existing `ClockPort`; no direct wall-clock read is allowed
in the new path.

**REFACTOR:** make shutdown stop and join the recovery thread. Keep the
compare-and-set on the observed heartbeat so recovery cannot interrupt a Run
that renewed its lease.

**Verification:**

- `tests/application/runs/test_run_submission_contract.py`
- `tests/application/runs/test_finalize_run_manifest.py`
- new stale recovery lifecycle tests

### Slice 4: Make heartbeat and lease loss terminally safe

**Rows:** #43 and #47
**Modules:** `application/execution/heartbeat.py`,
`application/runs/execute_run.py`, `application/runs/finalize_run.py`

**RED:**

- force one heartbeat write to fail and assert that the Run does not silently
  remain healthy without a recovery signal; after the defined retry policy,
  assert a deterministic terminal outcome and diagnostic;
- inject a non-cancellation `LeaseLost` while the Run remains `running` and
  assert it cannot return from execution leaving the Run permanently running.

**GREEN:** define the smallest lifecycle policy: bounded heartbeat retry,
observable persistent-heartbeat failure, and one race-safe terminalization
path for a lost lease. A lost lease must not overwrite a Run already
terminalized by another owner. The selected terminal status and diagnostic
code must be fixed in the test before implementation.

**REFACTOR:** consolidate terminalization through the existing finalization
Module. Preserve lease generation and cancellation compare-and-set behavior.

**Verification:**

- `tests/application/runs/test_dispatch_fencing_concurrency.py`
- `tests/application/runs/test_run_submission_contract.py`
- new heartbeat-failure and non-cancellation-lease-loss tests

### Slice 5: Remove misleading dispatcher status

**Rows:** #50
**Module:** `adapters/dispatch/thread_dispatcher.py`

**Triage before RED:** current contract tests explicitly expect an unknown
Run ID to return `completed`. This is therefore a contract defect candidate,
not an unconditional fix.

**RED:** first write the desired behavior: an unknown Run must be distinguishable
from a completed Run. Assert the new result through the dispatcher port and
through the caller, if a production caller exists.

**GREEN:** either return an explicit unknown status or remove this in-memory
status query when durable Run state is the authoritative source. Update
`tests/ports/test_run_dispatcher_contract.py` and adapter tests together.

**REFACTOR:** avoid making the dispatcher query SQLite. Keep durable Run state
in the Run Modules and in-memory execution state in the dispatcher.

### Slice 6: Resolve the Run summary identity question

**Rows:** #60
**Module:** `application/runs/execute_run.py`

**Triage before RED:** a Run summary is run-level Evidence, not necessarily a
Step. The empty `run_step_id` may be intentional. Inspect its readers and the
SQLite constraints before changing it.

**RED:** add a round-trip test that publishes a Run summary and reads it through
the Evidence reader. Assert whether the empty Step identifier is accepted as
run-level Evidence or whether a dedicated identity is required. Do not assert
against the literal `run_step_id=""`.

**GREEN:** only change persistence if the round-trip test proves a consumer
cannot distinguish Run summary Evidence from Step Evidence. Otherwise mark
#60 as mitigated and remove it from the fix queue.

### Slice 7: Make sampling and split allocation explicit

**Rows:** #62 and #63
**Modules:** `nodes/prep/import_.py`, `nodes/prep/split.py`

**RED:**

- import a deterministic Parquet fixture with a known ordering and assert the
  documented `max_rows` behavior, including whether it is sampling or a head
  limit;
- run the stratified splitter with one-row target groups and assert either a
  valid three-role allocation or a typed validation failure before any empty
  role is published.

**GREEN:** choose and document one policy. Recommended: retain `max_rows` as a
head limit only if it is explicitly named as such; otherwise add a deterministic
seeded sampling policy. For splitting, fail clearly when the requested roles
cannot be populated rather than publishing empty test/OOT Artifacts.

**REFACTOR:** keep allocation arithmetic pure and test it with a table of
small group sizes. Keep the node test focused on publication behavior.

**Verification:**

- node tests under `tests/nodes/`
- `tests/acceptance/test_launch_pathway.py`
- the canonical composed execution test

### Slice 8: Reject incomplete scorecard definitions

**Rows:** #68
**Module:** `nodes/build/models.py`

**RED:** provide a model Artifact whose coefficient set does not contain the
WOE feature required by a bin definition. Assert that scorecard publication
fails with a typed, actionable error and produces no partial scorecard.

**GREEN:** replace silent `continue` behavior with validation before building
the scorecard. The error must name the variable and distinguish an unused
selection from a malformed model Artifact.

**REFACTOR:** centralize the feature-contract check so model fitting and score
scaling cannot disagree about feature names. Preserve the strict model
Artifact format.

**Verification:**

- `tests/test_logistic_regression_known_input.py`
- `tests/nodes/test_score_scaling_known_input.py`
- new scorecard feature-contract regression test

### Slice 9: Do not hide corrupt Parquet behind a non-match

**Rows:** #76
**Module:** `adapters/evidence/parsers.py`

**RED:** give the Evidence reader a corrupt Parquet Artifact and a valid
candidate of the same broad kind. Assert that the reader returns a typed parse
failure for the corrupt Artifact instead of silently selecting the valid
candidate as if the corrupt Artifact were merely ineligible.

**GREEN:** distinguish “candidate does not have the required columns” from
“candidate cannot be read.” Preserve fallback for a valid, schema-incompatible
Artifact; surface an Evidence parse error for unreadable bytes.

**REFACTOR:** keep the distinction in the Evidence Adapter and add focused
tests for missing files, corrupt files, and valid schema mismatch.

**Verification:**

- `tests/test_evidence_adapters.py`
- `tests/application/evidence/test_resolve_evidence.py`
- new corrupt-Parquet reader test

### Slice 10: Convert malformed report data into controlled failure

**Rows:** #89 and #90
**Module:** `adapters/rendering/html_report.py`

**RED:** call the renderer with missing `pathway.steps` and missing
`validation.metrics_by_role`. Assert a typed report-data error or a rendered
diagnostic document, never a raw `KeyError`.

**GREEN:** validate the ReportBundle before rendering, or use one controlled
validation path in the renderer. Do not scatter `.get()` calls that silently
turn missing integrity data into an incomplete report.

**REFACTOR:** keep valid golden report output byte/structure compatible and
extend the existing HTML renderer tests with malformed-payload cases.

**Verification:**

- `tests/application/reporting/test_html_renderer.py`
- `tests/test_golden_report_bundle.py`
- `tests/application/reporting/test_generate_report.py`

## Final verification

After each vertical slice reaches GREEN:

1. Run the focused test file(s) for that slice.
2. Run `python3 -m pytest tests/ -q --no-cov`.
3. Run `ruff check` and the repository type checks.
4. Run the frontend targeted tests for any HTTP or Tauri contract change.
5. Regenerate the crash report and confirm each fixed row is either mitigated
   by a runtime regression test or explicitly reclassified as unverified.
6. Run `make preflight` before pushing. The repository gate remains the final
   authority for backend, frontend, packaged-sidecar, and Tauri behavior.

## Decisions needed before implementation

1. For a persistent heartbeat failure or non-cancellation `LeaseLost`, should
   the Run become `failed` or `interrupted`?
2. Should an import `max_rows` value mean deterministic head limiting or seeded
   sampling?
3. Must every Plan Version split produce non-empty train, test, and OOT
   Artifacts, or should small datasets be valid with a warning?
4. Is a Run summary intentionally run-level Evidence with no Step identifier?
5. Should malformed report data return a structured 500 or an offline
   diagnostic document?
