# No Legacy Plan Accommodation

Cardre has not launched and has never been used in production. No persisted plans
exist in any store, and any plan created going forward will be the first plan
created in that store. Therefore, backward compatibility with previously
persisted plan data is not a constraint on development.

## Decision

Development may freely break persisted-plan compatibility: rename node types,
rename step ids, change canonical step ids, change params schemas, remove
previously-supported parameter values, and reshape artifacts. No migration path
for pre-existing plans is required.

## Context

This decision was made during the finalization of the OptBinning first-class
binning path plan (`docs/plans/optbinning-first-class-path-plan.md`). That plan
switches the default pathway from `cardre.fine_classing` to `cardre.binning`,
renames the canonical step id from `"fine-classing"` to `"binning"`, removes the
`quantile` prebinning option, and renames `ManualBinningSourceInfo` DTO fields.
Each of those would normally require a backward-compatibility strategy.

Because the project has never been deployed, no real plans exist to migrate. The
read-time `_LEGACY_NODE_TYPE_METHOD` map in `cardre/store.py:32-35` is retained
as defence-in-depth but is not load-bearing for this or any current phase.

## Considered Options

- **Maintain backward compatibility anyway**: keep dual canonical step ids in
  `ManualBinningService`, keep `quantile` in validation while hiding it from the
  schema, keep additive-only `ManualBinningSourceInfo` field renames. Costs
  complexity and code surface that defends against a state that does not exist.

- **Drop backward compatibility entirely** (chosen): rename cleanly, remove
  deprecated options outright, single canonical step id per concept. Simpler
  code, clearer intent, no dead compat branches. The risk is limited to any
  developer's in-flight experimental plans, which are disposable.

## Consequences

- Node types, step ids, canonical step ids, params, and artifact shapes may
  change without migration code or additive-only constraints.
- The `_LEGACY_NODE_TYPE_METHOD` read-time map in `cardre/store.py` is kept as
  defence-in-depth but is not treated as a compatibility contract.
- This ADR should be revisited when Cardre reaches its first real deployment.
  Once persisted plans exist outside developer machines, future changes must
  adopt a compatibility or migration strategy and a new ADR should record that
  shift.
- Tests that assert on specific step ids or node types (e.g. `fine-classing` in
  `tests/test_sidecar_api.py`, `tests/test_binning.py`) may be updated
  mechanically without preserving both old and new assertions.
- The OptBinning plan's PR 67 may switch `proof_pathway.py` to `cardre.binning`
  and update ~25 test files referencing `fine-classing` without keeping the old
  identifiers alive.
