# Branch Evidence Policy Unification

## Status

Archived by PR4.

## Why this plan is archived

This plan was written for an implementation direction that kept
`EvidenceResolver`, `EvidencePolicyService`, branch evidence preparation, and
resolver-driven parent seeding as live seams.

PR4 chose the opposite direction and deleted the dead reuse subsystem.

The current architecture is:

- `cardre/evidence_locator.py` is the evidence-read seam.
- `EvidenceResolver` no longer exists.
- `prepare_branch_evidence`, `resolve_parent_evidence`,
  `check_to_node_current`, `BranchRunEvidence`, and `ShortCircuitResult` no
  longer exist.
- Launch does not support `run_to_node` execution.
- The only surviving launch-time policy check is the branch-current
  short-circuit on the locator-side seam.

## Source of truth

For the PR4 decision and the resulting target architecture, see:

- `docs/plans/thermo-nuclear-quality-sprint/reuse-decision.md`
- `docs/architecture/execution-and-staleness.md`
- `docs/adr/0004-single-run-lifecycle-atomic-finalisation.md`
- `docs/adr/0005-canonical-evidence-resolution-contract.md`
- `docs/adr/0013-evidence-locator-implementation.md`

Do not use the pre-PR4 resolver-based instructions that used to live here as
implementation guidance.
