# PR1 — Centralize branch step resolution and low-risk dedup

**Findings:** T6, K3, K4, K5, SE6, SE8
**Batch:** B (parallel with PR4)
**Depends on:** PR0 (safety net)
**Behaviour change:** No

## Goal

Do only obviously safe deduplication: restore one shared branch step
resolver module, remove duplicate `ResolvedStepRef` forms, delete unused
enum aliases, extract `_json_ready` once, delete pure re-export files.
Immediate simplification with low semantic risk.

## Tasks

### T6 — Centralize branch step resolution

1. Create `cardre/branch_step_resolver.py` exporting:
   - `ResolvedStepRef` dataclass (the single canonical form — no leading
     underscore, no `artifact_ids` field)
   - `resolve_step_for_branch(store, plan_version_id, branch_id,
     canonical_step_id) -> ResolvedStepRef | None`
   - `resolve_required_steps(store, plan_version_id, branch_id,
     canonical_step_ids) -> dict[str, ResolvedStepRef]`
2. Update `cardre/reporting/collector.py` to import from the new module.
   Delete the private `_ResolvedStepRef`, `_resolve_step_for_branch`,
   `_resolve_required_steps`, and the `_to_schema_ref` converter. Have
   `reporting/schema.py:ResolvedStepRef` alias the canonical one (or keep
   the Pydantic version with a single `to_schema_ref()` method on the
   dataclass). Delete the manual reconstruction at `collector.py:527-533`.
3. Update `cardre/readiness/check.py` to import from the new module.
   Delete its `ResolvedStepRef`, `resolve_step_for_branch`,
   `resolve_required_steps`. Remove from `cardre/readiness/__init__.py`'s
   `__all__`.
4. Delete the `artifact_ids` field everywhere (never assigned).
5. Delete `LimitationCode.MISSING_RUN_MANIFEST_COLLECTOR` from
   `cardre/readiness/limitation_codes.py` (duplicate of
   `MISSING_RUN_MANIFEST`).

### K3 — Type domain aggregates

1. In `cardre/domain/run.py:115-121`, change `RunStepEvidenceView` fields:
   - `input_artifacts: list[Any]` → `list[ArtifactRef]`
   - `output_artifacts: list[Any]` → `list[ArtifactRef]`
   - `evidence_edges: list[Any]` → `list[EvidenceEdge]`
2. Introduce `ExecutionFingerprint` typed record:
   ```python
   @dataclass(frozen=True)
   class ExecutionFingerprint:
       params_hash: str
       node_type: str
       node_version: str
   ```
   Replace the dict-protocol reads in `cardre/evidence_locator.py:227-231`
   with typed attribute access.
3. Remove `_check_transition` from `cardre/domain/run.py`'s `__all__`.

### K4 — EvidenceKind alias removal

1. In `cardre/_evidence/kinds.py`, delete:
   - `WOE_APPLICATION_EVIDENCE` (alias of `APPLY_WOE_EVIDENCE`)
   - `SCORE_APPLICATION_EVIDENCE` (alias of `APPLY_MODEL_EVIDENCE`)
2. In `cardre/_evidence/schemas.py`, delete the matching
   `SCHEMA_WOE_APPLICATION_EVIDENCE` and `SCHEMA_SCORE_APPLICATION_EVIDENCE`
   aliases.
3. Remove the duplicate registrations in `EVIDENCE_PROFILES` and
   `EVIDENCE_ADAPTERS`.
4. Grep for callers of the deleted names and update to the canonical
   `APPLY_WOE_EVIDENCE`/`APPLY_MODEL_EVIDENCE`. **If any caller depends on
   the alias name for backward compatibility, keep the alias but document
   it with a `# compat alias` comment and stop double-registering.**

### K5 — Stale docstring rewrite

1. In `cardre/_evidence/adapters/_base.py:9-13`, delete the reference to
   `_legacy_match` and the "Phase 2" migration prose. Rewrite as a
   one-paragraph description of the current adapter design.
2. Do the same for `cardre/_evidence/adapters/__init__.py:1-11`.

### SE6 — Extract `_json_ready` once

1. Move `_json_ready` from `cardre/execution/executor.py:45-65` and
   `cardre/execution/step_runner.py:41-59` to
   `cardre/execution/fingerprints.py` (which already owns fingerprint
   construction).
2. Reconcile the two drifted variants (executor handles `tuple`/`set` as
   separate branches; step_runner merges `(list, tuple)` and `set`). Pick
   the more-correct one and delete the other.
3. Import from `fingerprints.py` in both `executor.py` and `step_runner.py`.

### SE8 — Delete `dispatcher.py`

1. Delete `cardre/execution/dispatcher.py` (24-line pure re-export of
   `worker.py`).
2. Add `RunDispatcher`, `ThreadRunDispatcher`, `SyncRunDispatcher` to
   `cardre/execution/__init__.py`'s re-exports if callers want
   package-level access.
3. Update any imports of `cardre.execution.dispatcher` to
   `cardre.execution.worker`.

## Acceptance criteria

- [ ] `cardre/branch_step_resolver.py` exists; both `collector.py` and
  `check.py` import from it.
- [ ] 3 `ResolvedStepRef` types collapsed to 1; `_to_schema_ref` deleted.
- [ ] `artifact_ids` field deleted from all `ResolvedStepRef` definitions.
- [ ] `MISSING_RUN_MANIFEST_COLLECTOR` deleted.
- [ ] `RunStepEvidenceView` fields typed as `list[ArtifactRef]` /
  `list[EvidenceEdge]`.
- [ ] `ExecutionFingerprint` record exists; `evidence_locator.py` uses
  typed access.
- [ ] `WOE_APPLICATION_EVIDENCE` / `SCORE_APPLICATION_EVIDENCE` deleted or
  documented as compat aliases with no double-registration.
- [ ] `_legacy_match` references gone from `_base.py` docstrings.
- [ ] `_json_ready` defined once in `fingerprints.py`; both `executor.py`
  and `step_runner.py` import it.
- [ ] `cardre/execution/dispatcher.py` does not exist.
- [ ] `ruff check` clean.
- [ ] `pytest tests/ -q` green.
- [ ] `scripts/audit_quality.py --json` shows the step-resolver count
  dropped to 1.
- [ ] Golden report bundle diff passes (no behaviour change).

## Do not

- Do not collapse the adapter classes (that's PR2).
- Do not add new typed evidence kinds/models (that's PR2).
- Do not migrate any `_raw` consumers (that's PR3*).
- Do not touch the evidence-reuse subsystem (that's PR4).