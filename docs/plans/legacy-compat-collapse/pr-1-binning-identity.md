# PR 1 — Collapse automatic-binning identities to `cardre.automatic_binning`

**Sprint:** `docs/plans/legacy-compat-collapse.md`
**Depends on:** nothing
**Risk:** Medium
**Authority:** ADR 0003; user decision (rename to `cardre.automatic_binning`).

## Goal

One canonical automatic-binning node identity: `cardre.automatic_binning`. Delete the orphaned `AutoBinningFitNode` and its file. Rename `FineClassingNode` → `AutomaticBinningNode`, `cardre.fine_classing` → `cardre.automatic_binning`, step id `fine-classing` → `automatic-binning`. Manual binning (`cardre.manual_binning`) is untouched. Remove the dead `is_internal`/`is_deprecated` contract fields.

## Files to read first (do not edit)

- `cardre/nodes/build/bins.py` — `FineClassingNode` (lines 21-331) and `_run_fine_classing`. Note line 329: `from cardre.nodes.build.auto_binning_fit import _run_optbinning` — this is the ONLY live use of the orphaned file.
- `cardre/nodes/build/auto_binning_fit.py` — `AutoBinningFitNode` (orphaned, `is_internal=True`, never registered) + `_run_optbinning` (used by `FineClassingNode.run`) + `_resolve_train_input` helper. Note `_NUMERIC_TYPES` set at :42-45 and the manifest mislabel `"cardre_node_type": "cardre.fine_classing"` at :449.
- `cardre/nodes/contracts.py` — `NodeType` protocol; `is_internal` (:41) and `is_deprecated` (:42) are dead fields.
- `cardre/workflows/scorecard.py` — canonical steps; `fine-classing` step at :74-78; many downstream steps list `"fine-classing"` in their `parent_step_ids`.
- `cardre/nodes/registry.py` — registration lists; `FineClassingNode` imported at :178, registered at :224.
- `cardre/nodes/build/__init__.py` — re-exports `FineClassingNode`.
- `cardre/nodes/__init__.py` — re-exports `FineClassingNode` (:25, :109); docstring at :3 says "for backward compatibility" (misleading).
- `cardre/nodes/build/models.py` — `DummyFitNode` (:578, `is_internal=True` at :582), `NoopNode` (:618, `is_internal=True` at :619).

## Code instructions

### Step 1 — Move `_run_optbinning` + helpers into `bins.py`

Open `cardre/nodes/build/auto_binning_fit.py` and copy the following into `cardre/nodes/build/bins.py` (place after `_run_fine_classing`, before `ManualBinningNode`):
- The `_run_optbinning` function (lines 245-479).
- The `_resolve_train_input` helper (lines 236-242).
- The `_NUMERIC_TYPES` set (lines 42-45) — move to module level in `bins.py` as `_NUMERIC_TYPES`.

In the moved `_run_optbinning`, fix the class reference `AutoBinningFitNode._NUMERIC_TYPES` (was line 273) → the module-level `_NUMERIC_TYPES`.

Fix the manifest mislabel (was line 449):
```python
# was: "cardre_node_type": "cardre.fine_classing",
"cardre_node_type": "cardre.automatic_binning",
```

Delete the import at `bins.py:329`:
```python
# was: from cardre.nodes.build.auto_binning_fit import _run_optbinning
# now: _run_optbinning is in the same module — just call it directly
```
The existing `FineClassingNode.run` dispatch (`bins.py:324-331`) stays the same shape; only the import line goes away.

### Step 2 — Rename the class and identity

In `cardre/nodes/build/bins.py`:
- `class FineClassingNode(NodeType):` → `class AutomaticBinningNode(NodeType):`
- `node_type = "cardre.fine_classing"` → `node_type = "cardre.automatic_binning"`
- In `parameter_schema()`: `title="Fine Classing"` → `title="Automatic Binning"`
- In `_run_fine_classing` (line 353): `context.require_train_artifact("cardre.fine_classing")` → `context.require_train_artifact("cardre.automatic_binning")`

### Step 3 — Delete the orphaned file

Delete `cardre/nodes/build/auto_binning_fit.py` entirely.

### Step 4 — Update package exports

`cardre/nodes/build/__init__.py`: replace `FineClassingNode` with `AutomaticBinningNode` in:
- The import from `.bins` (line 2).
- `__all__` (line 35).

`cardre/nodes/__init__.py`: replace `FineClassingNode` with `AutomaticBinningNode` in:
- The import from `.build` (line 25).
- `__all__` (line 109).
- Rewrite the module docstring (line 3) — delete "for backward compatibility"; rephrase as:
  ```
  This module re-exports all node classes from subpackages as a convenience
  for the registry and tests.
  ```

### Step 5 — Update registry

`cardre/nodes/registry.py`: replace `FineClassingNode` with `AutomaticBinningNode` in:
- The import at line 178.
- The registration list at line 224.

### Step 6 — Remove dead contract fields

`cardre/nodes/contracts.py`: delete lines 41-42:
```python
is_internal: bool = False
is_deprecated: bool = False
```

Remove `is_internal = True` from:
- `cardre/nodes/build/models.py:582` (`DummyFitNode`)
- `cardre/nodes/build/models.py:619` (`NoopNode`)

(The `AutoBinningFitNode` one is gone with the deleted file.)

### Step 7 — Update canonical workflow

`cardre/workflows/scorecard.py`:
- Step id `"fine-classing"` → `"automatic-binning"` (the tuple at lines 74-78).
- `node_type` `"cardre.fine_classing"` → `"cardre.automatic_binning"` (line 75).
- Search the whole file for `"fine-classing"` and replace every occurrence with `"automatic-binning"` (these are `parent_step_ids` references in downstream steps: `initial-woe-iv`, `manual-binning`, etc.).

### Step 8 — Bulk-update tests

Run these replacements across `tests/` and `tests/fixtures/`:
- `cardre.fine_classing` → `cardre.automatic_binning`
- `FineClassingNode` → `AutomaticBinningNode`
- `"fine-classing"` (step id, in quotes) → `"automatic-binning"`
- Remove any `import` of `AutoBinningFitNode` / `auto_binning_fit` (no test should import the deleted file; if one does, delete that import line — `AutoBinningFitNode` was never registered and has no test value).

Verify with:
```bash
rg -n "cardre\.fine_classing|FineClassingNode|\"fine-classing\"|AutoBinningFit|auto_binning_fit|is_internal|is_deprecated" cardre/ tests/
# Must return zero matches.
```

### Step 9 — Update specific test files

- `tests/test_binning_node.py`: instantiate `AutomaticBinningNode`; assert `node_type == "cardre.automatic_binning"`.
- `tests/test_node_registry_tiers.py`: assert `cardre.automatic_binning` is a launch node; `cardre.auto_binning_fit` is not registered.
- `tests/test_deferred_nodes.py`: update the assertion at :67 (`"cardre.fine_classing" not in deferred` → `"cardre.automatic_binning" not in deferred`).
- `tests/conftest.py`: fixtures that seed `cardre.fine_classing` steps → `cardre.automatic_binning` (lines 63, 70).
- `tests/fixtures/golden_report_bundle.json`: step_type `"cardre.fine_classing"` → `"cardre.automatic_binning"`.
- `tests/test_api_manual_binning.py`, `tests/test_staleness_service.py`, `tests/test_branch_service.py`, `tests/test_branch_service_characterization.py`, `tests/test_api_typed_evidence.py`: update step id / node_type references.

### Step 10 — Add guard tests

Add to `tests/test_node_registry_tiers.py` (or a new `tests/test_canonical_contract.py`):
```python
def test_only_one_automatic_binning_node_registered():
    from cardre.nodes.registry import NodeRegistry
    reg = NodeRegistry.with_defaults()
    assert reg.has("cardre.automatic_binning")
    assert not reg.has("cardre.fine_classing")
    assert not reg.has("cardre.auto_binning_fit")
    assert not reg.has("cardre.binning")

def test_manual_binning_distinct_node():
    from cardre.nodes.registry import NodeRegistry
    reg = NodeRegistry.with_defaults()
    manual = reg.resolve("cardre.manual_binning")
    assert manual.category == "refinement"
    assert manual.node_type == "cardre.manual_binning"
```

## Verification

```bash
. .venv/bin/activate
rg -n "cardre\.fine_classing|FineClassingNode|\"fine-classing\"|AutoBinningFit|auto_binning_fit|is_internal|is_deprecated" cardre/ tests/
# Zero matches.
ruff check --fix
pytest tests/test_binning_node.py tests/test_node_registry_tiers.py \
       tests/test_deferred_nodes.py tests/test_launch_pathway.py \
       tests/test_api_manual_binning.py tests/test_staleness_service.py \
       tests/test_branch_service.py tests/test_canonical_contract.py -q
make preflight
scripts/pr-gate.sh
```

## Definition of done

- [ ] `cardre/nodes/build/auto_binning_fit.py` is deleted.
- [ ] `AutomaticBinningNode` with `node_type = "cardre.automatic_binning"` is the single registered automatic-binning node.
- [ ] `cardre.fine_classing`, `FineClassingNode`, `AutoBinningFitNode`, `"fine-classing"` appear nowhere in `cardre/` or `tests/`.
- [ ] `is_internal` and `is_deprecated` removed from `NodeType` and all node classes.
- [ ] Canonical workflow uses step id `automatic-binning` + node `cardre.automatic_binning`.
- [ ] Guard tests assert only `cardre.automatic_binning` is registered; `cardre.manual_binning` is distinct.
- [ ] `ruff check` clean; `make preflight` green; PR gate green.

## Failure mode

- **`_run_optbinning` import error after moving:** you left a stale `from cardre.nodes.build.auto_binning_fit import _run_optbinning` somewhere. Grep for it: `rg -n "auto_binning_fit" cardre/`. Delete the import; the function is now in `bins.py`.
- **`is_internal` attribute error:** a node class still sets `is_internal = True` but the field is gone. Grep: `rg -n "is_internal" cardre/`. Remove the line.
- **Test references old step id:** `rg -n "fine-classing" tests/` returns matches. Replace each with `"automatic-binning"`.
- **Optbinning test fails (missing optbinning package):** optbinning is an optional dep. Tests that exercise the `method="optbinning"` branch should be guarded with `pytest.importorskip("optbinning")`. Check `tests/test_binning_node.py` for the pattern.