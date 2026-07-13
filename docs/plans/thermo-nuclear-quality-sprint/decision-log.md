# Sprint Decision Log

## PR10 — Frontend + Tauri cleanup (F1–F10)

### F3, F6, F7 — Delete dead hooks `useRunWatch` and `useManualBinningReview`

**Date:** 2026-07-14
**Finding IDs:** F3, F6, F7
**Decision:** Delete both hooks and `useRunWatch.test.ts`.

**Rationale:** Git archaeology revealed that `useRunWatch` was created in the v2 big-bang merge (`ea34656`, PR #197) as a port of the v1 `useRunProgress` hook, but was **never wired into any component** — the v2 `ProjectView` was built with plain `useQuery` (fetch-on-select, no polling). `useManualBinningReview` was created for the Phase 2 `ManualBinningEditorSpike` component, which was deleted in `7a6d68a` (issue #239) as throwaway spike cleanup, but the hook survived the deletion. Both hooks have had zero consumers for 12+ days. The review-013 findings analyzed dead code as if it were live; the correct fix is deletion, not refactoring. If a future ticket wants live run-polling, it should re-create the hook with react-query's `refetchInterval` at that point.

**PR:** PR10
