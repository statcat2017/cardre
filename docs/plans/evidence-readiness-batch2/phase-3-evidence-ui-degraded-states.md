# Phase 3 — EvidenceTab degraded states

## Goal

Make `EvidenceTab` distinguish **all** important evidence states and
render backend summaries as the primary content. Artifact IDs/hashes
demote to audit metadata. The component is built on the **existing
seven-state pattern** already proven in `ReadinessPanel.tsx`; this PR
applies the same shape to evidence.

This is a render PR, not a new feature PR. The data was enriched in
PR 2; this PR renders it.

## Context you must read first

- `frontend/src/components/inspector/EvidenceTab.tsx` (57 LOC today) —
  the file you are editing. It renders a flat list of
  `evidence_kind`, `artifact_id`, `logical_hash`, `media_type`. It
  handles only "no run", "loading", "no items", "list".
- `frontend/src/components/ReadinessPanel.tsx` (183 LOC) — **the
  reference implementation of the seven-state pattern**. Read it
  fully. Note its loading/null-branch/null-run/error/blocked/ready
  branches. Model EvidenceTab on this structure.
- `frontend/src/components/__tests__/ReadinessPanel.test.tsx` (222 LOC)
  — **the reference test pattern**. Each state has its own test case
  using MSW. Copy this structure for `EvidenceTab.test.tsx`.
- `frontend/src/hooks/useReportReadiness.ts` — the React Query hook
  shape. EvidenceTab will use a parallel hook (the existing
  `useStepEvidence` if it exists, or a new one modeled on this).
- `frontend/src/api/client.ts:257` — `getStepEvidence` (regenerated
  in PR 2 with the new fields). Do not hand-edit it.
- `frontend/src/types.ts` — type aliases come from the generated
  schema; do not redefine API shapes.
- `docs/adr/0006-generated-api-contract-as-frontend-boundary.md` —
  the no-handwritten-types rule.
- `docs/plans/evidence-readiness-batch2/phase-2-evidence-summary-dtos.md`
  — the DTO PR 3 consumes; know the `EvidenceStatus` enum
  (`available`, `partial`, `stale`, `missing`, `unsupported`) and the
  response-level `status` field.
- `docs/plans/evidence-readiness-batch2/README.md` — cross-cutting
  rules (MSW-only testing, 600-line ceiling, schema regen, no TODOs
  gating safety).

## Changes

### 1. Add an evidence hook

If `frontend/src/hooks/useStepEvidence.ts` does not exist, create it
modeled on `useReportReadiness.ts` (27 LOC). Key the query on
`(projectId, runId, stepId)`; reuse the React Query cache identity
already in use.

```ts
export function useStepEvidence(
  projectId: string | null,
  runId: string | null,
  stepId: string | null,
) {
  return useQuery({
    queryKey: ["step-evidence", projectId, runId, stepId],
    enabled: !!projectId && !!runId && !!stepId,
    queryFn: () => api.getStepEvidence(projectId!, runId!, stepId!),
    staleTime: 30_000,
  });
}
```

Reuse the same `staleTime` convention as ReadinessPanel (don't pick a
new number). `useQuery` exposes `isError`, `error`, `isLoading`,
`isFetching`, `data` — these power the seven states.

### 2. Define a local evidence-state type

```ts
type EvidenceTabState =
  | "no-run"
  | "loading"
  | "load-failed"
  | "no-evidence"
  | "stale"
  | "partial"
  | "available";
```

Derive the state from a combination of: `runId == null` → no-run;
`isLoading` → loading; `isError` → load-failed; `data == null` or
`data.items.length === 0` → consult `data.status` for `MISSING` → no-evidence;
`data.status === "STALE"` → stale; `data.status === "PARTIAL"` → partial;
else → available.

This mirrors `ReadinessPanel`'s explicit-state derivation but
incorporates the `EvidenceStatus` enum from PR 2's response.

### 3. Render the seven states

Follow `ReadinessPanel.tsx`'s structure: each state has its own
explicit branch and copy. Suggested copy —TextEdit during
implementation, but keep these distinct messages:

| State | Copy |
|---|---|
| no-run | "No run yet — evidence is produced when this step runs." |
| loading | "Loading evidence…" (with the same spinner pattern as ReadinessPanel) |
| load-failed | "Evidence could not be loaded." + the `error` message if `error.message` is safe to display (text, not a stack trace). |
| no-evidence | "No evidence found for this step." + the canonical step hint from the response. |
| stale | "Current evidence is stale — upstream inputs have changed." |
| partial | "Partial evidence — some expected artifacts are missing." + list of which expected artifacts are absent (driven by per-item `status=MISSING` from PR 2). |
| available | Summary cards, primary content. |

### 4. Design the evidence card

Each evidence item renders as a card, primary content first:

```
WOE/IV evidence
Current · 12 variables · IV range 0.18 – 0.42 · 2 warnings
Top IV: income_band 0.42, age_band 0.31
Warnings: 2 variables had null event rate during binning.

Audit:
hash: abc123…    artifact_id: art-…    created: 2026-06-23T10:14Z
```

Card layout rules:

- **First line**: evidence kind title (e.g. "WOE/IV evidence", "Validation
  metrics", "Manual binning") — derive from `evidence_kind`. Add a
  shared `frontend/src/utils/evidenceLabels.ts` mapping kind → label.
- **Status badge**: one of `Current`, `Stale`, `Partial`, `Missing`,
  `Unsupported`. Reuse the badge helper from PR 3's shared enum.
- **Summary line**: derived from the `summary` dict (PR 2). Render
  short domain summaries first — IV range, variable count, Gini/KS,
  row counts, etc. as a single human-readable line per item type.
- **Warnings block**: list each string from the item's `warnings`
  array; collapse if more than three (show "+N more").
- **Audit metadata**: artifact_id, logical_hash, created_at. Smaller
  font, indented, always visible but never the first thing the eye
  lands on.
- **Unsupported items**: render with an "Unsupported" badge and
  `summary.unsupported_kind` true → "This artifact kind has no summary
  yet." Do not drop the card.

### 5. Demote artifact IDs and hashes

The existing UI renders `artifact_id`, `logical_hash`, `media_type` as
the primary content. Invert them: only the audit section shows them, and
they are prefixed `hash:` / `artifact_id:` rather than presented as the
title.

This is the launch-evidence UX fix — artifact IDs are audit metadata,
not the first thing a modeller needs.

### 6. Share the state badge with ReadinessPanel

If `ReadinessPanel`'s status badge style is reusable, extract it to
`frontend/src/components/StatusBadge.tsx`. If it's tightly coupled to
readiness copy, duplicate the small badge component for now — PR 0's
readiness consolidation is backend-side; the FE doesn't share a state
enum between readiness and evidence (different domains). Do not force a
shared status enum across the two; they mean different things.

## Tests

Create `frontend/src/components/inspector/__tests__/EvidenceTab.test.tsx`
modeled on `ReadinessPanel.test.tsx`. One test per state, MSW-driven:

1. **`renders no-run state when runId is null`** — render EvidenceTab
   with `runId=null`; assert "No run yet" copy. No MSW handler fires
   (or the handler must not be hit — assert via
   `onUnhandledRequest: "error"`).
2. **`renders loading state`** — MSW handler delays; assert spinner /
   "Loading evidence…" copy.
3. **`renders load-failed state`** — MSW returns 500; assert "Evidence
   could not be loaded." and that the error message is shown if safe.
4. **`renders no-evidence state`** — MSW returns
   `items=[], status="MISSING"`; assert "No evidence found" copy.
5. **`renders stale state`** — MSW returns items with
   `status="STALE"` (or response-level `status=stale`); assert the
   "stale" badge and copy.
6. **`renders partial state`** — MSW returns a mix where the
   response says `status=PARTIAL`; assert "Partial evidence" copy and
   that absent expected items are listed.
7. **`renders available evidence with summary`** — MSW returns a WOE/IV
   item with `summary={"selected_variable_count":12,"iv_min":0.18}`,
   etc.; assert "12 variables", "IV range 0.18 – 0.42" rendered; assert
   the artifact_id is in the audit section, not the title.
8. **`renders warnings`** — MSW returns an item with a non-empty
   `warnings` array; assert the warnings block renders.
9. **`renders unsupported kind safely`** — MSW returns an item with
   `status=UNSUPPORTED`, `summary={"unsupported_kind":true}`; assert
   "Unsupported" badge and fallback copy.

All tests use MSW. Do not mock the `api` module directly. The test
setup at `frontend/src/test/setup.ts` uses
`onUnhandledRequest: "error"` — every endpoint EvidenceTab
mounts/touches on mount must have a handler.

## Acceptance criteria

- `EvidenceTab` distinguishes all seven states explicitly; no state
  falls through to a generic render.
- Evidence summaries are the primary content; artifact_id /
  logical_hash / media_type appear only in an audit section.
- Per-item `status` (`Current` / `Stale` / `Partial` / `Missing` /
  `Unsupported`) badges render based on the `EvidenceStatus` enum from
  PR 2.
- Warnings render per card with collapse for >3 entries.
- Unsupported artifact kinds render safely (not dropped) with an
  explicit "Unsupported" badge.
- `EvidenceTab.tsx` is under 600 LOC; expect ~250–350 LOC including
  the card. Extract the card to
  `frontend/src/components/inspector/EvidenceCard.tsx` if it
  helps. Shared labels go in `frontend/src/utils/evidenceLabels.ts`.
- `EvidenceTab.test.tsx` exists with one test per state, all passing.
- `npm test` passes in `frontend/`; `npx tsc --noEmit` passes.
- No backend changes in this PR (schema already regenerated in PR 2).

## Out of scope for this phase

- Cross-state navigation tests between readiness and evidence — PR 4.
- Removing `ReadinessPanel.tsx:114-116`'s disclaimer — PR 4.
- New evidence kinds beyond what PR 2 surfaced.
- A "Recheck evidence" button — only add if ReadinessPanel's recheck
  pattern transfers directly and is demanded. Default: omit.