# Phase 3 — Guided PathwayView section states

You are implementing **Phase 3** of the Guided Workflow Sprint
(`docs/plans/guided-workflow-sprint.md`). Phase 1 and Phase 2 are merged.
Phase 0 has landed the branch-owned step ID canonicalization used here.

Read first:
- `frontend/src/components/PathwayView.tsx`
- `frontend/src/components/StepCard.tsx`
- `frontend/src/config/stepDisplayMetadata.ts`
- ADR 0008 (phase vocabulary + `step_guidance` keyed by canonical ID).

## Goal

Make the central pathway scannable. A modeller should understand the state of
the build/validate journey **without opening every card**. This is
journey-led, not DAG-led — keep the simple grid.

Each section header shows: phase status (not started / in progress / complete
/ blocked), counts (complete / stale / blocked), and the next step in that
section. Each card surfaces `workflowGuidance.step_guidance[canonical_id]`.

## Data

PathwayView already takes `steps`, `selectedStepId`, `onStepSelect`,
`carriedForwardSteps`, `liveStepStatus`. Add:

```ts
interface Props {
  steps: StepStatus[];
  selectedStepId: string | null;
  onStepSelect: (stepId: string) => void;
  carriedForwardSteps?: Record<string, boolean>;
  liveStepStatus?: Record<string, string>;
  guidance?: WorkflowGuidance;  // new
}
```

Guidance is optional so Phase 3 remains safe to render legacy (when not yet
fetched). All chrome degrades gracefully when `guidance` is `undefined`.

`step_guidance` is keyed by canonical ID (ADR 0008). PathwayView already
uses `canonicalizeStepId` from Phase 0 when grouping. Reuse the same
canonicalization when looking up `step_guidance`.

## Section Header

For each section in `SECTION_ORDER`:

1. Aggregate per-step `readiness` (from `guidance.step_guidance[canonical_id]`
   for steps in this section). Fall back to `'not_started'` if guidance
   missing.
2. Derive section phase:
   - `blocked` if any step in section is `blocked`.
   - `in_progress` if any step is `stale`, `needs_config`, `ready`, or
     has `status == 'running'` via `liveStepStatus`.
   - `complete` if all steps are `complete`.
   - `not_started` if all are `not_run` and not blocked.
3. Render three counts: complete, stale, blocked.
4. Identify the next step in section — the first step in the local
   `SECTION_ORDER` ordering whose `readiness in {"needs_config", "ready",
   "stale"}` or whose `status == 'not_run'` and is unblocked. Show its label
   and a thin "Next" arrow.

Section header visual (sketch):

```
1. DEFINE POPULATION AND TARGET               [Blocked · 0/3 complete · 1 blocker]
   ✓ Metadata
   ✓ Sample definition
   ⚠ Exclusions need review                  → Next
```

The expandable lists under each header are **not** added in this phase — keep
the existing grid of `StepCard`s. Only the header changes.

## StepCard Changes

`StepCard` extends its current surface (status badge, stale pill) with a
small readiness row sourced from `guidance.step_guidance[canonical_id]`:

- `readiness == "complete"` → small ✓ in the section colour.
- `readiness == "stale"` → "Stale — upstream has changed" in plain
  English. **Use this copy verbatim**, not the technical "Stale - upstream has
  changed since last run" permutation. Replace the existing stale pill lines
  in `StepCard.tsx` and `StepInspector.tsx` with this canonical copy in
  Phase 4.
- `readiness == "needs_config"` → "Configuration required".
- `readiness == "ready"` → "Ready to run".
- `readiness == "blocked"` → blocker icon + first blocker code listed.
  Render the first matching `blockers.find(b => b.step_id ===
  canonical_id).message` (fallback to `b.code`).

Card also shows:
- `primary_action` from guidance as the card's clickable hint text.
- `evidence_kinds.length > 0` → "N evidence items" along the bottom.
  Derived purely from `evidence_kinds.length` — backend semantics already
  agreed in Phase 1.

Stale-and-running conflict: when `liveStepStatus[step.step_id] ==
"running"`, the readiness row is overridden by a spinner row "Running…".
`liveStepStatus` already exists.

## Selection Click

`onStepSelect` stays. Clicking a card selects the step in the right inspector
(Phase 4 makes that inspector journey-aware). The card does **not** trigger
runs directly — the single run CTA lives in TopBar (Phase 2).

## Files

| File                                          | Action | Content                                                                                       |
|-----------------------------------------------|--------|-----------------------------------------------------------------------------------------------|
| `frontend/src/components/PathwayView.tsx`     | Edit   | Accept `guidance` prop. Compute per-section phase + counts + next step. Render enhanced header. |
| `frontend/src/config/stepDisplayMetadata.ts` | Edit   | Add `sectionPhase(steps, guidance): SectionPhase` helper (pure function, exported for tests). |
| `frontend/src/components/StepCard.tsx`       | Edit   | Accept `guidanceForStep?: WorkflowStepGuidance` and `blockers?: WorkflowBlocker[]`. Render readiness row + plain-English stale copy + blocker hint + evidence count. |
| `frontend/src/components/ProjectView.tsx`    | Edit   | Thread `guidance` from `useWorkflowGuidance` into `<PathwayView guidance={guidance} />`. |
| `frontend/src/types.ts`                      | Edit   | Re-export `WorkflowStepGuidance`, `WorkflowBlocker` from `./api/schema`. |

## Sequence

1. Add `sectionPhase` pure helper in `stepDisplayMetadata.ts`.
2. Extend `StepCard` with the new optional props. Default behaviour (no
   guidance) preserved exactly.
3. Rewrite `PathwayView` section header to show phase chip + counts + next
   step.
4. Thread `guidance` from `ProjectView` → `PathwayView` → `StepCard`.
5. `npx tsc --noEmit` clean.

## Acceptance Criteria

A modeller scanning the pathway sees, without opening any card:

- For each section: not started / in progress / complete / blocked, the
  three counts, and the next step's label.
- For each card: readiness state, primary action hint, evidence count,
  blocker if any. Stale steps show "Stale — upstream has changed" in plain
  English.
- Live `running` steps still show the spinner, not a stale row.
- When `guidance` is undefined (e.g., before first fetch), no chrome is
  shown — PathwayView behaves exactly as before Phase 3.

Manual verification:
- A project with a fully completed build stream but unstarted validate
  stream: section 4 (Fit and scale) shows **complete**, section 5 (Validate
  and export) shows **not started**, JourneyHeader (Phase 2) shows phase
  validate.
- A project with a stale logistic regression: the Build Bins / WOE section
  is `in_progress`; the Fit and scale section is `in_progress` with a stale
  pill; no falsely "blocked" marking.

## Non-Goals

- StepInspector tab redesign (Phase 4).
- Vertical timeline visual (Phase 5b/leave for future).
- DAG canvas.
- Per-step button actions inside the card (the single CTA lives in TopBar).

## Drop-Dead Notes

- Use `canonicalizeStepId` (Phase 0) for every guidance lookup. Do not
  introduce a second canonicalization path.
- If a `step_id` in `step_guidance` cannot be matched to any step in
  `PathwayView`'s `steps` (e.g., expected canonical step not in this plan),
  the section header's next-step picker skips it silently; do not crash.
- Do **not** move StepInspector's existing manual-binning readiness block
  here. StepInspector owns it until Phase 5a.
- The blocker pill copy comes from the backend's `WorkflowBlocker.message`.
  Do not localise. ADR 0008 §3 forbids frontend phase reinvention; the same
  applies to blocker wording.