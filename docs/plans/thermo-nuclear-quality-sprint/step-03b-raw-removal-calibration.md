# PR3b — Replace raw evidence reads in calibration

**Findings:** T1 (calibrate slice)
**Batch:** D (parallel with PR3a, PR3c)
**Depends on:** PR2 (needs typed properties on `ModelArtifactV1`)
**Behaviour change:** No

## Goal

Replace `_raw` dict access in `cardre/nodes/calibrate.py` (22 hits) and
`cardre/nodes/build/models.py` (6 hits) with typed attribute access on
`ModelArtifactV1`. This is one vertical slice of the T1 consumer
migration — calibration + model build only.

## Tasks

1. Read `cardre/nodes/calibrate.py` in full. Identify every
   `getattr(typed, "_raw", {})` / `_raw.get(...)` / `raw.get(...)` access.
2. For each access, replace with the corresponding typed property added in
   PR2:
   - `model.get("coefficients", {})` → `model.coefficients_dict`
   - `model.get("intercept", 0)` → `model.intercept`
   - `dict(getattr(typed_model, "_raw", {}))` → use typed properties
   - etc. for all 22 hits.
3. **Non-atomic in-place mutation fix:** `calibrate.py:506-510` mutates
   `model["intercept"]`/`model["coefficients"]` in place. After migrating
   to typed access, this should construct a new model dict (or typed
   object) rather than mutating. Coordinate with the T1c retirement plan
   — if `build_model_artifact` still returns a dict (PR2 does not change
   it), the mutation may need to stay as a dict update for now. Flag this
   for the model-artifact retirement PR.
4. Do the same for `cardre/nodes/build/models.py` (6 hits).
5. Run the golden report bundle diff. The calibration output must not
   change.

## Acceptance criteria

- [ ] `rg '_raw' cardre/nodes/calibrate.py` returns 0.
- [ ] `rg '_raw' cardre/nodes/build/models.py` returns 0.
- [ ] `rg 'getattr.*_raw' cardre/nodes/calibrate.py
  cardre/nodes/build/models.py` returns 0.
- [ ] Golden report bundle diff passes (no behaviour change).
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] `scripts/audit_quality.py --json` shows the `_raw` count in
  `cardre/nodes/` (calibrate + models) dropped by 28 (22+6).

## Do not

- Do not touch `scoring_export.py` or `freeze.py` (that's PR3a).
- Do not touch `collector.py` or `comparison_service.py` (that's PR3c).
- Do not change `build_model_artifact`'s return type (that's a later
  retirement PR).