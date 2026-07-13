# Canonical Evidence Resolution Contract

## Status

Proposed

## Historical note

PR4 deleted `EvidenceResolver` as dead layering. The surviving contract is that
`cardre/evidence_locator.py` owns the evidence lookup path and the branch-current
availability check consumed by launch coordination.

## Context

Cardre's reporting, readiness, comparison, export, and branch evidence services each define their own required canonical step lists, legacy alias maps, and evidence fallback policies. This has produced three concrete problems:

1. **Divergent required-step contracts.** `ReportCollector` requires `"logistic-regression"` as a canonical step. `check_report_readiness` and `ComparisonService` require `"model-fit"` and carry their own `LEGACY_CANONICAL_ALIASES` map to translate `"logistic-regression"` to `"model-fit"`. This means readiness can pass while the collector emits incomplete model evidence, or vice versa.

2. **Duplicated fallback chains.** Branch evidence, export, comparison, and step resolution each encode slightly different branch/full-plan/across-plan fallback behavior. `_check_branch_readiness` in `comparison_service.py` has its own multi-step fallback (branch-scoped lookup, then plan-level lookup, then staleness check). `_find_artifact` in the same file has another fallback. `BranchEvidenceResolver` has yet another. This is audit-sensitive drift: different services can reach different conclusions about whether evidence exists.

3. **Fake architectural boundary.** `BranchEvidenceResolver` accepts a `PlanExecutor` but never uses it, while importing `resolve_output_artifacts` from `executor`. This creates a circular architectural dependency and makes the layer boundary misleading.

## Decision

1. **One canonical evidence contract module.** A single module (e.g., `cardre/reporting/evidence_contract.py` or `cardre/evidence_contract.py`) owns:
   - The authoritative list of required canonical steps per report mode.
   - The legacy alias map (e.g., `"logistic-regression"` → `"model-fit"`).
   - The resolution policy for branch-scoped vs. full-plan evidence lookup.
   - The staleness-aware evidence existence check.

2. **All consumers import from the canonical module.** `ReportCollector`, `check_report_readiness`, `ComparisonService`, `BranchEvidenceResolver`, `ExportService`, and any future evidence consumer use the same contract. No local required-step lists, alias maps, or fallback chains.

3. **Evidence locator is the single lookup path.** `evidence_locator.py` (or a renamed equivalent) is the only place that implements branch/full-plan/across-plan fallback. Services call it with a named policy; they do not reimplement fallback logic.

4. **`resolve_output_artifacts` moves out of `executor.py`.** This function is used by non-executor services. It belongs in `evidence_locator` or store utilities. `BranchEvidenceResolver` no longer imports from `executor`.

5. **`BranchEvidenceResolver` drops the fake `PlanExecutor` dependency.** It receives only the store and the evidence contract.

## Consequences

- **Easier:** evidence resolution is auditable in one place. A change to required steps, aliases, or fallback policy cannot drift across services.
- **Easier:** new evidence consumers (e.g., a governance export endpoint) get correct behavior by importing the contract, not by reimplementing it.
- **Easier:** the architectural boundary between execution and evidence is clear. `executor.py` does not export evidence-lookup utilities.
- **Harder:** the initial migration requires updating four or five call sites and verifying they produce identical results. This is mechanical but must be tested carefully.
- **Risk:** if the canonical contract is too rigid, a future service with genuinely different evidence requirements may need to extend the contract rather than define its own. The contract should accept a policy parameter (e.g., report mode) rather than hardcoding one set of requirements.
