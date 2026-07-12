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

1. Define a `SectionCollector` protocol in
   `cardre/reporting/sections/__init__.py`:
   ```python
   class SectionCollector(Protocol):
       canonical_step_id: str
       kinds: tuple[EvidenceKind, ...]
       def build(self, bundle, ref, evidence, add_limitation, *,
                 store, reader, plan_version_id, report_mode) -> None: ...
   ```
2. Migrate each of the ~20 `_collect_*` methods from `collector.py` into a
   small collector class in `cardre/reporting/sections/`:
   - `sections/woe_iv.py`, `sections/score_scaling.py`,
     `sections/model.py`, `sections/validation.py`,
     `sections/cutoff.py`, `sections/exclusions.py`,
     `sections/sample.py`, `sections/manual_interventions.py`,
     `sections/redundancy.py`, `sections/selection.py`,
     `sections/diagnostics.py`, `sections/dataset_roles.py`,
     `sections/run_status.py`, `sections/reproducibility.py`,
     `sections/exports.py`, `sections/pathway.py`,
     `sections/explainability.py`
3. Register all section collectors in `SECTION_COLLECTORS:
   list[SectionCollector]`.
4. Rewrite `ReportCollector.collect()` as a single loop:
   ```python
   resolved = resolve_required_steps(...)
   for section in SECTION_COLLECTORS:
       ref = resolved.get(section.canonical_step_id)
       if ref is None:
           self.limitations.append(missing_step_limitation(section))
           continue
       evidence = self._read_evidence(section, ref)
       section.build(bundle, ref, evidence, self.limitations.append, ...)
   ```
5. The shared "resolve-or-limitation, read-or-limitation, map" triplet
   becomes a helper on `ReportCollector` (`_read_evidence(section, ref)`).

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
4. Update callers.

### R3 — `report_mode: Literal["branch", "champion"]`

1. Define `ReportMode = Literal["branch", "champion"]` in
   `cardre/reporting/schema.py` (or `cardre/reporting/types.py`).
2. Replace `report_mode: str` across all 8 sites listed in review 013.

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
2. Delete the explicit assignment in `collector.py:402`.
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