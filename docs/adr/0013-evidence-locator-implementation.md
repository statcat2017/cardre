# Evidence Locator — Implement ADR-0005 §3

## Status

Proposed

## Context

ADR-0005 §3 mandated: "Evidence locator is the single lookup path. `evidence_locator.py` (or a renamed equivalent) is the only place that implements branch/full-plan/across-plan fallback. Services call it with a named policy; they do not reimplement fallback logic."

This was never built. The fallback chain is duplicated across five locations:

1. `evidence_resolver._resolve_branch_then_full_then_plan` (lines 153–169)
2. `evidence_resolver._resolve_source_branch_then_full_then_plan` (lines 192–227)
3. `evidence_resolver._resolve_across_plan` (lines 260–278)
4. `staleness_service._step_is_stale` (lines 164–180)
5. `export_service.export_branch_audit_pack` (lines 176–202)

Additionally, `comparison_service._check_branch_readiness` (lines 56–60) uses a direct `get_latest_successful_run_step` path that bypasses `evidence_edges` entirely. `reporting/evidence_contract.find_evidence_for_canonical_step` is a partial helper that was never wired in (zero production imports).

A concrete bug: `evidence_resolver._resolve_branch_then_full_then_plan` queries `evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)` twice (lines 153 and 162) with identical arguments. The `evidence_edges` table has no `branch_id` column, so the second query returns identical results — the "branch then full-plan" fallback in the edge-walking path is a no-op.

Fingerprint comparison (`params_hash`, `node_type`, `node_version`) is duplicated in `evidence_resolver._matches_fingerprint` and inline in `staleness_service._step_is_stale` (lines 188–199).

## Decision

1. **New module: `cardre/evidence_locator.py`.** Owns the full edge-walking fallback through `evidence_edges` → `run_steps`, the fingerprint comparison, and the `ResolvedEvidence` assembly. At the package root (not inside `services/` or `reporting/`) to signal it is a shared primitive consumed by both layers.

2. **Interface:**
   ```python
   class EvidenceLocator:
       def __init__(self, store: ProjectStore) -> None: ...
       def resolve(
           self,
           plan_version_id: str,
           step_id: str,
           *,
           branch_id: str | None = None,
           plan_id: str | None = None,
           fingerprint_match: StepSpec | None = None,
       ) -> ResolvedEvidence | None: ...
   ```
   - Queries `evidence_edges` once per step (eliminates the duplicate query bug).
   - Accepts optional `StepSpec` for fingerprint matching — skips non-matching entries and continues fallback.
   - Returns `ResolvedEvidence` (run-step + edges + artifacts) or `None`.

3. **Incremental migration (four steps, verify after each):**
   - **Step 1:** Migrate `EvidenceResolver` — becomes a thin policy dispatcher (~50 lines) that calls the Locator and wraps results with diagnostics. Existing `test_evidence_resolver.py` must pass.
   - **Step 2:** Migrate `StalenessService._step_is_stale` — calls the Locator for edge-walking, keeps its own parent-output-hash comparison and recursive DAG walk. Existing `test_staleness_service.py` must pass.
   - **Step 3:** Migrate `comparison_service._check_branch_readiness` — from direct `get_latest_successful_run_step` path to edge-walking via Locator. Existing `test_comparison_service.py` must pass.
   - **Step 4:** Migrate `export_service` — same migration as comparison_service. Existing `test_exports.py` must pass.

4. **Dead code removed:**
   - `evidence_resolver._matches_fingerprint`, `._build_resolved_evidence`, `._find_run_step_from_plan_level_run` — move into the Locator.
   - `evidence_resolver._resolve_*` private methods — collapse into Locator calls.
   - `staleness_service._step_is_stale` edge-walking (lines 164–180) — replaced by Locator call.
   - `reporting/evidence_contract.find_evidence_for_canonical_step` — deleted (zero production imports).
   - Duplicate edge query (evidence_resolver lines 153+162) — eliminated by design.

5. **Direct tests for the Locator** using real `ProjectStore` + SQLite, covering: edge-walking fallback (branch → full-plan → plan-level), fingerprint matching (skip stale, continue fallback), missing evidence (return `None`), and `ResolvedEvidence` assembly (edges + artifacts bundled correctly).

## Consequences

- **Easier:** evidence resolution is auditable in one place. A change to fallback policy or fingerprint matching cannot drift across five consumers.
- **Easier:** the duplicate edge query bug is eliminated by design — the Locator queries edges once.
- **Easier:** new evidence consumers (e.g., governance export) get correct behavior by calling the Locator, not reimplementing fallback logic.
- **Easier:** the Locator is testable in isolation with synthetic evidence configurations — no need to construct a full executor or run lifecycle.
- **Harder:** the initial migration touches four consumers and must be verified incrementally. Each step is mechanical but must produce identical results.
- **Risk:** the direct-path consumers (`comparison_service`, `export_service`) currently bypass `evidence_edges`. Migrating them to edge-walking is a semantic change — results should be identical in practice (evidence_edges and run_steps are consistent), but edge cases may surface. Each migration step must be verified against its existing test suite.
