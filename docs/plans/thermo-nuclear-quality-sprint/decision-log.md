# Sprint Decision Log

All structural decisions made during the thermo-nuclear quality sprint (review 013).

## PR2 — Adapter table vs classes (T2)

**Date:** 2026-07-13
**Finding IDs:** T2
**Decision:** Replace 40 `EvidenceAdapter` classes with a `dict[EvidenceKind, AdapterSpec]` table in `cardre/_evidence/adapters/__init__.py`.

**Rationale:** ~30 of 40 adapters had byte-for-byte identical `parse` methods (read JSON → call `from_json`). The `kind`/`profile` class attrs were read by nobody. The `@runtime_checkable` Protocol was never used via `isinstance`. A table of `AdapterSpec(profile, parse)` collapses ~600 LOC to ~120 LOC while keeping the Protocol for the ~3 adapters that do real work (`WoeTable`, `IvTable`, `ScoredDataset`). The duplicated `_match` helpers and the registry all disappear.

**PR:** PR2 (#294)

## PR2 — `ModelArtifactV1` typed properties first, duplicate representations deferred (T1c)

**Date:** 2026-07-13
**Finding IDs:** T1c
**Decision:** Add typed read-only properties to `ModelArtifactV1` for every field accessed via `_raw.get(...)` in consumers. Do NOT retire the duplicate `_evidence/models/model.py:ModelArtifact` or the raw-dict `build_model_artifact` path.

**Rationale:** The typed properties unblock all consumer migrations (PR3a/3b/3c) without requiring a simultaneous rewrite of the model-building pipeline. Full retirement of the duplicate representation is a follow-up ticket — the sprint's DoD is "typed properties exist and consumers use them."

**PR:** PR2 (#294)
**Follow-up:** Retire `_evidence/models/model.py:ModelArtifact` and unify on `ModelArtifactV1` as the single model-artifact type.

## PR4 — Reuse-subsystem deletion (T3)

**Date:** 2026-07-13
**Finding IDs:** T3, K1
**Decision:** Option A — delete the unreachable evidence-reuse subsystem. `ExecutionActionPlanner` only ever emits `action="execute"`; there is no production path to `"reuse"` or `"skip"`.

**Rationale:** The dead code (~600 LOC) misleads readers and duplicates the live execute path. The product decision is that branch evidence reuse is not part of the near-term launch scope. Deleted: `EvidenceResolver`, `BranchRunEvidence`, `ShortCircuitResult`, `prepare_branch_evidence`, `resolve_parent_evidence`, `check_to_node_current`, `_reuse_run_step`, `write_reused_run_step`, `precomputed_outputs`/`precomputed_records`. The one live method (`check_branch_current`) was folded into `EvidenceLocator`. ADRs 0004, 0005, 0013, `execution-and-staleness.md`, and `branch-evidence-policy-unification.md` were updated to match the deleted state.

**PR:** PR4 (#298)

## PR5 — Section-collector registry (T5)

**Date:** 2026-07-13
**Finding IDs:** T5 (collector), R1–R6
**Decision:** Replace the 1337-line `ReportCollector` god-class with a `SectionCollector` protocol and a registry of section instances in `cardre/reporting/sections/`.

**Rationale:** The old `collect()` was a 210-line orchestrator of 15 `if ref := ...: self._collect_X(...)` lines. Each `_collect_*` shared the same "resolve → read-or-limitation → map" shape. Extracting a `SectionCollector` protocol (`canonical_step_id`, `kinds`, `build(bundle, ref, evidence, add_limitation)`) and registering one instance per section collapses the 15 branches to one loop. The file drops from 1337 to 240 lines. Combined with T1 (typed evidence) and T6 (dedup step-resolver), the collector is now a thin loop over the registry.

**PR:** PR5 (#315)

## PR6 — `prep.py` split + German-credit relocation (T5)

**Date:** 2026-07-13
**Finding IDs:** T5 (prep.py)
**Decision:** Split `cardre/nodes/prep.py` (1199 lines, 9 unrelated nodes) into `cardre/nodes/prep/{import,profile,split,metadata,treatment}.py`. Delete `GERMAN_CREDIT_COLUMNS` and `ImportGermanCreditNode` entirely (not relocated).

**Rationale:** The German-credit fixture (124 lines of UC Irvine demo-dataset schema) had no place in production launch-tier code. Zero tests and zero production plans referenced it. The split brings each file under 300 lines and isolates node concerns.

**PR:** PR6 (#316)

## PR6 — `BinningNode` dispatcher collapse (N1)

**Date:** 2026-07-13 (initial), 2026-07-14 (PR318 follow-up)
**Finding IDs:** N1
**Decision:** Collapse `BinningNode`'s sub-node dispatch. `BinningNode.run()` now delegates to module-level functions `_run_fine_classing(context)` and `_run_optbinning(context)` instead of instantiating sub-nodes or using `replace(context, validated_params=...)`.

**Rationale:** The original PR6 plan deferred this because `FineClassingNode` was still a launch-tier node. A follow-up (PR318) completed the collapse: `FineClassingNode` and `AutoBinningFitNode` were removed from the registry, and the two implementations became plain functions imported by `BinningNode`. The `replace(context, validated_params=...)` hack is gone.

**PR:** PR6 (#316), PR318 (follow-up)

## PR6 — `_typed_definition_payload` retained then cleaned (N5)

**Date:** 2026-07-13 (initial), 2026-07-14 (PR11 cleanup)
**Finding IDs:** N5
**Decision:** Keep the local helper in `feature_selection.py` but remove the `_raw` fallback. The helper now prefers `to_dict()` and falls back to `dataclasses.asdict`.

**Rationale:** The original PR6 plan deferred adding a `to_payload()` protocol across ~10 typed evidence classes. The PR11 cleanup round removed the `_raw` escape hatch from the helper while keeping it local. The helper is used at exactly 2 call sites in one file.

**PR:** PR6 (#316), PR11 (this round)

## PR8 — `RunStatus` enum + atomic transition (SE3)

**Date:** 2026-07-14
**Finding IDs:** SE3, SE4, SE5, SE7
**Decision:** Introduce `RunStatus(StrEnum)` with a `_VALID_TRANSITIONS` table and `RunRepository.transition(run_id, to_status, *, expected_from=...)` that enforces legal transitions atomically.

**Rationale:** The old ad-hoc string state machine (`"running"`/`"failed"`/`"succeeded"`/`"interrupted"`/`"cancelled"` as bare literals) was checked in 5+ places with no single owner. A run could be flipped to "failed" by a stale-sweep AND a worker failure AND a lifecycle exception, racing on the same row. The enum + atomic transition writer eliminates the race and makes the state machine explicit. `PlanExecutionResult` was also introduced so the coordinator no longer re-queries state the executor already computed (SE4).

**PR:** PR8 (#319)

## PR9 — Store/API cleanup scope reductions (A3, A5)

**Date:** 2026-07-14
**Finding IDs:** A3, A5
**Decision:** Scope reductions from the original plan:
- **A3 (route business logic):** Only 3 of 6 proposed relocations were done. `NodeTypeRegistry` and `ProjectListService` were not created because they would add indirection without removing complexity.
- **A5 (typed repo returns):** Only the `_value` polymorphic helper was deleted. Full typed hydration of all repos is deferred — 5 repos return dicts, no `Branch` domain class exists, and hydrating typed objects for all 5 is a cross-cutting change that moves complexity rather than reducing it.

**Rationale:** The safe, complexity-reducing subset was done. Full typed hydration is a follow-up ticket.

**PR:** PR9 (#320)
**Follow-up:** Full typed-domain repo hydration; `RunRepository.finish()` legacy-wrapper removal; `RunScope` audit.

## PR9 — `active_step_id` column + schema migration (A7)

**Date:** 2026-07-14
**Finding IDs:** A7
**Decision:** Promote `active_step_id` from `runs.metadata_json` blob to a first-class `TEXT` column. Bump schema version 100→101. Add migration runner in `_schema_version.py`.

**Rationale:** An operational field queried by `RunCoordinator` was stored as JSON, accessed via `json.loads`/`json.dumps`, and could not be indexed/filtered. The column makes it a first-class queryable field.

**PR:** PR9 (#320)

## PR10 — Delete dead hooks instead of refactoring (F3, F6, F7)

**Date:** 2026-07-14
**Finding IDs:** F3, F6, F7
**Decision:** Delete `useRunWatch`, `useManualBinningReview`, and `useRunWatch.test.ts` entirely.

**Rationale:** Git archaeology revealed that `useRunWatch` was created in the v2 big-bang merge (`ea34656`, PR #197) as a port of the v1 `useRunProgress` hook, but was **never wired into any component** — the v2 `ProjectView` was built with plain `useQuery` (fetch-on-select, no polling). `useManualBinningReview` was created for the Phase 2 `ManualBinningEditorSpike` component, which was deleted in `7a6d68a` (issue #239) as throwaway spike cleanup, but the hook survived the deletion. Both hooks have had zero consumers for 12+ days. The review-013 findings analyzed dead code as if it were live; the correct fix is deletion, not refactoring. If a future ticket wants live run-polling, it should re-create the hook with react-query's `refetchInterval` at that point.

**PR:** PR10 (#321)

## PR11 — Cleanup round

**Date:** 2026-07-14
**Finding IDs:** All (verification)
**Decision:** Final cleanup round to close the sprint:
- Removed remaining `_raw` accesses in `feature_selection.py` and `build/export.py`.
- Moved `resolve_run_step` out of `collector.py` into `reporting/_resolve.py` to eliminate reverse imports from sections.
- Deleted unused `Repository` base class from `store/_base.py` (kept `_branch_filter` helper).
- Tightened `scripts/audit_quality.py` to count definitions not usages, skip docstrings/f-strings in status-literal check.
- Updated docs: decision log expanded, resolution table added to review 013, evidence-kinds and artifact-evidence-access docs updated.

**PR:** PR11 (this round)
