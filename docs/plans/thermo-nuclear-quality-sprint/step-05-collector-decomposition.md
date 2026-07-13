# PR5 — Decompose reporting collector into section registry

**Findings:** T5 (collector), R1, R2, R3, R5, R6
**Batch:** E (parallel with PR6, PR7)
**Depends on:** PR3c (collector `_raw` removal), PR2 (typed diagnostics)
**Behaviour change:** No (golden report diff must pass)

## Goal

Decompose the 1337-line god-class `ReportCollector` into a registry-driven
`SectionCollector` design. After this PR, `collector.py` < 500 lines, the
~20 `_collect_*` methods live as small focused collectors in a
`reporting/sections/` package, and `collect()` is a single loop. Also
drive `readiness/check.py` from a table (R1), convert `readiness/dto.py`
to Pydantic (R2), tighten `report_mode` to `Literal` (R3), make
`report_status` a computed property (R5), and delete the renderer's
hardcoded default fallback (R6).

**This is a pure structure refactor.** The golden report bundle diff
(PR0) must pass — report output is byte-for-byte compatible (except for
intended schema improvements like `report_status = "blocked"` when
blocker limitations exist, which is an intended fix, not a regression).

## Tasks

### T5 — Collector decomposition (registry-driven)

1. Define a `SectionContext` dataclass that carries everything a section
   collector needs, so the protocol has a single uniform `build(ctx)`
   signature regardless of how many refs a section consumes:
   ```python
   @dataclass(frozen=True)
   class SectionContext:
       bundle: ReportBundle
       resolved: dict[str, ResolvedStepRef]      # all resolved refs
       run: dict[str, Any]                        # run row
       manifest_digest: ManifestDigest
       plan_version_id: str
       report_mode: ReportMode
       store: ProjectStore
       reader: ArtifactEvidenceReader
       add_limitation: Callable[[Limitation], None]
   ```

2. Define a `SectionCollector` protocol in
   `cardre/reporting/sections/__init__.py` with a single `build(ctx)`
   method. Sections that need a ref pull it from `ctx.resolved` by their
   `canonical_step_id`; sections that need no ref (champion, dataset_roles,
   artifacts, run_status, reproducibility) ignore `ctx.resolved`:
   ```python
   class SectionCollector(Protocol):
        canonical_step_id: str | None   # None for non-step sections
        def build(self, ctx: SectionContext) -> None: ...
    ```

   The uniform single-arg shape avoids the shape mismatch that 7 of the
   23 `_collect_*` methods have (multi-ref, no-ref, or digest-dependent).

3. Migrate each of the 23 `_collect_*` methods into a small collector class
   in `cardre/reporting/sections/`. Group related diagnostics together;
   the 23 methods map to these files:
   - `sections/woe_iv.py` (`_collect_woe_iv`, `_collect_initial_woe_iv`)
   - `sections/score_scaling.py` (`_collect_score_scaling`)
   - `sections/model.py` (`_collect_model`, `_collect_model_limitations`,
     `_collect_modelling_metadata`)
   - `sections/validation.py` (`_collect_validation`)
   - `sections/cutoff.py` (`_collect_cutoff`)
   - `sections/exclusions.py` (`_collect_exclusion_summary`)
   - `sections/sample.py` (`_collect_sample_definition`)
   - `sections/manual_interventions.py` (`_collect_manual_interventions`)
   - `sections/redundancy.py` (`_collect_redundancy_review`)
   - `sections/selection.py` (`_collect_variable_selection`)
   - `sections/diagnostics.py` (`_collect_coefficient_sign_check`,
     `_collect_separation_diagnostics`, `_collect_vif_diagnostics`,
     `_collect_calibration_diagnostics`)
   - `sections/dataset_roles.py` (`_collect_dataset_roles`) — no ref
   - `sections/run_status.py` (`_collect_run_status`) — needs digest+run
   - `sections/reproducibility.py` (`_collect_reproducibility`) — needs digest
   - `sections/exports.py` (`_collect_implementation_artifacts`) — 3 refs
   - `sections/champion.py` (`_collect_champion`) — no ref, plan_id
   - `sections/artifacts.py` (`_collect_artifacts`) — no ref, returns list
   - `sections/pathway.py` — the inline pathway/branches loop in `collect()`
     (currently inlined, not a `_collect_*` method)

4. Register all section collectors in `SECTION_COLLECTORS:
   list[SectionCollector]`.

5. Rewrite `ReportCollector.collect()` as a single loop:
   ```python
   resolved = resolve_required_steps(...)
   ctx = SectionContext(bundle=..., resolved=resolved, run=run,
                        manifest_digest=manifest_digest, ...)
   for section in SECTION_COLLECTORS:
       section.build(ctx)
   ```
   The shared "resolve-or-limitation, read-or-limitation, map" triplet
   becomes a helper on `ReportCollector` (`_read_evidence(section, ctx)`)
   that step-driven sections call from inside `build`.

### R1 — `readiness/check.py` table-driven

1. Define `StepRequirement` dataclass:
   ```python
   @dataclass(frozen=True)
   class StepRequirement:
       canonical_step_id: str
       expected_schema: str
       expected_role: str | None
       missing_code: LimitationCode
       extra_check: Callable | None = None
   ```
2. Define `_STEP_REQUIREMENTS: dict[str, StepRequirement]` with one entry
   per canonical step currently in the 8-branch cascade.
3. Add `output_artifact_refs(store, run_step_id) -> list[ArtifactRef]`
   helper (replaces the 8 duplicated SQL+`any(...)` blocks).
4. Rewrite the per-step readiness loop as a table-driven loop. The 190-line
   cascade collapses to ~40 table + ~20 loop.
5. The `final-woe-iv` champion-mode monotonicity check becomes the single
   `extra_check` callable. Replace its bare `except Exception` with typed
   catches.

### R2 — `readiness/dto.py` Pydantic

1. Delete `ReadinessBlocker`/`ReadinessWarning` copy-paste twins.
2. Define a single Pydantic `ReadinessFinding` model:
   ```python
   class ReadinessFinding(BaseModel):
       severity: Literal["blocker", "warning"]
       code: LimitationCode  # validator rejects unknown codes
       message: str
       step_id: str | None = None
   ```
3. Convert `ReportReadinessResult` to Pydantic. Delete hand-written
   `to_dict` (use `model_dump(exclude_none=True)`).
4. Update callers. Known callers (verified):
   - `cardre/readiness/__init__.py:14-15` — re-exports `ReadinessBlocker`,
     `ReadinessWarning`; update to export `ReadinessFinding`.
   - `cardre/services/report_service.py:21,32` —
     `ReportGenerationError.__init__` takes `blockers: list[ReadinessBlocker]`;
     change to `list[ReadinessFinding]`.
   - `tests/test_reporting.py:18,90,92,94` — imports `ReportReadinessResult`
     and `ReadinessBlocker`; update to `ReadinessFinding`.
   - `cardre/readiness/check.py` — 30+ construction sites for
     `ReadinessBlocker`/`ReadinessWarning`; add `severity="blocker"`/`"warning"` arg.

### R3 — `report_mode: Literal["branch", "champion"]`

1. Define `ReportMode = Literal["branch", "champion"]` in
   `cardre/reporting/schema.py` (or `cardre/reporting/types.py`).
2. Replace `report_mode: str` across all **12** occurrences in **7** files
   (verified against the current repo, not the review's "8 sites"):
   - `cardre/reporting/schema.py` — `ReportBundle.report_mode` (Pydantic field)
   - `cardre/reporting/collector.py` — `ReportCollector.__init__` and
     `generate_report_bundle`
   - `cardre/readiness/check.py` — `check_report_readiness`
   - `cardre/readiness/dto.py` — `ReportReadinessResult.report_mode` (twice:
     attribute annotation and `__init__` param)
   - `cardre/services/report_service.py` — `check_readiness`,
     `generate_and_write`, `generate_report`
   - `cardre/services/export_service.py` — two signatures
   - `cardre/_evidence/models/manifest.py` — `ReportBundleEvidence` frozen
     dataclass field (note: dataclass, not Pydantic; `Literal` still applies)

### R5 — `report_status` computed property

1. Make `report_status` a computed property on `ReportBundle`:
   ```python
   @property
   def report_status(self) -> Literal["blocked", "complete_with_warnings", "complete"]:
       if any(lim.severity == "blocker" for lim in self.limitations):
           return "blocked"
       if self.limitations:
           return "complete_with_warnings"
       return "complete"
   ```
2. Delete the explicit assignment in `collector.py:339`
   (currently `bundle.summary.report_status = "complete_with_warnings" if self.limitations else "complete"`).
3. **This is an intended behaviour change:** reports with blocker
   limitations now correctly say `"blocked"` instead of
   `"complete_with_warnings"`. Update the golden report fixture if
   needed (or add a second golden fixture for the blocked case). Document
   this in the PR description as an intended fix, not a regression.

### R6 — Renderer default-fallback deletion

1. In `cardre/reporting/renderer_html.py:56-65`, delete the 13-key
   `RedundancyReviewInfo` default-shape fallback.
2. Either pass the `ReportBundle` model to the renderer (so missing
   sections are defaulted by Pydantic), or drop the fallback to `{}` and
   let the template guards handle falsiness.
3. Verify the template renders nothing for a missing
   `redundancy_review`.

## Acceptance criteria

- [ ] `wc -l cardre/reporting/collector.py` < 500.
- [ ] `reporting/sections/` package exists with one file per section
  family.
- [ ] `collect()` is a single loop over `SECTION_COLLECTORS` (no
  `if ref := ...: self._collect_X(...)` cascade).
- [ ] `rg 'elif canonical_step_id' cardre/readiness/check.py` returns 0
  (the cascade is gone).
- [ ] `wc -l cardre/readiness/check.py` < 250.
- [ ] `rg 'class ReadinessBlocker|class ReadinessWarning'
  cardre/readiness/dto.py` returns 0 (collapsed to `ReadinessFinding`).
- [ ] `rg 'report_mode:\s*str' cardre` returns 0 (it's `Literal`).
- [ ] `report_status` is a computed property; no explicit assignment in
  `collector.py`.
- [ ] `rg 'RedundancyReviewInfo\(' cardre/reporting/renderer_html.py`
  returns 0 (default-fallback block gone).
- [ ] Golden report bundle diff passes (except the intended
  `report_status = "blocked"` fix, which is documented).
- [ ] `rg 'except Exception' cardre/readiness/check.py` returns 0
  (narrowed).
- [ ] `ruff check` clean; `pytest tests/ -q` green.

## Do not

- Do not touch node files (that's PR6).
- Do not touch binning types (that's PR7).
- Do not touch services/execution (that's PR8).
- Do not change the report bundle *schema* — only the construction
  mechanism. The golden diff catches regressions.

## Already done by PR3c (do not redo)

PR3c (PR #312, merged) already introduced `ManifestDigest` and rewrote
`_read_canonical_manifest` to return it, and `_collect_run_status` /
`_collect_reproducibility` already consume it. The original step-05 draft
listed these as tasks; they are **complete** and must not be redone. PR5
only consumes `ManifestDigest` via `SectionContext`.

## Follow-up from PR0

The golden report bundle test (PR0) skips a broad set of values globally
(coefficients, metrics, score scaling, bin values, WOE/IV, points, scores)
because the 60-row synthetic pathway's random train/test split produces
genuinely non-deterministic output. This weakens the collector safety net:
a mis-mapped metric or limitation message would not be caught.

**This PR should make the golden report pathway deterministic enough to
remove the broad value skips.** Options:
- Use a fixed random seed for the train/test split in the pathway test.
- Use a larger deterministic dataset that produces stable bin boundaries.
- Replace suffix-based skipping with path-specific non-determinism for
  the few genuinely unstable fields.

The goal: by the end of this PR, `test_golden_report_bundle_matches`
should compare all scalar values exactly, with no suffix-based skips.