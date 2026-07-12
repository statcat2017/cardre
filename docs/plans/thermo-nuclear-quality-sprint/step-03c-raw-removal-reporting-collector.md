# PR3c — Replace raw evidence reads in reporting collector

**Findings:** T1 (collector slice), R4
**Batch:** D (parallel with PR3a, PR3b)
**Depends on:** PR2 (needs typed diagnostics kinds + `ManualBinningOverrides`
model + typed properties)
**Behaviour change:** No

## Goal

Replace `_raw` dict access in `cardre/reporting/collector.py` (14 hits)
and `cardre/services/comparison_service.py` (8 hits) with typed attribute
access. Delete `_read_raw_json_by_step` (the parallel untyped reader) and
use the new typed diagnostics readers from PR2. Fix the
`reproducibility`/`run_status` split ownership (R4).

This is the reporting slice of the T1 consumer migration. It does NOT
decompose the collector into a section registry — that's PR5. This PR
only replaces `_raw` accesses in place; the structure stays the same.

## Tasks

### T1 (collector slice) — Remove `_raw`/duck-typing

1. Replace every `_raw` access in `collector.py` with typed attribute
   access:
   - `_collect_exclusion_summary`: use `ExclusionSummary.rules` (typed
     `list[JsonDict]`) instead of `raw.get("rows_before", 0)`.
   - `_collect_sample_definition`: use `SampleDefinition.sample_method` etc.
   - `_collect_variable_selection`: use `SelectionDefinition.selected`
     (map `SelectedVariable.variable`).
   - `_collect_model_limitations`: use the typed `ExplainabilityReport` field.
     If the typed model's `limitations: list[str]` is wrong for this use
     case (the collector expects dicts with `code`/`message`/`severity`/
     `accepted`), widen it to `list[LimitationItem]` — coordinate with PR2
     if a new field is needed.
2. Delete `_read_raw_json_by_step` (`collector.py:979-991`) and its 4
   callers. The `import json` inside the method body disappears. The 4
   `_collect_*_diagnostics` methods now do:
   ```python
   evidence = self.reader.read_step_output_optional(
       rs.run_step_id, EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS)
   ```
3. Delete the duck-typing in `_collect_manual_interventions`:
   `data.to_dict() if hasattr(data, "to_dict") else getattr(data, "_raw",
   data)` becomes `data.to_dict()` on the typed
   `ManualBinningOverrides` model from PR2.
4. Do the same for `cardre/services/comparison_service.py` (8 `_raw`
   hits).

### R4 — Fix `reproducibility`/`run_status` split ownership

1. Make `_read_canonical_manifest` return a small `ManifestDigest`
   dataclass instead of mutating `bundle`:
   ```python
   @dataclass
   class ManifestDigest:
       manifest_hash: str | None
       pathway_hash: str | None
       execution_mode: str | None
       target_step_id: str | None
       in_scope_step_ids: list[str]
       limitations: list[Limitation]
   ```
2. `_collect_run_status` consumes the digest's `execution_mode`/
   `target_step_id`/`in_scope_step_ids` and constructs `bundle.run_status`
   once, complete.
3. `_collect_reproducibility` consumes the digest's `manifest_hash`/
   `pathway_hash` and constructs `bundle.reproducibility` once, complete.
   The destroy-and-rebuild at `collector.py:1152-1163` disappears.
4. `_read_canonical_manifest` only validates and emits limitations (via
   the returned digest), no longer mutates `bundle`.

## Acceptance criteria

- [ ] `rg '_raw' cardre/reporting/collector.py` returns 0.
- [ ] `rg '_raw' cardre/services/comparison_service.py` returns 0.
- [ ] `rg '_read_raw_json_by_step' cardre/reporting` returns 0.
- [ ] `rg 'import json' cardre/reporting/collector.py` returns 0 (the
  inline import inside a method body is gone).
- [ ] No `hasattr(data, "to_dict")` or `getattr(data, "_raw", ...)`
  duck-typing remains in `reporting/`.
- [ ] `_read_canonical_manifest` returns a `ManifestDigest`, does not
  mutate `bundle`.
- [ ] `bundle.reproducibility` is constructed once (no destroy-and-rebuild).
- [ ] Golden report bundle diff passes (no behaviour change).
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] `scripts/audit_quality.py --json` shows the `_raw` count in
  `cardre/reporting/` + `cardre/services/comparison_service.py` dropped
  by 22 (14+8).

## Do not

- Do not decompose the collector into a section registry (that's PR5).
  This PR only replaces `_raw` accesses in place; the `_collect_*` method
  structure stays the same.
- Do not touch `scoring_export.py`, `freeze.py`, `calibrate.py`, or
  `build/models.py` (those are PR3a/3b).
- Do not touch `readiness/check.py` structure (that's PR5).