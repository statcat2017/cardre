# PR3a — Replace raw evidence reads in scoring export

**Findings:** T1 (scoring_export slice)
**Batch:** D (parallel with PR3b, PR3c)
**Depends on:** PR2 (needs typed properties on `ModelArtifactV1`/`ScoreScaling`)
**Behaviour change:** No

## Goal

Replace `_raw` dict access in `cardre/nodes/build/scoring_export.py` (47
hits) and `cardre/nodes/build/freeze.py` (10 hits) with typed attribute
access on `ModelArtifactV1`/`ScoreScaling`. This is one vertical slice of
the T1 consumer migration — scoring export only.

## Tasks

1. Read `cardre/nodes/build/scoring_export.py` in full. Identify every
   `getattr(typed, "_raw", {})` / `_raw.get(...)` / `raw.get(...)` access.
2. For each access, replace with the corresponding typed property added in
   PR2:
   - `scorecard_raw.get("base_score", 600)` → `scorecard.base_score`
   - `scorecard_raw.get("base_odds", ...)` → `scorecard.base_odds`
     (already parsed to float by PR2 — delete any inline `parse_base_odds`
     call)
   - `model_raw.get("coefficients", {})` → `model.coefficients_dict`
   - `model_raw.get("intercept", 0)` → `model.intercept`
   - etc. for all 47 hits.
3. Do the same for `cardre/nodes/build/freeze.py` (10 hits).
4. If any field accessed via `_raw` does not have a corresponding typed
   property on `ModelArtifactV1`/`ScoreScaling`, **do not add the property
   here** — that's PR2's job. Instead, flag the missing property, add it
   in PR2, and retry this PR. (In practice, PR2 should have covered all
   of them — this is a safety check.)
5. Run the golden report bundle diff. The scoring export output must not
   change.

## Acceptance criteria

- [ ] `rg '_raw' cardre/nodes/build/scoring_export.py` returns 0.
- [ ] `rg '_raw' cardre/nodes/build/freeze.py` returns 0.
- [ ] `rg 'getattr.*_raw' cardre/nodes/build/scoring_export.py
  cardre/nodes/build/freeze.py` returns 0.
- [ ] Golden report bundle diff passes (no behaviour change).
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] `scripts/audit_quality.py --json` shows the `_raw` count in
  `cardre/nodes/build/` dropped by 57 (47+10).

## Do not

- Do not touch `calibrate.py` (that's PR3b).
- Do not touch `collector.py` or `comparison_service.py` (that's PR3c).
- Do not add new typed properties — that's PR2. If a property is missing,
  PR2 is incomplete; fix it there.