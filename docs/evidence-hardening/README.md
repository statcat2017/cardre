# Artifact Evidence Access Hardening — Sprint Plan

Resolves Cardre issue 1: artifact and evidence access is still too leaky.

Current state: ~4/10. Target: 9/10.

## Principle

> Artifacts are storage. Evidence is product meaning.
> Production code consumes evidence, not artifact files.

## Concrete to-do steps (10 PRs)

| Step | PR | Outcome | Depends on | Parallelisable? |
|------|----|---------|------------|-----------------|
| S1 | PR 1 | `scripts/audit_artifact_reads.py` strict audit script with classifications | — | Yes (foundational, do first) |
| S2 | PR 2 | Typed evidence models + profiles for every launch-critical EvidenceKind | — | Yes (independent of S1) |
| S3 | PR 3 | Core build nodes (`models.py`, `selection.py`, `freeze.py`, `export.py`) consume typed evidence; no raw JSON reads | S2 | Yes (one agent per file) |
| S4 | PR 4 | `cardre/nodes/validate/apply.py` consumes typed bin/model/score evidence | S2 | Yes |
| S5 | PR 5 | Advanced modelling nodes (`ensembles.py`, `explainability.py`, `fairness.py`, `feature_selection.py`) consume typed evidence; experimental kinds added | S2 | Yes |
| S6 | PR 6 | Services (`manual_binning_service.py`, `comparison_service.py`) and sidecar routes (`artifacts.py`, `method_summary.py`, `runs.py`) use typed summaries / byte streams only | S2 | Yes |
| S7 | PR 7 | `reporting/collector.py` and `nodes/build/export.py` (TechnicalManifestExportNode) consume typed evidence; `_get_artifact_json` removed | S3, S2 | After S3 |
| S8 | PR 8 | `tests/helpers/evidence_assertions.py` and high-value tests converted to evidence assertions | S2, S3, S4, S5 | After S3–S5 |
| S9 | PR 9 | Strict guardrail: delete `_EXISTING_VIOLATORS`, narrow `APPROVED_PATTERNS`, add inline-suppression policy, add CI jobs | All production steps done | Last |
| S10 | PR 10 | `docs/architecture/artifact-evidence-access.md` and guardrail failure message links to it | S9 | Last |

## Definition of done (must all be true)

1. `_EXISTING_VIOLATORS` deleted from `tests/test_artifact_guardrail.py`.
2. Production direct artifact reads outside approved low-level modules = 0.
3. Core build nodes consume typed evidence.
4. Apply/validation nodes consume typed evidence.
5. Reporting + technical manifest generation consume typed evidence.
6. Sidecar artifact summaries use typed summaries.
7. Tests use evidence assertions (raw assertions only in isolated serialization tests).
8. Every launch-critical artifact has EvidenceKind + profile + parser + tests.
9. Guardrail is strict and runs in CI.
10. Architecture documentation explains how to add/consume evidence.

## Parallelised batches

See [`sprint-execution.md`](./sprint-execution.md) for the recommended batched execution schedule.

## Per-step LLM instructions

Each file is a drop-in prompt for a subagent to execute one step:

- [`step-01-audit-script.md`](./step-01-audit-script.md)
- [`step-02-evidence-profiles.md`](./step-02-evidence-profiles.md)
- [`step-03-build-nodes.md`](./step-03-build-nodes.md)
- [`step-04-apply-validate.md`](./step-04-apply-validate.md)
- [`step-05-advanced-nodes.md`](./step-05-advanced-nodes.md)
- [`step-06-services-sidecar.md`](./step-06-services-sidecar.md)
- [`step-07-reporting-manifest.md`](./step-07-reporting-manifest.md)
- [`step-08-test-assertions.md`](./step-08-test-assertions.md)
- [`step-09-strict-guardrail.md`](./step-09-strict-guardrail.md)
- [`step-10-architecture-docs.md`](./step-10-architecture-docs.md)