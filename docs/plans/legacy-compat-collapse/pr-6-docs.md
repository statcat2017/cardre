# PR 6 — Mark legacy-compat-removal complete; supersede stale plans

**Sprint:** `docs/plans/legacy-compat-collapse.md`
**Depends on:** PR 5
**Risk:** Low (docs only — no code changes)
**Authority:** ADR 0003.

## Goal

Documentation only. Mark obsolete plans as historical/superseded; correct false claims; explain the canonical architecture. No code changes.

## Files to read first (do not edit)

- `docs/adr/0003-no-legacy-plan-accommodation.md`
- `docs/plans/legacy-compat-removal-sprint.md` + `docs/plans/legacy-compat-removal/phase-*.md`
- `docs/plans/optbinning-first-class-path-plan.md`, `optbinning-technical-implementation.md`, `optbinning-integration-plan.md`
- `docs/plans/thermo-nuclear-quality-sprint/decision-log.md`
- `docs/plan-reviews/013-thermo-nuclear-codebase-review.md`
- `docs/architecture/domain-model.md`, `node-registry.md`, `artifact-evidence-access.md`, `storage-and-migrations.md`
- `docs/reference/node-catalogue.md`, `evidence-kinds.md`
- `CONTEXT.md`
- `docs/plans/ml-scorecard-methods-implementation-plan.md`

## Code instructions

### Step 1 — Mark the legacy-compat-removal sprint complete

`docs/plans/legacy-compat-removal-sprint.md`: add a status banner at the very top (after the title line):
```
**Status: Completed (2026-07-14).** All six phases resolved; see
`docs/plans/legacy-compat-collapse.md` for the final canonical state.
```
Check off all Definition-of-Done items (lines 124-148) by changing `- [ ]` to `- [x]`.

### Step 2 — Mark phase docs complete

`docs/plans/legacy-compat-removal/phase-3-manifest-consolidation.md`: add after the title:
```
**Status: Completed via `docs/plans/legacy-compat-collapse.md` PR 5.**
```

`docs/plans/legacy-compat-removal/phase-6-deferred-facade-removal.md`: add after the title:
```
**Status: The `cardre/evidence.py` facade was deleted in Phase 1; the
`cardre/nodes/__init__.py` facade remains (live consumers — see
`docs/plans/legacy-compat-collapse.md` §6 "Remaining compatibility code").**
```

### Step 3 — Supersede the optbinning plans

`docs/plans/optbinning-first-class-path-plan.md`: add after the title:
```
**Status: Superseded.** The canonical automatic-binning node is
`cardre.automatic_binning` (not `cardre.binning`). `AutoBinningFitNode` is
deleted; `method` dispatch lives on `AutomaticBinningNode`. See
`docs/plans/legacy-compat-collapse.md`.
```

`docs/plans/optbinning-technical-implementation.md`: same superseded banner.

`docs/plans/optbinning-integration-plan.md`: same superseded banner.

### Step 4 — Correct false claims about FineClassingNode removal

`docs/plans/thermo-nuclear-quality-sprint/decision-log.md` line 62: the claim that PR318 removed `FineClassingNode`/`AutoBinningFitNode` from the registry is **false**. Add a correction note immediately after line 62:
```
> **Correction (2026-07-14):** PR318 did not remove `FineClassingNode` from the
> registry; it remained registered as `cardre.fine_classing`. The actual collapse
> happened in `docs/plans/legacy-compat-collapse.md` PR 1: renamed to
> `cardre.automatic_binning`, `AutoBinningFitNode` deleted.
```

`docs/plan-reviews/013-thermo-nuclear-codebase-review.md` line 994: same correction — add a note after the table row:
```
> **Correction (2026-07-14):** This claim was never executed. `FineClassingNode`
> and `AutoBinningFitNode` were not removed by PR6/PR318. The actual collapse
> happened in `docs/plans/legacy-compat-collapse.md` PR 1.
```

### Step 5 — Update ADR 0003

`docs/adr/0003-no-legacy-plan-accommodation.md`: preserve the reasoning; add a consequence note at the end of the "Consequences" section (after line 49):
```
- **Update (2026-07-14):** The canonical automatic-binning identity is
  `cardre.automatic_binning`. The `cardre.binning` rename described in this
  ADR was never executed; `cardre.automatic_binning` was chosen instead.
  `_LEGACY_NODE_TYPE_METHOD` (referenced at the old `cardre/store.py:32-35`)
  was deleted in the legacy-compat-removal sprint Phase 1. See
  `docs/plans/legacy-compat-collapse.md` for the final state.
```

### Step 6 — Update architecture docs

`docs/architecture/domain-model.md` line 60: update the `fine_classing` reference to `cardre.automatic_binning` (the `missing_policy` property is now on the `cardre.automatic_binning` node). Add a paragraph in the "Build Stream Workflow" section explaining the two-stage binning workflow (automatic initial → manual refinement) and why WOE/IV is recalculated after manual binning.

`docs/architecture/node-registry.md`: update any binning node references to `cardre.automatic_binning` + `cardre.manual_binning`.

`docs/architecture/storage-and-migrations.md`: update to reflect the single-baseline schema (no migration runner).

### Step 7 — Update reference docs

`docs/reference/node-catalogue.md` line 21: replace
```
| `cardre.fine_classing` | fit | Fine classing of variables (supports fine_classing and optbinning methods) |
```
with
```
| `cardre.automatic_binning` | fit | Automatic initial binning of variables (supports fine_classing and optbinning methods) |
```

`docs/reference/evidence-kinds.md`: remove `RUN_MANIFEST`, `WOE_APPLICATION_EVIDENCE`, `SCORE_APPLICATION_EVIDENCE` from the kind list.

### Step 8 — Update CONTEXT.md

`CONTEXT.md` "Build Stream Workflow" section (lines 67-82):
- Step 5 "Auto fine classing → bins ALL variables on train." → "Automatic initial binning (`cardre.automatic_binning`) → bins ALL variables on train."
- Step 9 "Manual bin editing / coarse classing → refines bins..." stays; add a note that the final WOE/IV (step 10's WOE transform uses the recalculated final WOE map).

### Step 9 — Remove `cardre_scaled_score` from the ml-scorecard plan doc

`docs/plans/ml-scorecard-methods-implementation-plan.md`:
- Line 183: remove `| cardre_scaled_score | Optional Cardre-created score scale from probability or log odds |` from the table.
- Line 278: remove `cardre_scaled_score` from the scored-columns list.

## Verification

```bash
rg -n "cardre\.fine_classing|AutoBinningFitNode|cardre\.binning" docs/
# Remaining matches must be in clearly-marked historical/superseded/correction
# sections only (the banners added in steps 3-5).
python3 scripts/check_doc_references.py
make preflight
scripts/pr-gate.sh
```

## Definition of done

- [ ] `legacy-compat-removal-sprint.md` marked complete with all DoD items checked.
- [ ] Phase 3 + Phase 6 docs marked complete.
- [ ] OptBinning plans marked superseded.
- [ ] False claims about FineClassingNode removal corrected.
- [ ] ADR 0003 updated with the canonical identity note.
- [ ] Architecture + reference docs use `cardre.automatic_binning`.
- [ ] `cardre_scaled_score` removed from the ml-scorecard plan doc.
- [ ] `make preflight` green (includes `check_doc_references`); PR gate green.

## Failure mode

- **`check_doc_references.py` fails:** it validates that doc references to source files/line numbers still resolve. If you referenced a specific line number that has shifted, update the reference or remove the line-number specificity. Read `scripts/check_doc_references.py` to understand what it checks.
- **`rg` finds `cardre.fine_classing` outside historical sections:** move the reference into a clearly-marked historical note, or update it to `cardre.automatic_binning` if it's a current-state description.