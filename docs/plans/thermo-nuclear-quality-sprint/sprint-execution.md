# Sprint Execution — How to Run the Quality Sprint in Parallelised Batches

The README defines 12 PRs (PR0–PR11). Most of the work is file-isolated,
but the dependency graph constrains ordering. Use the batches below to
overlap work safely. Within each batch, launch independent subagents in
parallel; merge a batch before starting the next so downstream agents can
rely on the new typed readers, deleted dead code, and deduped helpers.

## Operating rules

1. **One step = one PR.** Each batch's steps merge as small PRs; do not
   batch unrelated steps into a single PR.
2. **A PR may either change behaviour OR refactor structure, but not
   both** unless explicitly labelled as a migration PR. See README §Operating
   rules.
3. **Before pushing a PR**, run
   `. .venv/bin/activate && ruff check --fix && make preflight`. PRs that
   fail preflight do not get merged.
4. **PR0 safety net must land first.** No refactor PR merges until golden
   fixtures, smoke test, and grep checks exist. This is the safety net that
   makes the refactors reviewable.
5. **No behaviour change without a test.** If a PR changes observable
   behaviour (report output, run status, artifact shape), it must include
   a test that asserts the new behaviour and a before/after diff. The
   golden report bundle fixture (PR0) is the diff baseline for collector
   refactors.
6. **No new raw JSON parsing in product code.** If a typed reader is
   missing, expand `cardre/_evidence/` (PR2) instead.
7. **Subagent scope:** each agent receives exactly the per-step instruction
   file plus this batch map. They are NOT given the whole spec. They edit
   only their assigned files.
8. **Reference the finding ID** (T1, T2, ..., F10) in every commit message
   and PR description so the audit is traceable.
9. **Do not delete tests for deleted code without a decision.** See README
   §PR4 and the per-step instructions.
10. **Audit script is the source of truth** for `_raw` violation counts.
    After PR2, run
    `rg '_raw' cardre/nodes cardre/reporting cardre/services/comparison_service.py --type py -c`
    and include the before/after delta in the PR description.

## Batches

### Batch A — Safety net (1 agent, must be first)

- **PR0** — golden fixtures, smoke test, grep checks

**Gate:** PR0 merged. CI green. Golden report bundle fixture exists and
passes. The smoke test (`test_launch_pathway.py` already exists — extend
it or add a report-level golden diff). The grep check scripts exist and
can emit current violator counts (the baseline for measuring progress).

Do not start any other batch until PR0 is merged.

### Batch B — Low-risk consolidation + reuse decision (parallel, 2 agents)

- **PR1** — centralize branch step resolution + low-risk dedup (T6, K3,
  K4, K5, SE6, SE8). Independent file set: `cardre/branch_step_resolver.py`
  (new), `cardre/_evidence/kinds.py`, `cardre/_evidence/adapters/_base.py`,
  `cardre/domain/run.py`, `cardre/execution/executor.py` (SE6 `_json_ready`
  extraction), `cardre/execution/step_runner.py`, `cardre/execution/fingerprints.py`,
  `cardre/execution/dispatcher.py` (SE8 deletion),
  `cardre/reporting/collector.py` (import update),
  `cardre/readiness/check.py` (import update).
- **PR4** — evidence reuse decision (T3, K1). Independent file set:
  `cardre/services/evidence_resolver.py`, `cardre/execution/executor.py`
  (reuse branches — coordinate with PR1 on `_json_ready` but the reuse
  branches are in different functions), `cardre/execution/run_step_writer.py`,
  `cardre/execution/action_planner.py`, `cardre/evidence_locator.py`.
  **Requires the product decision in `reuse-decision.md` before execution.**

**Gate:** both merged. CI green. `branch_step_resolver.py` exists;
`EvidenceResolver` is deleted or wired; `ExecutionActionPlanner` only emits
`"execute"` (or reuse is wired with tests).

### Batch C — Typed evidence coverage (sequential, 1 agent, largest step)

- **PR2** — complete typed evidence coverage: 4 diagnostics kinds +
  `ManualBinningOverrides` model (T1a, T1b); typed read-only properties on
  `ModelArtifactV1` (T1c — properties only, no consumer migration yet);
  adapter table collapse (T2); fix `BinDefinition` Any-shadow +
  `apply_overrides` lossy round-trip + `normalize` (T7); dedup
  `artifacts.py` write/register (K2).

Must run after Batch B (needs T6 resolver and the adapter table ready).
This is the highest-leverage and largest single step — it touches
`cardre/_evidence/`, `cardre/modeling/schema.py`, `cardre/modeling/builders.py`,
`cardre/_evidence/models/binning.py`, `cardre/engine/binning/definition.py`,
`cardre/artifacts.py`, `cardre/modeling/serialization.py`.

**Important:** PR2 adds typed properties and new kinds/models but does NOT
migrate consumers off `_raw`. The consumers migrate in Batch D (one slice
at a time). This avoids the "150 call sites changed at once" trap.

**Gate:** merged. CI green. The 4 diagnostics + manual-binning overrides
have `EvidenceKind` members, typed models, and `AdapterSpec` entries.
`ModelArtifactV1` has typed properties for every field currently read via
`_raw.get(...)`. `BinDefinition` has no `_lifecycle: Any`. Round-trip tests
for model artifacts and merged bins pass. `EVIDENCE_ADAPTERS` is a table.

### Batch D — Remove `_raw` from consumers (parallel, 3 agents)

Run in parallel; each agent owns a disjoint vertical slice. Depends on
Batch C (needs typed properties + new evidence kinds).

- **PR3a** — scoring export slice: replace `_raw` in
  `cardre/nodes/build/scoring_export.py` (47 `_raw` accesses) and
  `cardre/nodes/build/freeze.py` (10) with typed attribute access.
- **PR3b** — calibration slice: replace `_raw` in
  `cardre/nodes/calibrate.py` (22) and
  `cardre/nodes/build/models.py` (6) with typed attribute access.
- **PR3c** — reporting collector slice: replace `_raw` in
  `cardre/reporting/collector.py` (14) and
  `cardre/services/comparison_service.py` (8). Delete
  `_read_raw_json_by_step` and use the new typed diagnostics readers.
  Fix `reproducibility`/`run_status` split ownership (R4).

**Gate:** each agent's file count in the `_raw` audit shows 0. CI green.
Golden report bundle diff passes (no report output change). The
`hasattr(data, "to_dict")` duck-typing in collector is gone.

### Batch E — Collector decomposition + node helpers + binning (parallel, 3 agents)

Depends on Batch D (needs PR3c collector `_raw` removal).

- **PR5** — collector decomposition: registry-driven `SectionCollector`;
  `collect()` becomes a loop; `reporting/sections/` package. Golden report
  diff must pass. Target: `collector.py` < 500 lines. Also drives
  `readiness/check.py` from a table (R1), `readiness/dto.py` Pydantic (R2),
  `report_mode: Literal` (R3), `report_status` computed property (R5),
  renderer default fallback (R6).
- **PR6** — node helper extraction: `context.target_metadata()`,
  `reader.require_model()`, `context.data_artifacts()`; fix fairness
  copy-paste bug; `_typed_definition_payload` protocol (N5); magic strings
  → constants (N4). Also: `BinningNode` dispatcher collapse (N1), god-function
  extraction (`ValidationMetricsNode.run` 280→~80,
  `VariableClusteringNode.run` 230→~50), `ModelExplainabilityNode`
  estimator-load dedup (N2), ensemble dead-code removal (N3),
  `prep.py` split + German-credit fixture relocation.
- **PR7** — binning override seam hardening: replace the stale golden manual
  override fixture with the live schema, add golden regression tests around
  `LifecycleBinDefinition.apply_overrides(...)`, and fix field-preservation
  bugs only if the new tests expose one. Do not attempt repo-wide
  `BinDefinition` retirement here.

**Gate:** `collector.py` < 500 lines. `prep.py` is gone (split into 5
files). `GERMAN_CREDIT_COLUMNS` not in production launch-tier code. God-
functions < 100 lines. CI green. Golden report diff passes.

### Batch F — Run status transitions (sequential, 1 agent)

Depends on Batch B (needs PR4 reuse-subsystem deletion) and Batch D.

- **PR8** — `RunStatus` enum + single `RunRepository.transition` (SE3);
  executor returns `PlanExecutionResult` (SE4); delete `to_node` executor
  branch (SE2); stale-recovery dedup (SE1); `refresh_comparison` atomicity
  (SE5); `branch_id` single-read (SE7). This is a **migration PR**
  (labelled) — it changes the run-status writer from string literals to an
  enum + transition function. The observable behaviour (which status a
  run ends in) must not change; only the mechanism does.

**Gate:** `RunStatus` is an enum; `finish(...)` calls go through one
transition function; `refresh_comparison` is one transaction. CI green.
Run lifecycle tests pass with the new enum.

### Batch G — Store / API / sidecar (parallel, 2 agents)

Depends on Batch F (needs `RunStatus` enum for repo return-type
consistency).

- **PR9a** — `ProjectStore` delegate block deletion (A1); `Repository`
  base + `_branch_filter` helper + `ChampionRepository` extraction (A2);
  repo return-type consistency (A5); `active_step_id` column (A7).
- **PR9b** — move route business logic to services (A3); `errors.py`
  dedup (A4); centralise mappings (A6); `create_project` `__version__`
  fix (A8); sidecar argv cleanup (A9).

**Gate:** `ProjectStore` < 80 lines. No route walks the filesystem or
builds `RunSummary` inline. CI green.

### Batch H — Frontend + Tauri (1 agent, independent)

Can run any time after Batch A (no backend dependency, but best after
the API shapes stabilize post-PR9).

- **PR10** — `firstQueryError` → `queryKey[0]` (F1); `ApiError.code`
  typed union (F2); `useRunWatch` single prose switch + `stuck` deletion
  (F3, F6); `toErrorMessage` helper (F4); schema-typed component props
  (F5); react-query for run poll + manual-binning (F7); dead styles (F8);
  `App.tsx` project state (F9); `main.rs` timeout + dead ctrl-c (F10).

**Gate:** `npm run typecheck` green. `npm test` green. No `any`/`unknown`
casts on `ApiError.code`.

### Batch I — Verify + lock-down (sequential, 1 agent, last)

Depends on all prior batches merged.

- **PR11** — full test suite green; `make preflight` green; audit script
  confirms zero `_raw` accesses in production node/reporting code; update
  `docs/architecture/` and `CONTEXT.md` if evidence kinds changed; retro
  decision log.

**Gate:** `make preflight` green. `_raw` count in
`cardre/nodes`+`cardre/reporting`+`cardre/services/comparison_service.py`
is 0. Decision log written. No file in `cardre/` exceeds 1000 lines.

## Critical path (fallback if parallelism is limited)

If only one agent is available, run in this order:

```text
PR0 → PR1 → PR2 → PR3c → PR5 → PR4 → PR8 → PR9 → PR6 → PR7 → PR10 → PR11
```

Critical path target: PR2 is the longest single step (typed-evidence
completion touches ~12 files + new model/adapter files). Expect ~40% of
total sprint effort in PR2 + PR3* + PR5.

## Estimated effort

| Step | Estimated effort | Files touched | Behaviour change? |
|---|---|---|---|
| PR0 | Medium | ~5 test/script files | No (tests + scripts only) |
| PR1 | Low-medium | ~10 files | No |
| PR2 | **High** (largest step) | ~12 files + new model/adapter files | No (additive) |
| PR3a | Medium | `scoring_export.py`, `freeze.py` | No |
| PR3b | Medium | `calibrate.py`, `build/models.py` | No |
| PR3c | Medium | `collector.py`, `comparison_service.py` | No |
| PR4 | Low (mostly deletion) | ~5 files + docs/tests | Decision required |
| PR5 | **High** | `collector.py` + new `reporting/sections/` | No (golden diff) |
| PR6 | High | ~15 node files + new `prep/` package | No |
| PR7 | Low-medium | binning fixtures/tests + maybe `definition.py` | No (round-trip tests) |
| PR8 | Medium | ~7 services/execution files | Migration (labelled) |
| PR9 | Medium | ~15 store/api files | No |
| PR10 | Medium | ~12 frontend/rust files | No |
| PR11 | Low | docs + verification | No |

Total: 14 PRs (PR0 + PR1–PR11, with PR3 split into a/b/c and PR9 split into
a/b). ~100 files touched. ~1500–2000 LOC deleted net (deletions outweigh
additions because the code-judo moves collapse boilerplate).
