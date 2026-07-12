# PR7 — Converge binning types

**Findings:** T7 (full convergence), T2 (if binning adapters remain)
**Batch:** E (parallel with PR5, PR6)
**Depends on:** PR2 (needs `BinDefinition` Any-shadow fix if PR2 did it;
otherwise this PR does it)
**Behaviour change:** No (round-trip tests must pass)

## Goal

Converge `BinDefinition` and `LifecycleBinDefinition` into one typed
representation. Ensure `apply_overrides` does not drop fields. Add
round-trip tests for merged bins.

**Note:** PR2 may already do some of T7 (the `BinDefinition` Any-shadow
fix, `normalize` → `dataclasses.replace`, and `apply_overrides` typed
rewrite). If PR2 covered T7 fully, this PR is a no-op or only adds
round-trip tests. If PR2 deferred any of T7, this PR finishes it. The
split exists because T7 is behaviour-sensitive (the lossy round-trip is
a correctness bug) and deserves its own PR with dedicated tests.

## Tasks

### T7 — Converge binning types

1. **If PR2 did not already do so:** Make `BinDefinition` a thin typed
   alias for `LifecycleBinDefinition` (re-export, or retire
   `BinDefinition`/`BinVariable` and update callers). Delete the
   `_lifecycle: Any` field and the `if self._lifecycle is not None: return
   self._lifecycle.X` forwarding.
2. **If PR2 did not already do so:** Replace `normalize` +
   `_normalize_var` with `dataclasses.replace(self,
   schema_version=SCHEMA_BIN_DEFINITION)`.
3. **If PR2 did not already do so:** Rewrite `validate_overrides` and
   `apply_overrides` to take and return `LifecycleBinDefinition` (not
   `JsonDict`). Construct merged bins via
   `dataclasses.replace`/`LifecycleBin(...)`.
4. **If PR2 did not already do so:** Update callers of
   `validate_overrides`/`apply_overrides` (likely in
   `cardre/services/manual_binning_service.py`) to pass/expect typed
   `LifecycleBinDefinition`.

### Round-trip tests (always do this, even if PR2 did the rest)

1. Use the golden bin definition + manual overrides fixtures from PR0
   (`tests/fixtures/golden_bin_definition.json`,
   `tests/fixtures/golden_manual_binning_overrides.json`).
2. Add a test that:
   - Reads the golden bin definition through `LifecycleBinDefinition.from_dict`
   - Applies the golden manual overrides via `apply_overrides`
   - Asserts the merged bins include ALL `LifecycleBin.from_dict` fields
     (`kind`, `woe`, `iv`, `bad_rate`, `row_pct` — the fields that were
     silently dropped before T7)
   - Round-trips the merged result through `to_dict()` → `from_dict()`
     and asserts losslessness
3. Add a property-based test (if `hypothesis` is available) or a
   parametric test with several override scenarios (no overrides,
   partial overrides, full overrides, edge cases like empty bins).

### T2 (binning adapters, if any remain)

1. If PR2 did not collapse all binning-related adapter classes into
   `AdapterSpec` entries, do so here. The binning adapters
   (`BinDefinitionAdapter`, `ManualBinningOverridesAdapter`, etc.)
   should be table entries, not classes, per PR2's T2 work.

## Acceptance criteria

- [ ] `BinDefinition` has no `_lifecycle: Any` field (or is retired).
- [ ] `normalize` is `dataclasses.replace(self, schema_version=...)`
  (one line).
- [ ] `apply_overrides`/`validate_overrides` operate on typed
  `LifecycleBinDefinition` (not `JsonDict`).
- [ ] Merged bins include all `LifecycleBin.from_dict` fields (no silent
  field-drop).
- [ ] Golden bin definition + manual overrides round-trip tests pass.
- [ ] `rg 'JsonDict' cardre/engine/binning/definition.py` returns 0 in
  `apply_overrides`/`validate_overrides` signatures (they take typed
  `LifecycleBinDefinition`).
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] `scripts/audit_quality.py --json` shows no binning adapter classes
  remain (if T2 applies).

## Do not

- Do not change the bin-override *semantics* (which bins are selected,
  how WOE is recomputed). Only change the *types* the functions operate
  on. The round-trip tests prove behaviour preservation.
- Do not touch node files (that's PR6).
- Do not touch `reporting/collector.py` (that's PR5).