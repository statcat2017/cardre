# PR7 — Harden the binning override seam

**Findings:** T7 (remaining residue after PR2)
**Batch:** E (parallel with PR5, PR6)
**Depends on:** PR2
**Behaviour change:** No (round-trip tests must pass)

## Goal

Close the remaining correctness and maintenance risk around manual-binning
overrides. Align the golden override fixture with the live override schema,
prove merged bins round-trip losslessly through `LifecycleBinDefinition`,
and fix field-preservation bugs only if the new regression tests expose one.

**Note:** PR2 already landed most of the original T7 work: adapter collapse,
`normalize` as `dataclasses.replace(...)`, and typed
`LifecycleBinDefinition.apply_overrides(...)` / `validate_overrides(...)`.
What remains is not full global convergence of `BinDefinition` and
`LifecycleBinDefinition`. That broader refactor now has too much fan-out for
too little value. PR7 should stay narrow: harden the manual-binning seam and
lock in the behaviour with current-schema fixtures and regression tests.

## Tasks

### T7 — Harden the remaining manual-binning path

1. Replace the stale golden manual-override fixture with the current
   production override shape used by the manual-binning node. The fixture
   should use live action names such as `merge_bins`, `group_categories`,
   `reject_variable`, and `source_bin_ids` rather than the older
   `merge` / `group` / `reject` / `reorder` + `bins` shape.
2. Add a golden regression test that:
   - reads `tests/fixtures/golden_bin_definition.json` through
     `LifecycleBinDefinition.from_payload(...)`
   - applies current-schema manual overrides through
     `LifecycleBinDefinition.apply_overrides(...)`
   - round-trips the merged result through `to_payload()` →
     `from_payload()` and asserts losslessness
3. Expand the merged-bin assertions so they cover the fields most likely to
   regress at this seam: the already-fixed metrics (`kind`, `bad_rate`,
   `woe`, `iv`, `row_pct`) plus any special/other-bin metadata or extra
   payload fields represented in the fixtures or targeted test setup.
4. Only if the new tests expose a real loss, fix `apply_overrides(...)`
   locally in `cardre/engine/binning/definition.py`. Keep any production
   code change minimal and tied directly to the failing regression.

### Explicit non-goals

- Do not retire `BinDefinition` globally in this PR.
- Do not widen this into API/service/readiness DTO work for manual-binning
  overrides.
- Do not change override semantics: which bins are selected, how they are
  merged, or how WOE/IV are recomputed.

## Acceptance criteria

- [ ] `tests/fixtures/golden_manual_binning_overrides.json` matches the live
  manual-binning override schema used by production code.
- [ ] A regression test reads the golden bin definition through
  `LifecycleBinDefinition.from_payload(...)`, applies current-schema
  overrides, and proves the merged result round-trips losslessly through
  `to_payload()` → `from_payload()`.
- [ ] The merged-bin assertions cover the previously dropped metrics
  (`kind`, `bad_rate`, `woe`, `iv`, `row_pct`) and any special/other-bin
  metadata exercised by the fixture or targeted test setup.
- [ ] If production code changes are needed, they are local to
  `cardre/engine/binning/definition.py` or the directly-related fixture/test
  seam; no broad caller migration is introduced.
- [ ] `ruff check` clean; `pytest tests/ -q` green.

## Do not

- Do not change the bin-override semantics. The tests should harden the
  existing behaviour, not redefine it.
- Do not turn this into a repo-wide `BinDefinition` →
  `LifecycleBinDefinition` migration.
- Do not touch API/service/readiness files just to make override payloads
  "more typed" unless a regression test proves the current seam is wrong.
- Do not touch `reporting/collector.py` (that's PR5).
