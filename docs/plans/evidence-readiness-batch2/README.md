# Evidence and Readiness Hardening — Batch 2

## Purpose

Batch 1 proved the guided journey can be followed. Batch 2 must prove the
*evidence* behind the journey can be trusted. Cover weaknesses:

3. report readiness is still shallow;
5. evidence UI is too thin;
6. error/degraded states are underdeveloped.

Target outcome: a user can answer — *"What evidence exists for this step,
what is missing, is it current, and why is export blocked?"* — without
reading logs or guessing from generic artifact IDs.

## Scope boundary

This batch does **not** add new modelling functionality.

Allowed:

- extract a dedicated `cardre/readiness/` package (PR 0 refactor);
- make readiness branch-scoped and self-describing;
- enrich evidence DTOs with backend-generated summaries, staleness, and
  source step/branch attribution;
- extend `EvidenceTab` to distinguish seven explicit states;
- add tests proving readiness and evidence do not silently diverge.

Not allowed:

- new scorecard nodes;
- new ML methods;
- new report sections unrelated to existing artifacts;
- manual-binning UI redesign beyond evidence/readiness messaging;
- desktop packaging smoke tests.

## Validation context (read before starting)

Validated against the repo on 2026-06-23. Confirmed facts that shape the
work:

- The manual-binning readiness scan at `cardre/reporting/readiness.py:241-254`
  is **not branch-scoped**. It iterates `store.get_plan_version_steps()`
  linearly and matches `canonical_step_id == "manual-binning"` or
  `node_type == "cardre.manual_binning"`. The same file *already* uses
  `resolve_required_steps` (`cardre/step_id.py:77`) for the WOE/IV checks
  (`readiness.py:174-217`). The fix is local: route the manual-binning
  check through `resolve_required_steps`, the same function the file
  already imports.
- `ReadinessBlocker` / `ReadinessWarning` (`cardre/reporting/readiness.py:36-71`)
  **do not carry `step_id`**. `ReadinessItem.step_id`
  (`sidecar/models.py:558-574`) exists on the DTO but is always
  serialised as `None`. `ReadinessPanel.tsx:135-146` and
  `ReadinessPanel.test.tsx:105-130` already handle `step_id` correctly —
  the frontend is waiting on the backend.
- **Two readiness producers diverge structurally.** TopBar reads
  `guidance.report_readiness` from `/workflow-guidance`
  (`cardre/services/workflow_guidance_service.py:294-317`, with
  `report_mode="branch"` hard-coded and `"step_id": None` hard-coded in
  the dict literal at `:308,312`). ExportPanel/ReadinessPanel read from
  `/report-readiness`. `ReadinessPanel.tsx:114-116` literally prints a
  disclaimer. Any consistency test (PR 4's stated goal) is meaningless
  while this duplication exists. PR 0 resolves it; PR 4 then tests it.
- Staleness is already fully implemented at `cardre/staleness.py`:
  `step_is_stale` (`:47`) does recursive parent-`logical_hash`
  comparison; `staleness_detail` (`:142`) returns `StalenessDetail`
  (`:17`) with reason (`never_run` / `params_changed` /
  `node_version_changed` / `upstream_stale` / `upstream_artifact_changed`).
  **Reuse this.** Do not invent a new staleness notion in the evidence
  route. `physical_hash` is never consulted by staleness — do not surface
  it in the new DTO without an explicit UI use.
- "Partial evidence" is a **different axis** from staleness. It means
  "some expected artifact for this canonical step is absent." Derive it
  from `cardre/reporting/evidence_contract.py:18-49`
  (`REQUIRED_STEPS_BRANCH` / `REQUIRED_STEPS_CHAMPION` /
  `REQUIRED_STEPS_COLLECTOR`), **not** from `step_is_stale`. PR 2 must
  keep these axes independent in the DTO.
- The `summary: dict | None` field on `RunStepEvidenceItem`
  (`sidecar/models.py:752-766`) is populated from
  `ArtifactEvidenceSummary` (`cardre/_evidence/models.py:685-693`), which
  carries only `kind`, `schema_version`, `source_artifact_id` — no
  domain content. The per-evidence-type summary builders PR 2 adds are
  genuinely new code; put them in `cardre/_evidence/summaries.py`
  (dispatch by `evidence_kind`), **not** inline in the route file
  (`sidecar/routes/evidence.py` is 68 lines and must stay thin).
- `EvidenceTab.tsx` is **57 lines today** and renders a flat list
  (`frontend/src/components/inspector/EvidenceTab.tsx:33-54`). It handles
  none of the seven states this batch requires. **The seven-state
  pattern already exists in `ReadinessPanel.tsx` and is fully tested in
  `ReadinessPanel.test.tsx`.** Model the new EvidenceTab states on that
  existing component; do not reinvent.
- `MISSING_WOE_IV_EVIDENCE_V1` is emitted by **both**
  `cardre/reporting/collector.py:321` and `cardre/reporting/readiness.py:213`.
  A report can succeed-with-limitation while readiness blocks. PR 4 must
  add an assertion that collector-emitted blocker-level limitation codes
  are a subset of readiness blockers; otherwise the consistency tests
  will race.
- `cardre/reporting/collector.py` (716 LOC) and
  `cardre/services/workflow_guidance_service.py` (647 LOC) are **already
  over the 600-line CI ceiling**. PR 0's readiness-package extraction
  must move the readiness-specific code out of `workflow_guidance_service.py`
  without growing `collector.py`.
- Frontend framework: vitest + `@testing-library/react` + MSW. Test setup
  in `frontend/src/test/setup.ts` uses `onUnhandledRequest: "error"` —
  every endpoint a test mounts must be mocked. The MSW server lives at
  `frontend/src/test/server.ts`.
- ADR 0006: API response shapes come from
  `frontend/src/api/schema.d.ts`. Any backend model change requires
  regenerating with `python3 scripts/generate-openapi-types.py` and
  committing the diff in the same PR. The `check-api-contracts` CI job
  enforces this.

## PR sequence

| PR  | Title | Main outcome |
|-----|-------|--------------|
| PR 0 | Readiness package extraction | Single readiness producer; `collector.py` and `workflow_guidance_service.py` no longer speak readiness independently |
| PR 1 | Branch-scoped readiness with step_id attribution | Manual-binning readiness cannot be satisfied by the wrong branch; every blocker carries a navigable step_id; response echoes branch/run/mode/version context |
| PR 2 | Evidence summary DTOs and per-kind summarisers | Backend-generated domain summaries (IV range, row counts, Gini/KS, …), staleness, source-step attribution; `physical_hash` absent |
| PR 3 | EvidenceTab degraded states | Seven explicit states modeled on `ReadinessPanel`; artifact IDs demoted to audit metadata |
| PR 4 | Readiness/evidence consistency tests | Assert producer consolidation held; collector limitations ⊆ readiness blockers; blocker-to-evidence navigation works end-to-end |

Detailed LLM instructions live in:

- `phase-0-readiness-package-extraction.md`
- `phase-1-branch-scoped-readiness-and-step-ids.md`
- `phase-2-evidence-summary-dtos.md`
- `phase-3-evidence-ui-degraded-states.md`
- `phase-4-readiness-evidence-consistency-tests.md`

## Cross-cutting rules for all PRs

1. **No new modelling/evidence/scorecard scope.** If a change tempts you
   into `cardre/nodes/`, `cardre/executor.py`, or new artifact roles,
   stop and re-scope.
2. **Stay under the 600-line `.tsx` and `.py` ceiling** except for test
   files (per `scripts/check-line-counts.py` policy). Extract before
   approaching it. Reusable backend helpers go in `cardre/_evidence/` or
   `cardre/readiness/`; reusable frontend helpers go in
   `frontend/src/utils/` or `frontend/src/hooks/`.
3. **Reuse existing resolution and staleness modules.** Branch/canonical
   resolution is `cardre/step_id.py:resolve_required_steps`. Staleness
   is `cardre/staleness.py:staleness_detail`. Required-step contracts are
   `cardre/reporting/evidence_contract.py`. Do not reimplement these.
4. **No handwritten TS types for API shapes.** Regenerate
   `frontend/src/api/schema.d.ts` and commit the diff in the same PR.
5. **Every new frontend test uses MSW.** The `server` in
   `frontend/src/test/server.ts` is the only network seam.
6. **No TODOs that gate safety.** If a guard cannot be implemented,
   implement the prerequisite or remove the guard.
7. **Every readiness blocker that has a meaningful step target must
   populate `step_id`.** No blocker ships with `step_id: None` unless it
   genuinely has no step target (e.g. NO_CHAMPION_ASSIGNMENT).

## Definition of done for the batch

1. `cardre/readiness/` is a package; `workflow_guidance_service.py` and
   `sidecar/routes/reports.py` both call into it; neither re-derives
   readiness.
2. Report readiness is branch-scoped, including the manual-binning
   check.
3. Manual-binning readiness cannot be satisfied by the wrong branch.
4. Readiness response echoes `project_id`, `target_branch_id`, `run_id`,
   `report_mode`, `checked_at`, `plan_version_id`.
5. Every readiness blocker/warning with a meaningful step target carries
   a non-null `step_id`.
6. `EvidenceTab` shows backend-generated summaries, not bare artifact
   IDs. Artifact IDs/hashes remain visible but secondary.
7. `EvidenceTab` distinguishes no-run, loading, load-failed, no-evidence,
   stale, partial, and available states.
8. Readiness and evidence state cannot diverge silently: a single
   producer supplies both routes; collector blocker-level limitations are
   a subset of readiness blockers; tests prove it for the key launch
   blockers (manual-binning unreviewed, final-woe-iv missing, stale
   upstream).
9. Blocker → "Go to step" → `EvidenceTab` for that step explains the
   blocker. Tests assert the navigation.
10. No `.tsx` or non-test `.py` file exceeds the 600-line ceiling.
11. No new modelling scope is introduced.

## Priority

Do this before manual-binning UX polish. Batch 2 makes the product
trustworthy enough to launch; UX polish on top of untrustworthy evidence
is wasted effort.