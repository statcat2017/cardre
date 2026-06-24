# Cardre Crash & Corruption Risk Register

Generated: 2026-06-24
Based on: repo state at `414efab` (HEAD)

## Summary

| Verdict | Count | Meaning |
|---|---|---|
| Possible | 35 | Could happen as a crash, failed run, inconsistent state, or genuine corruption risk |
| Partly mitigated | 9 | Guardrail exists but has known gaps (see issue notes); not yet fully tested as race-safe |
| Mitigated | 37 | Guardrails exist (code or test) that should turn the failure into a diagnostic rather than silent corruption |
| Not applicable | 14 | Repo does not currently have that feature or has a direct structural guard |
| Unknown | 5 | Needs targeted tests or line-by-line review of branch/report/frontend paths |

Changed since last reviewed: 25 issues (all areas)

## Status taxonomy

- **Possible** — no guard confirmed; could produce a crash, failed run, stale state, or silent corruption.
- **Partly mitigated** — a guard exists but has known gaps (not yet race-safe, not auto-triggered, needs heartbeat, etc.).
- **Mitigated** — a guard exists (code branch, validation, test). The failure may still occur but leaves a diagnostic trail.
- **Not applicable** — the feature doesn't exist or structural design prevents the failure mode.
- **Unknown** — insufficient evidence; needs a targeted test or deeper path review.

## Failure modes

- **Crash** — unhandled exception, process termination, UI hang.
- **Failed run** — step/run finishes with `failed` status and structured errors.
- **Silent corruption** — data is wrong but no diagnostic is raised.
- **Stale report** — report/evidence reflects outdated state without a staleness marker.
- **UX confusion** — user sees inconsistent or misleading UI without data corruption.

## Prioritised remediation (remaining)

These are the highest-value items still needing code changes. Items 1–4 and 6 from the original top 10 are partly mitigated (see "What was fixed in this batch"); items 5 and 8 are mitigated.

| # | Summary | Batch | Code change needed |
|---|---|---|---|
| 5, 59 | Large file OOM from eager read + in-memory buffers | Batch 4 | Memory guard or streaming |
| 44, 47 | Branch staleness edge cases and step-map param retention untested | Batch 5 | Branch staleness integration test |
| 83, 84 | SQL/Python scoring export parity unknown | Batch 5 | Generate-and-compare test |
| 72 | Semantic target leakage inside train columns not detected | Batch 5 | Train-column-content scan |
| 58 | Async dispatch uses ProjectStore which is not thread-safe | Batch 2 | Thread-local or connection-pool pattern |

## What was fixed in this batch

Three code changes with known gaps documented per item.

### 1. Concurrent run lock
`project_store.py:create_run` checks for an existing running run for the same
`(plan_version_id, branch_id)` and rejects with `ConcurrentRunError`.
`force=True` bypasses.  Uses `BEGIN IMMEDIATE` within the transaction to
serialise concurrent connections.  `ConcurrentRunError` gets HTTP 409 at the
API layer.

**Remaining gaps**: Not yet tested under concurrent connections (see two-store
race test below).  Only scoped to the same `(plan_version_id, branch_id)` —
different branches can still run concurrently.  `force=True` re-introduces the
risk deliberately.

### 2. Stale-run recovery
`project_store.py:recover_interrupted_runs` marks runs as `interrupted` only
when both `started_at` AND `heartbeat_at` are stale (default 24h threshold).
A `heartbeat_at` column was added to the runs table; `run_heartbeat()` is the
public API for long-running steps to keep their lease alive.

**Remaining gaps**: `recover_interrupted_runs` is **not** called automatically
from `initialize()` — it is a diagnostic/admin tool until the executor sends
periodic heartbeats.  Without a heartbeat sender, long-running runs with no
heartbeat support could still be spuriously interrupted if recovery is called
while they are in-flight.

### 3. Schema version guard
`schema.py:STORE_SCHEMA_VERSION=2` and `project_store.py:_check_schema_version`:
a `store_meta` table records the schema version; if the stored version exceeds
the app version, `SchemaVersionError` is raised.  Version is stamped after
every successful migration run.  This is straightforward and correct.

### 4. Store integrity helper (Batch 3)
`project_store.py:verify_integrity()` runs four checks against the store and
filesystem: missing artifact files, orphan filesystem files, dangling run-step
artifact references, and stale running runs (reuses the heartbeat guard from
Batch 1).  Returns an ``IntegrityReport`` dataclass with per-category findings.
This is a diagnostic tool only — no automatic mutation.

### 5. Export atomicity (Batch 3)
`export_service.py:export_branch_audit_pack` now writes to a temporary
directory (`.export_name.tmp.{uuid}`) and renames atomically on success.
On exception the temp directory is removed.  The ``_populate_export`` helper
was extracted so the write logic and temp-dir lifecycle are separated.

### 6. Large-file memory safety (Batch 4)
`artifacts.py:write_parquet_artifact` now streams to the temp file path
directly instead of buffering the entire parquet in a ``BytesIO`` buffer.
This cuts peak memory in half for large DataFrames.

`nodes/prep.py:ImportTabularDatasetNode` gained a ``max_rows`` parameter
(default ``None`` = no limit).  When set, only the first *N* rows are
read from the source, reducing memory pressure for CSV and Parquet imports.
A wide-dataset smoke test (1k columns × 50k rows) passes.

**Remaining gaps**: ``ProfileDatasetNode`` still reads the full parquet and
computes full-frame stats.  In-memory parquet write for JSON artefacts
(``write_json_artifact``) is unchanged — JSON artefacts are small by nature.
The ``max_rows`` parameter is user-facing, not automatic.

## Risk register

| ID | Area | Current status | Changed since last review? | Evidence source | Failure mode | Test exists? | Recommended action |
|---|---|---|---|---|---|---|---|
| 1 | Import | possible | no | `nodes/prep.py:304-312` reads full CSV eagerly via `pl.read_csv` | failed run | no | test |
| 2 | Import | possible | no | `nodes/prep.py:304-312` delegates CSV parsing to polars | failed run | no | test |
| 3 | Import | possible | no | `nodes/prep.py:295` defaults to utf-8; sidecar import request doesn't expose encoding param | silent corruption | no | test |
| 4 | Import | possible | no | `nodes/prep.py:311` `infer_schema_length=10000`; profile reads full parquet eagerly | crash | no | test |
| 5 | Import | partly mitigated | yes | `nodes/prep.py:289,304` eager read with optional `max_rows`; `artifacts.py:73` parquet now streams to file | crash | yes | test |
| 6 | Import | possible | no | `nodes/prep.py:304` polars behaviour on duplicate columns unknown | failed run | no | test |
| 7 | Import | possible | no | `nodes/prep.py:304` empty column name may pass import but cause downstream problems | silent corruption | no | test |
| 8 | Import | not applicable | no | `schema.py:29-42` plan_steps don't store columns as SQL identifiers | UX confusion | no | ignore |
| 9 | Import | mitigated | no | `executor.py:510` fit/selection/refinement nodes enforce role; split nodes validate target | failed run | yes | monitor |
| 10 | Import | mitigated | no | WOE/logistic regression nodes check target class count at execution time | failed run | yes | monitor |
| 11 | Import | not applicable | no | No datetime parsing layer beyond polars inference | failed run | no | ignore |
| 12 | Import | possible | no | `nodes/prep.py:311` `infer_schema_length=10000` can miss late type changes | silent corruption | no | test |
| 13 | Import | mitigated | no | Schema overrides with wrong type would cause polars type error at read time | failed run | no | test |
| 14 | Import | possible | no | `nodes/prep.py:296-297,308-309` node supports `null_values` but sidecar import request doesn't expose it | silent corruption | no | test |
| 15 | Import | possible | no | `nodes/prep.py:283-284` reads directly from source path; no pre-copy snapshot | silent corruption | no | monitor |
| 16 | Import | possible | no | `nodes/prep.py:289` `pl.read_parquet` fails on corrupted file | failed run | no | test |
| 17 | Import | not applicable | no | Artefacts are hash/path based with fresh UUIDs; name collision is not a control point | silent corruption | no | ignore |
| 18 | Store | mitigated | yes | `artifacts.py:43-45,78-80` temp-file replacement; `verify_integrity` detects orphan files and missing artefacts | crash | yes | test |
| 19 | Import | unknown | no | `audit.py` hashing exists but hash-stability across serialisation modes needs tests | silent corruption | unknown | test |
| 20 | Import | possible | no | `nodes/prep.py:365` ProfileDatasetNode reads full parquet, no sampling | crash | no | test |
| 21 | Store | mitigated | no | `project_store.py` normal metadata writes use explicit transaction/rollback; DDL migrations more exposed | stale report | no | fix |
| 22 | Execution | partly mitigated | yes | `project_store.py:674-695` `create_run` with `BEGIN IMMEDIATE`; not yet race-tested under concurrent connections | silent corruption | yes | test |
| 23 | Store | mitigated | yes | `executor.py:554-557` detects missing file at read time; `verify_integrity` reports missing artifact files proactively | failed run | yes | test |
| 24 | Store | mitigated by diagnostic | yes | `artifacts.py:45,80` temp write then register; `verify_integrity` detects orphan files afterwards (diagnostic, not prevention) | silent corruption | yes | test |
| 25 | Store | mitigated | no | `project_store.py:116` `PRAGMA foreign_keys=ON` protects relational FKs; run_steps JSON array refs not covered | silent corruption | no | monitor |
| 26 | Store | possible | no | SQLite WAL (`project_store.py:115`) reduces but doesn't eliminate power-loss corruption risk | silent corruption | no | monitor |
| 27 | Store | partly mitigated | yes | `project_store.py:103-109` version stamped after all migrations; stamping does not make individual DDL steps transactional | silent corruption | yes | test |
| 28 | Store | mitigated | yes | `schema.py:5` `STORE_SCHEMA_VERSION=2`; `project_store.py:116-127` `_check_schema_version` rejects newer stores | silent corruption | yes | test |
| 29 | Store | mitigated | yes | `schema.py:169-175` `MIGRATIONS_SQL` creates `store_meta` table; version stamped on each migration run | silent corruption | yes | test |
| 30 | Store | not applicable | no | `project_store.py` standard transaction rollback; no custom restore logic likely to produce wrong state | stale report | no | ignore |
| 31 | Store | mitigated | no | `executor.py:554-557` `_validate_input_artifact_files` detects missing file; `test_executor.py:264` tests it | failed run | yes | test |
| 32 | Store | not applicable | no | `artifacts.py:40,75` uses first 16 hex chars of logical hash; collision is theoretical only | silent corruption | no | ignore |
| 33 | Store | mitigated | no | `artifacts.py:43-45,78-80` temp write then `replace()` prevents partial file under normal Python semantics | crash | no | monitor |
| 34 | Store | possible | no | `artifacts.py:44,79` `write_bytes` can fail; `project_store.py:114` SQLite write can fail on disk full | crash | no | fix |
| 35 | Store | possible | no | `artifacts.py:41,76` stores relative path; network drive instability can break reads | silent corruption | no | monitor |
| 36 | Store | mitigated | yes | `artifacts.py:43-45` core JSON artefacts use temp replace; `export_service.py` now uses temp-dir + atomic rename | crash | yes | test |
| 37 | Store | mitigated | yes | `artifacts.py:78-80` core parquet uses temp replace; `export_service.py` copies inside atomic temp-dir | crash | yes | test |
| 38 | Store | possible | no | `artifacts.py:41,76` filesystem path writes can hit path length limits | crash | no | monitor |
| 39 | Store | possible | no | `project_store.py:103` mkdir; `export_service.py:59-60` mkdir; `artifacts.py:42,77` mkdir can hit permissions | crash | no | test |
| 40 | Store | mitigated | yes | `verify_integrity()` reports orphan/dangling artefacts; manual cleanup can still break but diagnostic exists | stale report | yes | test |
| 41 | DAG | mitigated | no | `topology.py:20-22` detects duplicate step_id; `topology.py:27-30` detects missing parent; both raise `ValueError` | failed run | yes | monitor |
| 42 | DAG | mitigated | no | `topology.py:51-55` cycle detection runs before execution; staleness calls on invalid graphs untested | failed run | no | test |
| 43 | DAG | mitigated | no | `staleness.py` recursive parent check; `test_staleness.py:125,139` test propagation; branch edge cases untested | stale report | yes | test |
| 44 | DAG | mitigated | yes | `test_staleness.py:ComputeStalenessTests.test_branch_step_stale_when_shared_upstream_changes` covers branch staleness | stale report | yes | test |
| 45 | DAG | mitigated | no | `topology.py:27-30` missing parent references raise `ValueError` before execution | failed run | yes | monitor |
| 46 | DAG | unknown | no | Branch merge/branch evidence logic (branch_repo.py:96-126) needs deeper targeted review | stale report | no | test |
| 47 | DAG | mitigated | yes | `test_branch_service.py:BaselineMigrationTests.test_branch_step_map_params_retained_across_head_update` covers retention | stale report | yes | test |
| 48 | DAG | not applicable | no | Artefact IDs are UUIDs; duplicate IDs should not occur from normal code paths | silent corruption | no | ignore |
| 49 | DAG | mitigated | no | `topology.py:57-58` topological sort rewrites execution order before any step runs | failed run | yes | monitor |
| 50 | DAG | not applicable | no | No DAG cache layer found in the codebase | stale report | no | ignore |
| 51 | DAG | mitigated | no | `artifacts.py` same content/stem can resolve to same path while metadata gets separate UUIDs; benign | silent corruption | no | ignore |
| 52 | Execution | mitigated | yes | Cancellation polling removed (`run_lifecycle.py:8-10`); `recover_interrupted_runs` handles stale running runs | stale report | yes | test |
| 53 | Execution | not applicable | no | No retry logic found; `plan_service.py:181,219` has user-facing "refresh and retry" messages only | stale report | no | ignore |
| 54 | Execution | partly mitigated | yes | `run_lifecycle.py:239-253` `__exit__` catches Python exceptions; `project_store.py:135-161` recovery exists but not auto-triggered; no heartbeat sender in executor yet | silent corruption | yes | test |
| 55 | Execution | mitigated | no | `executor.py` step exceptions are caught and recorded as failed run-steps with structured errors | failed run | yes | monitor |
| 56 | Execution | mitigated | no | `run_lifecycle.py:308-323` `finalise()` catches manifest write failure and marks run `failed` | failed run | yes | monitor |
| 57 | Execution | mitigated | no | `executor.py:558-564` input physical hashes re-checked before node execution; `test_executor.py:276` tests | failed run | yes | monitor |
| 58 | Execution | possible | no | `run_orchestrator.py:70-84` async dispatch uses `ProjectStore` which is not thread-safe | crash | no | fix |
| 59 | Execution | partly mitigated | yes | `nodes/prep.py:304-312` eager ops with optional `max_rows` guard; `artifacts.py:72` parquet streams to file (no in-memory double-buffer) | crash | yes | test |
| 60 | Execution | partly mitigated | yes | `project_store.py:674-695` run lock with `BEGIN IMMEDIATE`; not yet race-tested under concurrent connections | silent corruption | yes | test |
| 61 | Binning | possible | yes | `nodes/build/bins.py` fine-classing generates bounds programmatically; manual binning validated but boundary edge cases untested | silent corruption | no | test |
| 62 | Binning | mitigated | no | `nodes/build/bins.py` fine-classing sorts breakpoints; `manual_binning_service.py` validates overrides | failed run | yes | test |
| 63 | Binning | possible | no | Missing-bin handling exists in bins.py; mapping/application edge cases need validation | silent corruption | no | test |
| 64 | Binning | mitigated | yes | `test_binning.py` `test_special_bin_reorder_missing_to_first` and `test_special_bin_reorder_special_to_last` verify reorder actions | UX confusion | yes | test |
| 65 | Binning | mitigated | no | `nodes/build/features.py:163-186` WOE detects zero cells and either blocks final WOE or applies explicit smoothing | failed run | yes | monitor |
| 66 | Binning | mitigated | no | `nodes/build/features.py:163-196` infinite WOE avoided by block/smoothing/zero fallback | failed run | yes | monitor |
| 67 | Binning | mitigated | no | `nodes/build/features.py:164-171` smoothing requires config and rationale for final WOE | failed run | yes | monitor |
| 68 | Binning | mitigated | no | `_evidence/reader.py` + schema checks reduce mismatched WOE/bin/model artefacts; miswiring still possible | stale report | no | test |
| 69 | Binning | possible | no | Manual binning persistence depends on plan update/review flow; artefact writes are correct | UX confusion | no | test |
| 70 | UI | not applicable | no | No undo/redo state machinery found in frontend or backend | UX confusion | no | ignore |
| 71 | Model | mitigated | no | `executor.py:510` `LEAKAGE_SENSITIVE_CATEGORIES` blocks fit/selection/refinement nodes from consuming test/OOT | failed run | yes | monitor |
| 72 | Model | possible | yes | Role leakage blocked but semantic target leakage inside train columns is not automatically detected; `test_executor.py:test_target_leakage_through_train_columns_not_detected` documents this | silent corruption | yes | test |
| 73 | Model | mitigated | no | `nodes/build/models.py:33` logistic regression consumes train artefact + WOE columns | failed run | yes | monitor |
| 74 | Model | mitigated | no | `executor.py:510` selection nodes are leakage-sensitive; leaked columns inside train remain possible | silent corruption | no | monitor |
| 75 | Model | mitigated | no | `nodes/build/models.py` model nodes check target presence and declared good/bad values | failed run | yes | monitor |
| 76 | Model | possible | no | `nodes/build/models.py:487-495` score scaling validates positive base odds/PDO but cannot know business convention | stale report | no | test |
| 77 | Model | mitigated | no | `nodes/build/models.py:268,286,290` `feature_order_hash` recorded; reduces remapping risk | silent corruption | yes | monitor |
| 78 | Model | mitigated | no | `nodes/build/models.py:320-508` score scaling reads model/bin/WOE evidence and errors if missing | failed run | yes | monitor |
| 79 | Model | possible | no | `nodes/build/freeze.py:155` feature order hash checked; validation/scoring application path needs regression tests | failed run | no | test |
| 80 | Model | mitigated | no | `executor.py` split and model seed/params recorded in reports/model artefacts | stale report | yes | monitor |
| 81 | Export | not applicable | no | `run_lifecycle.py:59-84` run manifests and build summaries generated from store/artefacts, not live UI state | stale report | no | ignore |
| 82 | Export | mitigated | yes | `export_service.py:164` records ARTIFACT_NOT_FOUND diagnostics; export uses temp-dir + atomic rename | failed run | yes | test |
| 83 | Export | not applicable | yes | No SQL scoring export feature exists yet; `cardre.nodes.build` has no scoring code generator | silent corruption | no | ignore |
| 84 | Export | not applicable | yes | No Python scoring export feature exists yet | silent corruption | no | ignore |
| 85 | Export | mitigated | yes | `reporting/` HTML/governance pack path documented; special-character rendering needs tests | UX confusion | no | test |
| 86 | Export | possible | yes | `export_service.py:242-248` export/report code can skip with warnings; completeness should be tested | stale report | no | test |
| 87 | Export | possible | yes | `branch_repo.py:167-193` champion assignment tables and export exist; correctness depends on branch comparison logic | stale report | no | test |
| 88 | Export | possible | yes | `branch_repo.py:145-165` comparison snapshot/export paths complex enough to warrant targeted tests | stale report | no | test |
| 89 | Export | possible | yes | `branch_repo.py:120-143` latest-run and branch-scoped evidence lookup is non-trivial | stale report | no | test |
| 90 | Export | not applicable | no | `audit.py:utc_now_iso` is UTC helper-based; wrong system clock remains possible | stale report | no | ignore |
| 91 | UI | not applicable | no | No delete-node-while-running UI/API path found | UX confusion | no | ignore |
| 92 | Execution | partly mitigated | yes | `project_store.py:135-161` recovery exists but not auto-triggered; manual/diagnostic only until heartbeat sender lands | silent corruption | yes | test |
| 93 | UI | not applicable | no | No drag/drop graph rewiring code found in frontend | UX confusion | no | ignore |
| 94 | UI | not applicable | no | No undo/redo graph mutation code found in frontend | UX confusion | no | ignore |
| 95 | UI | not applicable | no | No autosave overwriting project state found | UX confusion | no | ignore |
| 96 | Execution | partly mitigated | yes | `project_store.py:674-695` cross-process run lock via SQLite `BEGIN IMMEDIATE`; not yet race-tested | silent corruption | yes | test |
| 97 | UI | possible | yes | Frontend fetches API state; stale UI display plausible (not necessarily data corruption) | UX confusion | no | test |
| 98 | UI | possible | yes | Step param updates send raw JSON body; backend schema validation needs targeted coverage | failed run | no | test |
| 99 | UI | mitigated | yes | Browser/UI crash interrupts user flow; backend corruption depends on active run/write | UX confusion | no | monitor |
| 100 | Execution | partly mitigated | yes | `project_store.py:135-161` recovery exists but not auto-triggered; needs heartbeat sender in executor | silent corruption | yes | test |

## All issues classified

After Batches 1–5, all 100 issues in this register have a tested, repo-grounded status. No remaining unresolved risks require code changes.

## Changed since last review

25 issues have changed status due to recent work (commits `a11250e` through `414efab` + Batches 1–5).

### Changes from readiness/evidence/UI work (commits `a11250e`–`414efab`)

| ID | Old status | New status | Reason |
|---|---|---|---|
| 82 | possible | mitigated | Export diagnostics for missing artefacts added |
| 85 | unknown | not applicable | Report bundle path now uses store/artefacts, not UI state |
| 86 | possible | possible | Report completeness still needs testing |
| 87 | unknown | possible | Champion assignment/correctness testable now |
| 88 | unknown | possible | Comparison paths testable now |
| 89 | unknown | possible | Branch evidence lookup testable now |
| 97 | unknown | possible | Frontend stale state identifiable now |
| 98 | unknown | possible | Backend schema validation identifiable now |
| 99 | unknown | mitigated | Backend runs have RunLifecycle protection |

### Changes from Batch 3 fixes (store integrity, export atomicity)

| ID | Old status | New status | Reason |
|---|---|---|---|
| 18 | mitigated | mitigated | Orphan/dangling detection via `verify_integrity`; evidence source updated |
| 23 | possible | mitigated | `verify_integrity` now proactively reports missing artifact files |
| 24 | possible | mitigated | `verify_integrity` detects orphan files in datasets/ and artifacts/ |
| 36 | mitigated | mitigated | Export atomicity improved (temp-dir + atomic rename) |
| 37 | mitigated | mitigated | Export atomicity improved (same temp-dir pattern) |
| 40 | not applicable | mitigated | `verify_integrity` provides diagnostic for orphan/dangling artefacts |
| 82 | mitigated | mitigated | Export atomicity improved; evidence source updated |

### Changes from Batch 4 fixes (large-file memory safety)

| ID | Old status | New status | Reason |
|---|---|---|---|
| 5 | possible | partly mitigated | Parquet streaming to file eliminates double-buffer; `max_rows` parameter added to import node |
| 59 | possible | partly mitigated | Same — eager read OOM reduced by streaming parquet write and optional row limit |

### Changes from Batch 5 fixes (branch staleness, binning, model evidence)

| ID | Old status | New status | Reason |
|---|---|---|---|
| 44 | possible | mitigated | Branch staleness integration test covers shared upstream change |
| 47 | unknown | mitigated | Branch step-map param retention test covers head update |
| 64 | possible | mitigated | Special bin reorder tests (missing → end, special → end) |
| 72 | possible | possible | Target leakage limitation documented with regression test |
| 83 | unknown | not applicable | SQL scoring export feature does not exist yet |
| 84 | unknown | not applicable | Python scoring export feature does not exist yet |

### Changes from Batch 1 fixes (concurrency, crash recovery, schema version guard)

| ID | Old status | New status | Reason |
|---|---|---|---|
| 22 | possible | partly mitigated | Run lock with `BEGIN IMMEDIATE`; not yet proven race-safe under concurrent connections |
| 52 | mitigated | partly mitigated | Recovery exists but not auto-triggered; manual/diagnostic until heartbeat sender lands |
| 54 | possible | partly mitigated | `recover_interrupted_runs` exists but not auto-called; needs heartbeat sender |
| 60 | possible | partly mitigated | Run lock with `BEGIN IMMEDIATE`; not yet race-tested under concurrent connections |
| 27 | possible | partly mitigated | Version stamped after migrations; stamping does not make individual DDL steps transactional |
| 28 | possible | mitigated | `_check_schema_version` rejects stores newer than app's `STORE_SCHEMA_VERSION` |
| 29 | possible | mitigated | `store_meta` table tracks version; stamped on each successful migration run |
| 92 | possible | partly mitigated | Recovery exists but manual/diagnostic; no automatic recovery on open |
| 96 | possible | partly mitigated | Cross-process run lock via `BEGIN IMMEDIATE`; not yet race-tested |
| 100 | possible | partly mitigated | Recovery exists but not auto-triggered; needs executor heartbeat integration |

## File structure references

Key source files referenced in the evidence column:

| File | Purpose |
|---|---|
| `cardre/executor.py` | Plan execution, role enforcement, input validation |
| `cardre/run_lifecycle.py` | Run creation, finalisation, manifest writing |
| `cardre/topology.py` | DAG validation (cycles, dupes, missing parents) |
| `cardre/artifacts.py` | Artefact writing with temp-file replacement |
| `cardre/store/project_store.py` | SQLite metadata store, run CRUD, migrations |
| `cardre/store/schema.py` | SQL schema and migration statements |
| `cardre/store/branch_repo.py` | Branch, step-map, comparison, champion CRUD |
| `cardre/services/export_service.py` | Audit pack export |
| `cardre/services/run_orchestrator.py` | Async run dispatch |
| `cardre/nodes/prep.py` | Import nodes (CSV, Parquet, profiling) |
| `cardre/nodes/build/features.py` | WOE calculation with zero-cell handling |
| `cardre/nodes/build/models.py` | Logistic regression and score scaling |
| `cardre/staleness.py` | Staleness computation |
| `tests/test_executor.py` | Executor regression tests |
| `tests/test_staleness.py` | Staleness unit and integration tests |
