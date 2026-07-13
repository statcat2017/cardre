# Thermo-Nuclear Quality Sprint — Resolving Review 013

Resolves every finding from
[Plan Review 013: Thermo-Nuclear Codebase Quality Audit](../../plan-reviews/013-thermo-nuclear-codebase-review.md).

Current state: 5 presumptive blockers, 50 total findings. Target: zero
blockers, all findings resolved, behaviour preserved.

## Principle

> The typed-evidence layer is the load-bearing abstraction for the whole
> engine. It is currently ~50% used. Completing it is the single
> highest-leverage move — but it must be done in small, test-backed,
> behaviour-preserving steps, not a giant refactor PR.

The audit (review 013) identifies root causes and prefers deletion over
abstraction layering. This sprint turns those findings into a sequenced
refactor programme with hard acceptance criteria, small PR boundaries, and
explicit "no behaviour change" checks.

## Operating rules

1. **One PR = one step.** Do not batch unrelated steps into a single PR.
2. **A PR may either change behaviour OR refactor structure, but not both**
   unless explicitly labelled as a migration PR. Collector decomposition,
   run-lifecycle changes, model-artifact unification, and binning
   overrides are structure-only unless a finding explicitly fixes a bug.
3. **PR0 safety net must land first.** No refactor PR merges until the
   golden fixtures, smoke test, and grep checks exist.
4. **No behaviour change without a test.** If a PR changes observable
   behaviour (report output, run status, artifact shape), it must include
   a test that asserts the new behaviour and a before/after diff.
5. **Reference the finding ID** (T1, T2, ..., F10) in every commit message
   and PR description so the audit is traceable.
6. **`make preflight` green before push.** Run
   `. .venv/bin/activate && ruff check --fix && make preflight` before every
   push. Failing preflight blocks the PR gate.
7. **Do not delete tests for deleted code without a decision.** Tests that
   exercise the dead reuse subsystem (T3) must be triaged: deleted if the
   behaviour is removed, rewritten if the behaviour is wired, or kept with
   a `# review-013-T3: dead code, removal pending` marker. Do not leave
   them in a halfway state.
8. **No new raw JSON parsing in product code.** If a typed reader is
   missing, expand `cardre/_evidence/` (PR2) instead.

## Dependency graph

```text
PR0  safety net (golden fixtures, smoke test, grep checks)
  ├── PR1  low-risk consolidation (shared resolver, easy dedup)
  ├── PR2  typed evidence coverage (new kinds, typed properties)
  │    ├── PR3a remove _raw from scoring export slice
  │    ├── PR3b remove _raw from calibration slice
  │    ├── PR3c remove _raw from reporting collector slice
  │    │    └── PR5  collector decomposition (section registry)
  │    ├── PR7  binning override seam hardening (fixtures + round-trip tests)
  │    └── PR6  node helper extraction (target_metadata, require_model)
  ├── PR4  evidence reuse decision (delete or implement)
  │    └── PR8  run status transitions (RunStatus enum, atomic finish)
  │         └── PR9  store / API cleanup
  └── PR10 frontend + Tauri cleanup (independent)
       └── PR11 verify + lock-down (last)
```

## Steps (12 PRs)

| Step | PR | Title | Findings | Depends on | Behaviour change? |
|---|---|---|---|---|---|
| S0 | PR0 | Safety net before refactor | — | — | No (tests + scripts only) |
| S1 | PR1 | Centralize branch step resolution and low-risk dedup | T6, K3, K4, K5, SE6, SE8 | PR0 | No |
| S2 | PR2 | Complete typed evidence coverage (new kinds + typed properties) | T1a, T1b, T1c-typed-props, T2, T7, K2 | PR1 | No (additive — new types, no consumer changes) |
| S3a | PR3a | Replace raw evidence reads in scoring export | T1 (scoring_export slice) | PR2 | No |
| S3b | PR3b | Replace raw evidence reads in calibration | T1 (calibrate slice) | PR2 | No |
| S3c | PR3c | Replace raw evidence reads in reporting collector | T1 (collector slice), R4 | PR2 | No |
| S4 | PR4 | Decide evidence reuse: delete or implement | T3, K1 | PR1 | Decision required (see below) |
| S5 | PR5 | Decompose reporting collector into section registry | T5 (collector), R1, R2, R3, R5, R6 | PR3c | No (golden report diff) |
| S6 | PR6 | Extract node helpers (target_metadata, require_model, data_artifacts) | T4, N4, N5 | PR2 | No |
| S7 | PR7 | Harden binning override seam (current-schema fixtures + lossless round-trip tests) | T7 (remaining residue after PR2) | PR2 | No (round-trip tests) |
| S8 | PR8 | Introduce RunStatus enum and atomic transitions | SE1, SE2, SE3, SE4, SE5, SE7 | PR4 | Migration (labelled) |
| S9 | PR9 | Store / API / sidecar cleanup | A1-A9 | PR8 | No |
| S10 | PR10 | Frontend + Tauri cleanup | F1-F10 | — | No |
| S11 | PR11 | Verify, lock-down, decision log | All | All | No |

## PR4 — evidence reuse decision (spec required)

PR4 is gated on a **product decision** before any code is written:

**Option A: reuse is not part of launch.** Delete the unreachable paths,
remove or rewrite tests/docs/ADRs that imply support, and make unsupported
behaviour impossible to call. Update:
- `docs/adr/0004-single-run-lifecycle-atomic-finalisation.md`
- `docs/adr/0005-canonical-evidence-resolution-contract.md`
- `docs/adr/0013-evidence-locator-implementation.md`
- `docs/plans/branch-evidence-policy-unification.md`
- `docs/architecture/execution-and-staleness.md`
- Tests: `tests/test_evidence_resolver.py` (254 LOC, 19 reuse refs),
  `tests/test_evidence_resolver_edge_cases.py` (235 LOC, 24 refs),
  `tests/test_run_step_writer.py` (6 refs),
  `tests/test_executor_characterization.py` (4 refs)

**Option B: reuse is part of near-term branch semantics.** Do not delete.
Instead, make the planner actually emit `reuse`/`skip`, add integration
tests, and make failure modes explicit.

The decision must be recorded in
`docs/plans/thermo-nuclear-quality-sprint/reuse-decision.md` before PR4
execution begins. The sprint step file (`step-04`) provides the deletion
instructions for Option A and notes on Option B; the choice is made before
opening the PR.

## Acceptance criteria per finding

### T1 — typed evidence layer
- [ ] No `_raw` access outside `cardre/_evidence/**`, except in
  `cardre/_evidence/adapters/` (internal to the adapter layer) and
  documented compatibility tests.
- [ ] `MANUAL_BINNING_OVERRIDES` adapter returns a typed model, not `dict`.
- [ ] The 4 diagnostics evidence types (`coefficient_sign`, `separation`,
  `vif`, `calibration`) have `EvidenceKind`, profile, adapter, model.
- [ ] `ModelArtifactV1` has typed read-only properties for every field
  currently accessed via `_raw.get(...)` in consumers.
- [ ] `_read_raw_json_by_step` deleted from `reporting/collector.py`.
- [ ] Existing sample reports are unchanged (golden report diff passes).
- [ ] Existing model artifacts round-trip through the typed reader.

### T2 — adapter boilerplate
- [ ] `EVIDENCE_ADAPTERS` is a `dict[EvidenceKind, AdapterSpec]` table (or
  the 40 classes are reduced to ≤3 with real `parse` work).
- [ ] Duplicated `_match` helpers deleted; one shared match function.
- [ ] `kind`/`profile` class attrs (read by nobody) deleted.

### T3 — dead reuse subsystem
- [ ] `ExecutionActionPlanner` and executor agree on the action set (only
  `"execute"`, or `reuse`/`skip` are wired and tested).
- [ ] No unreachable reuse/skip branches remain, OR integration tests
  prove they execute.
- [ ] Branch evidence docs (`docs/adr/0004`, `0005`, `0013`,
  `docs/architecture/execution-and-staleness.md`,
  `docs/plans/branch-evidence-policy-unification.md`) match implementation.
- [ ] Tests named `test_evidence_resolver*` are either removed, rewritten,
  or tied to live product behaviour.

### T4 — node boilerplate
- [ ] `context.target_metadata()` exists and replaces all 15 inline copies.
- [ ] `reader.require_model(model_art, node_type)` exists and replaces all
  11 six-line guards.
- [ ] `context.data_artifacts()` exists and replaces 6+ comprehensions.
- [ ] `cardre/nodes/fairness.py` error messages reference the correct node
  type (not "fairness_report requires..." in `ProxyRiskReportNode`).

### T5 — god-files
- [ ] `reporting/collector.py` < 500 lines; `reporting/sections/` exists.
- [ ] `nodes/prep.py` split into `prep/{import,profile,split,metadata,treatment}.py`,
  each <300 lines.
- [ ] `GERMAN_CREDIT_COLUMNS` not in production launch-tier code.
- [ ] `ValidationMetricsNode.run` < 100 lines; pure helpers extracted.
- [ ] `VariableClusteringNode.run` < 80 lines; impossible `ImportError`
  catch deleted.

### T6 — duplicated step resolver
- [ ] `cardre/branch_step_resolver.py` exists; both `collector.py` and
  `check.py` import from it.
- [ ] 3 `ResolvedStepRef` types collapsed to 1; `_to_schema_ref` deleted.
- [ ] `artifact_ids` field deleted; `MISSING_RUN_MANIFEST_COLLECTOR`
  deleted.

### T7 — binning types
- [ ] `tests/fixtures/golden_manual_binning_overrides.json` matches the live
  manual-binning override schema used by production code.
- [ ] A regression test reads the golden bin definition through
  `LifecycleBinDefinition.from_payload(...)`, applies current-schema
  overrides, and proves the merged result round-trips losslessly through
  `to_payload()` → `from_payload()`.
- [ ] Merged-bin assertions cover the previously dropped metrics (`kind`,
  `bad_rate`, `woe`, `iv`, `row_pct`) and any special/other-bin metadata
  exercised by the fixture or targeted test setup.
- [ ] If production code changes are needed, they stay local to the
  manual-binning binning seam; no repo-wide `BinDefinition` retirement or
  broad caller migration is part of PR7.

### R1-R6, SE1-SE8, N1-N5, A1-A9, K1-K5, F1-F10
- [ ] Resolved per the finding descriptions in
  [review 013](../../plan-reviews/013-thermo-nuclear-codebase-review.md).
- [ ] Each finding's acceptance criteria (where specified in the step
  file) met.

### Sprint-wide
- [ ] `make preflight` green. `ruff check`, `pytest tests/ -q`,
  `cd frontend && npm test && npm run typecheck` all pass.
- [ ] Golden report bundle fixture unchanged (unless intentionally
  improved — then diff is documented).
- [ ] `rg '_raw' cardre/nodes cardre/reporting
  cardre/services/comparison_service.py --type py -c` shows 0 in every
  file.
- [ ] `rg '^class .*Adapter' cardre/_evidence/adapters --type py` returns
  ≤3.
- [ ] No file in `cardre/` exceeds 1000 lines.
- [ ] Decision log written at
  `docs/plans/thermo-nuclear-quality-sprint/decision-log.md`.

## Parallelised batches

See [`sprint-execution.md`](./sprint-execution.md) for the recommended
batched execution schedule with gates.

## Per-step LLM instructions

Each file is a drop-in prompt for a subagent to execute one step:

- [`step-00-safety-net.md`](./step-00-safety-net.md)
- [`step-01-low-risk-consolidation.md`](./step-01-low-risk-consolidation.md)
- [`step-02-typed-evidence-coverage.md`](./step-02-typed-evidence-coverage.md)
- [`step-03a-raw-removal-scoring-export.md`](./step-03a-raw-removal-scoring-export.md)
- [`step-03b-raw-removal-calibration.md`](./step-03b-raw-removal-calibration.md)
- [`step-03c-raw-removal-reporting-collector.md`](./step-03c-raw-removal-reporting-collector.md)
- [`step-04-evidence-reuse-decision.md`](./step-04-evidence-reuse-decision.md)
- [`step-05-collector-decomposition.md`](./step-05-collector-decomposition.md)
- [`step-06-node-helper-extraction.md`](./step-06-node-helper-extraction.md)
- [`step-07-binning-type-cleanup.md`](./step-07-binning-type-cleanup.md)
- [`step-08-run-status-transitions.md`](./step-08-run-status-transitions.md)
- [`step-09-store-api-sidecar-cleanup.md`](./step-09-store-api-sidecar-cleanup.md)
- [`step-10-frontend-tauri-cleanup.md`](./step-10-frontend-tauri-cleanup.md)
- [`step-11-verify-lockdown.md`](./step-11-verify-lockdown.md)

## Critical path

```text
PR0 → PR1 → PR2 → PR3c → PR5 → PR11
                 ↘ PR4 → PR8 → PR9 ↗
```

PR10 (frontend) is fully independent and can run any time.
Critical path target: PR2 is the longest single step (typed-evidence
completion touches ~12 files + new model/adapter files). Expect ~40% of
total sprint effort in PR2 + PR3* + PR5.
