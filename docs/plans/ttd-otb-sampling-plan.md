# Through-the-Door vs On-the-Books Sampling — Implementation Plan

> Derived from: Anderson Ch. 5 (Development Sample), Ch. 18 (Reject Inference).
> Aligned with Cardre's DevelopmentSampleDefinitionNode and the existing reject inference plan.

## 1. Problem

The algo-risk-credit skill states:
> "Through-the-door vs on-the-books: TTD samples include all applicants; OTB only approved ones. Model purpose determines which sample to use."

Cardre's `DevelopmentSampleDefinitionNode` supports `sample_method` (`"full_population"`, `"sample"`) and `prior_probability_adjustment`, but has **no concept of TTD vs OTB**. The distinction matters because:

- **TTD (through-the-door)**: All applicants, including rejects. Used for application scoring (approval decisions). Requires reject inference to assign outcomes to rejects.
- **OTB (on-the-books)**: Only approved/financed accounts. Used for behavioral scoring (account management). Suffers from selection bias but outcomes are known.

The existing reject inference plan (`docs/plans/reject-inference-module-plan.md`) introduces a `DefineRejectPopulationNode` between sample definition and split. This plan updates the sample definition node to explicitly model the TTD vs OTB choice as a first-class concept, making it the upstream decision that feeds into reject inference.

## 2. Design Decision

**Chosen: Extend `DevelopmentSampleDefinitionNode`, not a new node.**

The sample definition node already describes *what* sample is being built. Adding TTD vs OTB as a parameter on this node makes the connection explicit: "I am building a TTD sample (with rejects)" vs "I am building an OTB sample (approved only)".

The reject inference plan then reads this choice to determine:
- TTD + `sample_method="full_population"` → expects reject inference downstream
- OTB + `sample_method"` → no reject inference needed

## 3. Parameter Changes

### `DevelopmentSampleDefinitionNode` — new params

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `sample_domain` | str | `"ttd"` | `"ttd"` (through-the-door, all applicants) or `"otb"` (on-the-books, approved only) |
| `rejection_source` | str | `None` | Required if `sample_domain="ttd"`. `"flag_column"`, `"target_missing"`, or `None` (if no rejects in data, i.e. an OTB dataset used for TTD domain). |
| `rejection_column` | str | `None` | Column name if `rejection_source="flag_column"` |
| `approval_column` | str | `None` | Column indicating approved/financed status. Required for OTB to document the approval filter. |
| `approval_values` | list | `None` | Values in `approval_column` indicating approval (e.g. `["1", "approved", "financed"]`) |

### Validation

```python
def validate_params(self, params):
    errors = []
    domain = params.get("sample_domain", "ttd")
    if domain not in ("ttd", "otb"):
        errors.append("sample_domain must be 'ttd' or 'otb'")
    if domain == "ttd":
        rejection_source = params.get("rejection_source")
        if rejection_source is not None and rejection_source not in ("flag_column", "target_missing"):
            errors.append("rejection_source must be 'flag_column', 'target_missing', or None")
    if domain == "otb":
        if not params.get("approval_column"):
            errors.append("approval_column is required for otb sample domain")
    return errors
```

## 4. Sample Definition Artifact Changes

The existing sample definition artifact gains:

```json
{
  "schema_version": "cardre.sample_definition.v1",
  "sample_method": "full_population",
  "weight_column": null,
  "population_bad_rate": null,
  "prior_probability_adjustment": null,
  "sample_domain": "ttd",
  "rejection_source": "target_missing",
  "rejection_column": null,
  "total_rows": 15000,
  "financed_rows": 10000,
  "non_financed_rows": 5000,
  "sample_description": "TTD development sample, full population, reject inference required"
}
```

For OTB:
```json
{
  "sample_domain": "otb",
  "approval_column": "status",
  "approval_values": ["approved", "financed"],
  "total_rows": 10000,
  "financed_rows": 10000,
  "non_financed_rows": 0,
  "sample_description": "OTB development sample, approved accounts only"
}
```

## 5. Schema Version

The current sample definition output has no schema version. We introduce:

```python
SCHEMA_SAMPLE_DEFINITION = "cardre.sample_definition.v1"
```

The existing output format gets versioned. A migration in `DevelopmentSampleDefinitionNode.run()` writes the legacy fields plus the new ones, with `sample_domain=ttd` as the implicit default for backward compatibility.

## 6. Integration with Reject Inference

The `DefineRejectPopulationNode` (from the reject inference plan) now reads:

1. `DevelopmentSampleDefinitionNode` output → gets `sample_domain`, `rejection_source`, `rejection_column`
2. If `sample_domain="otb"`: no reject population defined (non_financed_rows=0)
3. If `sample_domain="ttd"`: uses the rejection parameters to classify financed vs non-financed

The reject inference branch point in `branch_service.py` additionally validates that the parent sample definition's `sample_domain` is `"ttd"` before allowing a `reject_inference_challenger` branch.

## 7. Branch Point Validation

In `branch_service.py`, `_validate_branch_point()`:

```python
if branch_type == "reject_inference_challenger":
    sample_def_step = resolve_ancestor(steps, "sample-definition")
    sample_def_params = sample_def_step.params
    if sample_def_params.get("sample_domain") != "ttd":
        raise BranchValidationError(
            "Reject inference challenger requires sample_domain='ttd'. "
            "Cannot add reject inference to an OTB sample."
        )
```

## 8. Files to Create or Modify

| File | Action | Notes |
|------|--------|-------|
| `cardre/nodes/prep.py` | **MODIFY** | `DevelopmentSampleDefinitionNode`: +new params, +validation, +output fields |
| `cardre/evidence.py` | **MODIFY** | +1 schema constant `SCHEMA_SAMPLE_DEFINITION` (if not exists) |
| `cardre/services/branch_service.py` | **MODIFY** | Validate `sample_domain` before allowing reject inference branch |
| `cardre/reporting/collector.py` | **MODIFY** | Optionally surface sample_domain in report bundle |
| `sidecar/proof_pathway.py` | **MODIFY** | Update default sample-definition params to include `sample_domain="ttd"` |
| `tests/test_phase2a.py` | **MODIFY** | Update sample definition tests |
| `tests/test_reject_inference.py` | **MODIFY** | Integration tests with TTD/OTB distinction |

## 9. Testing Strategy

1. `test_sample_domain_ttd_default`: No explicit domain → defaults to ttd
2. `test_sample_domain_otb_requires_approval_column`: otb without approval_column → validation error
3. `test_sample_domain_invalid`: Invalid domain string → validation error
4. `test_sample_definition_artifact_includes_domain`: Written artifact has sample_domain field
5. `test_reject_branch_blocked_on_otb`: Trying to create reject inference branch on OTB sample → blocked
6. `test_backward_compatibility`: Old sample definition without domain field → defaults to ttd

## 10. Implementation Sequence

| Phase | What | Effort | Depends on |
|-------|------|--------|------------|
| 1 | Params + validation on `DevelopmentSampleDefinitionNode` | Small | — |
| 2 | Schema version + artifact output changes | Small | Phase 1 |
| 3 | Branch service validation | Tiny | Phase 1 |
| 4 | Backward compatibility + tests | Small | Phase 2 |
| 5 | Reject inference plan integration (when implemented) | Tiny | All phases + reject inference module |

**MVP:** Params and validation only. Backward compatible — existing OTB workflows set none of the new params. TTD workflows opt in explicitly. Reject inference branch guard activates when reject inference module lands.
