# Batch 07d — Binning and Canonical-Pathway Migration

## Objective

Move binning and the canonical scorecard pathway to their settled domain-owned locations, then delete the obsolete `engine` and `workflows` package surfaces.

## Scope

- Move binning definitions, diagnostics, capabilities, WOE logic, and adapters to the locations prescribed by the target architecture.
- Move the canonical scorecard pathway to `cardre/domain/plans` and update catalogue, node, test, and documentation imports.
- Replace `domain/binning` forwarders with the canonical implementation and update every `cardre.engine` importer, including code still under `cardre/_evidence`; this is an import migration, not evidence-package relocation.
- Keep one canonical node type, step ID, parameter schema, and pathway per concept.
- Delete `cardre/engine` and `cardre/workflows` after every caller moves.

## Prohibited

- No forwarder modules, deprecated aliases, dual canonical IDs, or migration maps.
- No `ProjectStore` removal or execution-context porting; those are 07f and 07e.
- Do not preserve old persisted-plan shapes: ADR-0003 explicitly permits a clean cut.

## Acceptance

- A production search returns no `cardre.engine` or `cardre.workflows` imports.
- Binning, score-scaling, scoring-export parity, and golden fixture tests pass.
- Canonical-contract tests assert only the final pathway and identifiers.

## Enables

07c may delete `cardre/_evidence` only after this batch removes its dependency on the legacy binning package.
