# Phase 5 Starting Point

## Phase 5 — Governance Report Compiler

Phase 5 turns the Phase 4 audit graph into a structured governance report. Every claim must trace to a branch, run step, artefact, metric, warning, or champion decision.

---

## Frozen Evidence Contract

Phase 5 reads only existing evidence. It does not invent new modelling outputs.
The report generator must consume from these sources:

| Source | Format | Content |
|---|---|---|
| Technical manifest | JSON | Full step manifest with hashes, params, node versions, run IDs, artefact references |
| Branch metadata | `plan_branches` row | Branch type, branch point, creation reason, head plan version |
| Branch step map | `branch_step_map` rows | Canonical/actual step IDs, ownership (shared vs branch-owned), source lineage |
| Run records | `runs` row | Status, timestamps, branch association |
| Run-step records | `run_steps` rows | Input/output artefact IDs, execution fingerprint, warnings, errors |
| Artefact records | `artifacts` row | Type, role, path, physical/logical hashes, media type |
| WOE/IV summaries | JSON artefact (final-woe-iv) | IV, bin definitions, warnings per variable |
| Model artefacts | JSON artefact (logistic-regression) | Coefficients, convergence, feature count |
| Score scaling | JSON artefact (score-scaling) | Base score, odds, PDO, points mapping |
| Validation metrics | JSON artefact (validation-metrics) | AUC, Gini, KS, calibration by role |
| Cutoff analysis | JSON artefact (cutoff-analysis) | Approval rate, bad rate, capture rate by cutoff |
| Comparison snapshot | JSON artefact (branch_comparison) | WOE/IV comparison, model comparison, validation comparison, cutoff comparison |
| Champion assignment | `champion_assignments` row | Selected branch, comparison snapshot, rationale, supersession chain |

### Read-only rules

- No modelling execution during report generation
- No run records created during report generation
- No artefact mutation during report generation
- No plan version creation during report generation

---

## Phase 5 Structure

| Slice | Scope | Dependency |
|---|---|---|
| **5A** | Report evidence model and section manifest | Evidence contract |
| **5B** | Section generation as structured JSON | 5A |
| **5C** | HTML/Markdown renderer | 5B |
| **5D** | Export bundle integration | 5C |
| **5E** | Report QA checks and missing-evidence diagnostics | 5D |
| **5F** | Optional PDF generation | 5E |

---

## 5A — Report Evidence Model

The first PR builds a structured JSON report model with evidence tracing.

**Existing scaffold:** `cardre/services/report_service.py` — defines
`GovernanceReport`, `ReportSection`, `EvidenceRef`, `SECTION_MANIFEST`,
and `create_empty_report()`.

```python
# Example usage:
from cardre.services.report_service import create_empty_report
report = create_empty_report(
    project_id="...",
    branch_id="...",
    report_id=str(uuid.uuid4()),
    created_at=utc_now_iso(),
)
report.sections[0].content = {"project_name": "...", "version": "0.4.0"}
report.sections[0].evidence_refs.append(
    EvidenceRef(source_type="branch", source_id=branch_id, claim="selected branch")
)
```

Section manifest (initial):

- `project_header` — project name, version, date
- `branch_summary` — selected branch, type, point, reason
- `data_quality` — import, profiling, exclusion counts
- `variable_selection` — IV rankings, clustering, selected variables
- `binning_definition` — fine-classing + manual override summary
- `model_specification` — LR coefficients, score scaling params
- `validation_results` — AUC/Gini/KS by role with calibration
- `cutoff_strategy` — cutoff trade-offs
- `champion_rationale` — comparison summary and champion reason
- `evidence_footprint` — artefact hashes, run-step fingerprints
- `comparison_summary` — WOE/IV diff, model diff, metric delta
