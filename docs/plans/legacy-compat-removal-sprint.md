# Legacy Compatibility Removal Sprint

Remove the now-redundant compatibility layers/shims from Cardre. The repo's
own ADR explicitly states the project has not launched, has no production
persisted plans, and does not need pre-launch persisted-plan compatibility —
so every shim that exists "for backwards compatibility" is dead weight that
adds active complexity and divergence risk.

The governing authority is **ADR 0003**
(`docs/adr/0003-no-legacy-plan-accommodation.md`):

> "Cardre has not launched and has never been used in production. No persisted
> plans exist in any store … backward compatibility with previously persisted
> plan data is not a constraint on development."

> "Development may freely break persisted-plan compatibility: rename node
> types, rename step ids, change canonical step ids, change params schemas,
> remove previously-supported parameter values, and reshape artifacts. No
> migration path for pre-existing plans is required."

## The Problems In One Sentence Each

1. **Shims nobody imports.** `cardre/store_schema.py` and
   `cardre/reporting/readiness.py` have zero live importers — pure dead code.
2. **Shim still in use by its own package.** `cardre/reporting/limitation_codes.py`
   is a shim still imported by `reporting/schema.py` and `reporting/collector.py`.
3. **Defence-in-depth migration code that is not load-bearing.**
   `ProjectStore._migrate_step_spec()` + `_LEGACY_NODE_TYPE_METHOD` rewrite
   legacy node types on every `get_version_steps()` call — the ADR calls this
   defence-in-depth, not load-bearing.
4. **Vestigial API fields.** `/node-types/{node_type}/schema` synthesizes
   `params_schema` and `defaults` from the first method, but the frontend
   editor builds forms from `methods[].params` and never reads those flat
   fields.
5. **Dual-manifest divergence.** `write_manifest()` writes a legacy
   `run_manifest` artifact AND a canonical `manifest.json`; the code itself
   says the canonical is authoritative while the legacy is "for backwards
   compatibility." Reporting reads the canonical; the sidecar API and
   evidence reader read the legacy — a live divergence bug waiting to bite.
6. **Evidence reader fallback heuristics kept alive by writer gaps.**
   `ArtifactEvidenceReader._legacy_match()` has 22 kind-specific branches
   that only run because 9 writers fail to emit `schema_version`, forcing the
   reader to fall through Phase 1 (schema match) to Phase 3 (heuristics).

## Target End State

- No import shims that re-export a renamed module.
- No read-time migration of legacy node types.
- No synthesized flat `params_schema`/`defaults` on the node-type schema
  endpoint — `methods[].params` is the single source of truth.
- One manifest per run: the canonical `RunManifest` model, written once,
  registered once as the `run_manifest` artifact, read by everyone.
- Every audited artifact writer emits `schema_version`; the reader resolves
  artifacts via Phase 1 schema match, and the corresponding
  `_legacy_match()` branches are gone.

## Design Principles

- **ADR 0003 is the licence to break things.** No migration paths are
  required. Compatibility shims can be deleted outright.
- **Smallest safe change per phase.** Each phase is independently mergeable
  and reviewable. No phase rewrites execution behaviour.
- **Preserve coverage, don't delete it.** When a test asserts an old shape,
  rewrite it to assert the canonical shape 1:1 before removing the old shape.
- **Additive before subtractive.** Add `schema_version` to writers (Phase 4)
  *before* removing the `_legacy_match()` branches that depend on it
  (Phase 5).
- **One PR per phase** through `scripts/pr-gate.sh` per `AGENTS.md`. CI must
  be green before human review.

## Pre-Requisites (must hold before Phase 1)

- `make preflight` passes on `main`.
- The venv is bootstrapped:
  `. .venv/bin/activate && pip install -e ".[sidecar,dev,test]"`.
- `ruff` is available (part of the `dev` extra).
- Branch off `main` for the first phase (each phase gets its own branch).

## Phase Sequence

| Phase | Title                                         | Depends on | Behaviour change? | Risk   |
|-------|-----------------------------------------------|------------|-------------------|--------|
| 1     | Shim + legacy-migration removal               | —          | No (dead code)    | Very low |
| 2     | Remove legacy API fields `params_schema`/`defaults` | —    | No (frontend ignores them) | Medium |
| 3     | Manifest consolidation (single canonical manifest) | 1    | **Yes** (consumers read canonical) | High |
| 4     | Close evidence writer `schema_version` gaps  | —          | No (additive metadata) | Low |
| 5     | Retire `_legacy_match()` branches             | 4          | No (Phase 1 now matches) | Medium |
| 6     | *(Deferred — not this sprint)* Facade removal | —          | —                 | —      |

**Sprint scope: Phases 1-5.** Phase 6 is captured here only to record what is
deliberately deferred and why.

Each phase has a dedicated document in `docs/plans/legacy-compat-removal/`:
- `phase-1-shim-removal.md`
- `phase-2-api-legacy-fields.md`
- `phase-3-manifest-consolidation.md`
- `phase-4-evidence-writer-schema-versions.md`
- `phase-5-legacy-evidence-branch-removal.md`
- `phase-6-deferred-facade-removal.md`

## Dependency Graph

```
Phase 1 ──────────────┐
                      v
Phase 2 (independent)  Phase 3 (needs 1 merged, riskiest)
Phase 4 (independent)
                      v
                      Phase 5 (needs 4)
```

- Phases 1, 2, 4 are **independently mergeable** and can be developed in
  parallel.
- **Phase 3 depends on Phase 1** being merged (both touch
  `cardre/store/project_store.py` and `plan_repo.py` is adjacent; Phase 3
  touches `run_lifecycle.py` and the manifest consumers — no file overlap
  with Phase 1, but landing 1 first keeps the riskiest change isolated).
- **Phase 5 depends on Phase 4** — writers must emit `schema_version` before
  the matching branches can be removed.

## Definition Of Done

The sprint is resolved only when **all** of the following hold:

- [ ] `cardre/store_schema.py`, `cardre/reporting/readiness.py`,
      `cardre/reporting/limitation_codes.py` are deleted.
- [ ] `cardre/reporting/schema.py` and `cardre/reporting/collector.py` import
      `LimitationCode` from `cardre.readiness.limitation_codes`.
- [ ] `_LEGACY_NODE_TYPE_METHOD` and `ProjectStore._migrate_step_spec()` are
      gone; `PlanRepository.get_version_steps()` returns `StepSpec` directly.
- [ ] ADR 0003's stale path reference (`cardre/store.py` →
      `cardre/store/project_store.py`) is corrected.
- [ ] `NodeTypeSchemaResponse` has no `params_schema`/`defaults` fields; the
      synthesis block is gone; the 14 test assertions are rewritten against
      `methods[0].params`.
- [ ] `frontend/src/api/schema.d.ts` and `openapi.json` are regenerated and
      `git diff --exit-code` clean.
- [ ] `write_manifest()` writes exactly one manifest; the canonical
      `manifest.json` is registered as the `run_manifest` artifact; the
      legacy artifact write is gone.
- [ ] Reporting collector, sidecar manifest route, and evidence reader all
      read the same (canonical) manifest.
- [ ] All 9 audited writers emit `schema_version` in artifact metadata.
- [ ] The 7 retired `_legacy_match()` branches are gone; remaining branches
      are only for not-yet-audited deferred-tier kinds.
- [ ] `ruff check --fix` clean.
- [ ] `make preflight` green.
- [ ] Each phase PR raised via `scripts/pr-gate.sh` and CI green.

## Out Of Scope (Deliberate — Phase 6, deferred)

Per the source report's explicit guidance, this sprint does **not**:

- **Delete `cardre/evidence.py`.** It re-exports the `cardre/_evidence/*`
  subpackage and has **62 import sites** (30 production, 32 test) across every
  node class, the reporting pipeline, the readiness checks, the comparison
  service, and all four sidecar routes. Deletion requires migrating every
  consumer to `cardre._evidence.*` first — a separate mechanical sprint. The
  migration path is recorded in `phase-6-deferred-facade-removal.md`.
- **Delete `cardre/nodes/__init__.py`.** It re-exports all node classes and has
  **41+ import sites** in `registry.py`, `cardre/__init__.py`, plan service,
  etc. Same mechanical-migration pattern; deferred.
- **Remove `_legacy_match()` branches for deferred-tier evidence kinds**
  (REPORT_BUNDLE, COMPARISON_ARTIFACT, FEATURE_SELECTION_EVIDENCE,
  RESAMPLING_EVIDENCE, HYPERPARAMETER_TUNING_EVIDENCE, ENSEMBLE_MODEL_ARTIFACT,
  EXPLAINABILITY_REPORT, FAIRNESS_REPORT, PROXY_RISK_REPORT,
  MANUAL_BINNING_OVERRIDES). These require their own writer `schema_version`
  audit first, which is out of scope for this sprint.

## Risks

1. **Phase 3 is the highest-risk phase.** The canonical manifest payload is
   structurally richer than the legacy one (`manifest_hash`, `plan_id`,
   `pathway_hash`, `diagnostics`, proper `RunManifestStep` fields). Every
   consumer that parsed the legacy shape must be re-validated. Mitigation:
   register the canonical first (3.2) and run the full test suite — any
   breakage is a consumer that depended on the legacy shape.
2. **Phase 2 test rewrite could lose coverage.** The 14 assertions verify
   param keys/enums/minima/defaults. Mitigation: map each assertion 1:1 to a
   `methods[0].params` assertion before deleting the synthesis.
3. **Phase 5 branch removal could regress if a writer is missed.**
   Mitigation: each branch removal is gated on (a) all writers for that kind
   emit `schema_version` and (b) a Phase-1 regression test exists. One PR per
   kind.
4. **Codegen freshness gate.** Phase 2 must regenerate `schema.d.ts` and
   `openapi.json` via `scripts/generate-openapi-types.py`; `make preflight`
   enforces `git diff --exit-code` on both generated files. Forgetting to
   regenerate fails CI.

## How To Run This Sprint

This sprint is designed for a smaller LLM to execute phase-by-phase. Each
phase document is self-contained and follows the same structure:

1. **Goal** — one sentence.
2. **Authority** — the ADR/report basis.
3. **Files** — exact files to read, modify, delete (with line numbers).
4. **Steps** — the minimal change, ordered.
5. **Verification commands** — exact shell commands to run.
6. **Definition of done for this phase** — checkbox list.
7. **Failure mode** — what to do if tests fail unexpectedly.

Rules for the executing agent:
- Run one phase at a time, in dependency order.
- Run `ruff check --fix` and `make preflight` before raising a PR.
- Raise one PR per phase via `scripts/pr-gate.sh`.
- On a red gate, read `.opencode/pr-gate-logs/<pr>/<job>.log`, fix, push,
  re-run. Do not ask the user to review a red PR.
- Commit messages: `chore(legacy-removal-N): <title>` (or
  `refactor(legacy-removal-N): ...` for Phase 3).
- Do not touch files outside the phase's explicit file list without
  justifying it against the phase's goal.