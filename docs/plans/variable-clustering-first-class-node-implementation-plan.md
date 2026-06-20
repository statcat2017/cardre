# Variable Clustering First-Class Node Implementation Plan

## Goal

Promote the existing `VariableClusteringNode` into a first-class Cardre evidence-producing node.

The node should expose explicit clustering methods, produce a reusable variable-clustering evidence artifact, feed downstream variable selection, and appear in audit/reporting as a dedicated redundancy review section.

## Existing State

`VariableClusteringNode` already exists at `cardre/nodes/build/features.py`.

It is already registered and wired into the scorecard pathways:

- `cardre/registry.py`
- `cardre/nodes/__init__.py`
- `cardre/nodes/build/__init__.py`
- `sidecar/proof_pathway.py`
- `frontend/src/config/stepDisplayMetadata.ts`
- `tests/test_scorecard_selection.py`
- `tests/contracts/test_node_contracts.py`

This is not a greenfield node. Implement this as an in-place upgrade.

## Locked Decisions

- Keep class name `VariableClusteringNode`.
- Keep `node_type = "cardre.variable_clustering"`.
- Keep `version = "1"`.
- Keep category as `selection`.
- Do not add a dedicated variable-screening node in this change.
- Add both downstream variable-selection integration and reporting integration.
- Preserve compatibility with legacy clustering artifacts that contain top-level `clusters`.

## Important Constraint

`input_representation = "woe_train"` cannot read a WOE-transformed train artifact in the current pathway because `woe_transform_train` runs after variable selection.

For `woe_train`, the clustering node must build WOE columns on the fly using:

- raw train artifact
- bin definition artifact
- WOE table artifact from `initial-woe-iv`

Recommended v1-compatible default: `input_representation = "raw_train"`.

`woe_train` should be implemented as an available option, but making it the pathway default should be a later migration because it requires adding `binning` as a parent of `variable-clustering`.

## Phase 1: Evidence Schema

Update `cardre/evidence.py`.

Add:

```python
SCHEMA_VARIABLE_CLUSTERING_EVIDENCE = "cardre.variable_clustering_evidence.v1"
```

Add `EvidenceKind.VARIABLE_CLUSTERING`.

Add typed evidence dataclasses:

```python
@dataclass(frozen=True)
class ClusterMember:
    variable: str
    iv: float | None = None
    missing_rate: float | None = None

@dataclass(frozen=True)
class VariableCluster:
    cluster_id: str
    variables: list[ClusterMember]
    representative_suggestion: str | None = None
    representative_reason: str = ""
    max_pairwise_abs_corr: float | None = None
    notes: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class VariableClusteringEvidence:
    method: str
    input_representation: str
    similarity_metric: str
    threshold: float | None
    clusters: list[VariableCluster]
    singleton_variables: list[str]
    warnings: list[dict[str, Any]]
    schema_version: str = SCHEMA_VARIABLE_CLUSTERING_EVIDENCE
```

Add a `from_json()` parser that accepts both enriched variable objects and legacy bare-string variables.

Add `_EVIDENCE_PROFILES` entry:

```python
EvidenceKind.VARIABLE_CLUSTERING: _Profile(
    expected_roles={"report"},
    expected_artifact_types={"report"},
    schema_version=SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
    required_keys={"method", "clusters"},
)
```

Register the parser in `_parse`.

Export new schema constant and dataclasses in `__all__`.

## Phase 2: Upgrade VariableClusteringNode Parameters

Update `VariableClusteringNode` in `cardre/nodes/build/features.py`.

Add `parameter_schema()` with available methods:

| Method | Status | Purpose |
| --- | --- | --- |
| `correlation_threshold` | available | Simple explainable threshold clustering |
| `hierarchical` | available | Correlation-distance hierarchical clustering |
| `varclus_pca` | coming_soon | SAS-style VARCLUS/PCA component clustering |
| `mixed_type` | coming_soon | Numeric/categorical mixed-type redundancy clustering |
| `target_aware` | coming_soon | Target-aware redundancy clustering |

`correlation_threshold` params:

| Param | Type | Default |
| --- | --- | --- |
| `similarity_metric` | enum `pearson`, `spearman` | `pearson` |
| `absolute_correlation` | boolean | `true` |
| `threshold` | float | `0.7` |
| `input_representation` | enum `raw_train`, `woe_train` | `raw_train` |
| `missing_handling` | enum `pairwise`, `complete_case` | `pairwise` |
| `candidate_limit` | integer | `50` |
| `representative_rule` | enum `highest_iv`, `lowest_missing`, `manual` | `highest_iv` |

`hierarchical` params:

| Param | Type | Default |
| --- | --- | --- |
| `similarity_metric` | enum `pearson`, `spearman` | `pearson` |
| `distance` | fixed string | `1 - abs(correlation)` |
| `linkage` | enum `average`, `complete` | `average` |
| `cut_threshold` | float | `0.3` |
| `input_representation` | enum `raw_train`, `woe_train` | `raw_train` |
| `missing_handling` | enum `pairwise`, `complete_case` | `pairwise` |
| `candidate_limit` | integer | `50` |
| `representative_rule` | enum `highest_iv`, `lowest_missing`, `manual` | `highest_iv` |

Keep `validate_params()` compatible with legacy `correlation_threshold`.

Map legacy param `correlation_threshold` to new param `threshold` when `threshold` is absent.

## Phase 3: Upgrade VariableClusteringNode Execution

Rewrite `run()` around these steps:

1. Resolve train artifact.
2. Resolve IV table with `ArtifactEvidenceReader.find_optional(..., EvidenceKind.IV_TABLE)`.
3. Resolve WOE table and bin definition only when `input_representation == "woe_train"`.
4. Build candidate variable list from IV table when present, otherwise numeric train columns.
5. Exclude target and non-feature columns where possible using modelling metadata.
6. Apply `candidate_limit`.
7. Compute missing rates from raw train columns.
8. Build clustering matrix.
9. Compute correlation matrix.
10. Build clusters using chosen method.
11. Enrich clusters with representative suggestions and audit metadata.
12. Write one JSON report artifact with `metadata.schema_version`.

Artifact payload shape:

```json
{
  "schema_version": "cardre.variable_clustering_evidence.v1",
  "method": "correlation_threshold",
  "input_representation": "raw_train",
  "similarity_metric": "pearson",
  "absolute_correlation": true,
  "threshold": 0.7,
  "missing_handling": "pairwise",
  "candidate_limit": 50,
  "representative_rule": "highest_iv",
  "clusters": [
    {
      "cluster_id": "cluster_001",
      "variables": [
        {
          "variable": "bureau_score",
          "iv": 0.42,
          "missing_rate": 0.01
        }
      ],
      "representative_suggestion": "bureau_score",
      "representative_reason": "highest IV",
      "max_pairwise_abs_corr": 0.86,
      "notes": []
    }
  ],
  "singleton_variables": ["age", "months_on_book"],
  "warnings": []
}
```

Keep `clusters` top-level for legacy compatibility.

Return metrics:

```python
{
    "candidate_count": ...,
    "cluster_count": ...,
    "singleton_count": ...,
    "warning_count": ...,
}
```

## Phase 4: WOE Representation Support

For `input_representation == "woe_train"`:

- Read `EvidenceKind.BIN_DEFINITION`.
- Read `EvidenceKind.WOE_TABLE`.
- Use `build_bin_condition()` from `cardre.nodes._bin_mask`.
- Apply bin definitions to raw train columns.
- Map bin ids to WOE values.
- Build temporary numeric WOE columns for clustering only.
- Do not persist a transformed dataset.

This logic can mirror `WoeTransformTrainNode` but should remain local unless duplication becomes excessive.

If WOE artifacts are missing, raise a clear error:

```text
Variable clustering with input_representation='woe_train' requires bin definition and WOE table artifacts.
```

## Phase 5: Clustering Algorithms

Correlation-threshold clustering:

- Use absolute correlation when `absolute_correlation = true`.
- Treat variables as connected when similarity >= threshold.
- Build connected components rather than only greedy first-neighbour groups.
- This avoids missing transitive clusters.

Hierarchical clustering:

- Use distance `1 - abs(correlation)`.
- Implement scipy-free average/complete agglomerative clustering to avoid new dependency.
- Cut when merge distance exceeds `cut_threshold`.
- Keep deterministic ordering by candidate variable order.

Missing handling:

- `complete_case`: drop rows with nulls in candidate columns before matrix creation.
- `pairwise`: compute each pair correlation on rows where both columns are non-null.

Spearman:

- Rank each column first, then Pearson on ranks.

## Phase 6: Representative Suggestions

Available representative rules inside clustering:

| Rule | Implementation |
| --- | --- |
| `highest_iv` | Choose max IV from IV table; tie-break lowest missing rate, then original candidate order |
| `lowest_missing` | Choose lowest missing rate; tie-break highest IV, then original candidate order |
| `manual` | No automatic suggestion; set representative to null and reason to "manual review required" |

Do not implement `lowest_psi` in this phase because PSI is produced downstream by validation.

Do not implement `highest_univariate_gini` unless a suitable upstream artifact is added; mark as future work.

## Phase 7: VariableSelectionNode Integration

Update `VariableSelectionNode` in `cardre/nodes/build/features.py`.

Add params to `parameter_schema()`:

| Param | Type | Default |
| --- | --- | --- |
| `cluster_representative_rule` | enum `none`, `highest_iv`, `lowest_missing`, `manual_override` | `none` |
| `cluster_representative_overrides` | list | `[]` |

Keep default `none` to preserve current behaviour.

Validation:

- Each override must include `cluster_id`, `variable`, and `reason`.
- Reject override variable not in the target cluster.
- Continue requiring reasons for manual includes/excludes.

Read clustering evidence:

- First try `EvidenceKind.VARIABLE_CLUSTERING`.
- Fall back to legacy JSON scan for top-level `clusters`.
- Handle both `variables: ["x"]` and `variables: [{"variable": "x"}]`.

When `cluster_representative_rule != "none"`:

- Select one variable per multi-variable cluster based on the rule.
- Honour `manual_excludes` first.
- Honour `cluster_representative_overrides` next.
- Honour `manual_includes`, but if this keeps multiple variables from the same cluster, record a rationale in the output.
- Continue applying `min_iv` and `max_variables`.

Update selection artifact to include:

```json
{
  "cluster_representative_rule": "highest_iv",
  "cluster_representative_overrides": [],
  "cluster_decisions": [
    {
      "cluster_id": "cluster_001",
      "selected_variable": "bureau_score",
      "reason": "highest IV within variable cluster",
      "candidate_variables": ["bureau_score", "external_risk_band"]
    }
  ]
}
```

Keep `schema_version = cardre.selection_definition.v1`.

## Phase 8: Reporting Integration

Update `cardre/reporting/schema.py`.

Add models:

```python
class RedundancyClusterMember(BaseModel):
    variable: str
    iv: float | None = None
    missing_rate: float | None = None

class RedundancyCluster(BaseModel):
    cluster_id: str
    variables: list[RedundancyClusterMember] = Field(default_factory=list)
    representative_suggestion: str | None = None
    representative_reason: str = ""
    max_pairwise_abs_corr: float | None = None
    notes: list[str] = Field(default_factory=list)

class RedundancyReviewInfo(BaseModel):
    method: str = ""
    input_representation: str = ""
    similarity_metric: str = ""
    threshold: float | None = None
    representative_rule: str = ""
    cluster_count: int = 0
    singleton_count: int = 0
    clusters: list[RedundancyCluster] = Field(default_factory=list)
    singleton_variables: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
```

Add to `ReportBundle`:

```python
redundancy_review: RedundancyReviewInfo = Field(default_factory=RedundancyReviewInfo)
```

Update `cardre/reporting/collector.py`:

- Add optional resolution for canonical step `variable-clustering`.
- Add `_collect_redundancy_review()`.
- Read `EvidenceKind.VARIABLE_CLUSTERING` from the clustering run step.
- Populate `bundle.redundancy_review`.
- Add warning limitation if the step exists but evidence is missing.

Update `cardre/reporting/limitation_codes.py`:

```python
MISSING_VARIABLE_CLUSTERING_EVIDENCE = "MISSING_VARIABLE_CLUSTERING_EVIDENCE"
```

Update `cardre/reporting/templates/report.html.j2`:

- Add section title: `Redundancy and Variable Clustering Review`.
- Render method, input representation, metric, threshold, representative rule.
- Render cluster table: cluster id, variables, representative, reason, max corr.
- Render singleton variables.
- Render warnings.

## Phase 9: Pathway and Frontend

Update `sidecar/proof_pathway.py` clustering params for both scorecard pathways:

```python
params={
    "method": "correlation_threshold",
    "similarity_metric": "pearson",
    "absolute_correlation": True,
    "threshold": 0.7,
    "input_representation": "raw_train",
    "missing_handling": "pairwise",
    "candidate_limit": 50,
    "representative_rule": "highest_iv",
}
```

Do not change parents unless making `woe_train` the default.

Update `frontend/src/config/stepDisplayMetadata.ts` description:

```text
Group redundant variables and suggest cluster representatives
```

No custom frontend component is required for MVP because method/params are schema-driven.

Optional later frontend enhancement:

- Add cluster table in `StepInspector`.
- Add actions: accept suggested representative, keep multiple variables, exclude cluster, override representative, add rationale.
- Persist those choices as `VariableSelectionNode` params, not clustering params.

## Phase 10: Tests

Update or add tests:

- `tests/test_scorecard_selection.py`
- `tests/contracts/test_node_contracts.py`
- `tests/test_reporting.py`
- `tests/test_reporting_acceptance.py`
- `tests/golden_scorecard/test_german_credit_statistical_pipeline.py`
- `tests/test_scorecard_model.py`

Required coverage:

- Legacy params `{correlation_threshold, candidate_limit}` still run.
- New schema defaults merge and validate.
- Invalid threshold fails.
- `correlation_threshold` method forms expected clusters.
- Connected-component behaviour handles transitive clusters.
- `singleton_variables` excludes multi-variable clusters.
- Representative suggestion uses highest IV.
- Representative suggestion uses lowest missing.
- Legacy bare-string cluster artifacts still work in `VariableSelectionNode`.
- New enriched clustering evidence works in `VariableSelectionNode`.
- `cluster_representative_rule = none` preserves current behaviour.
- `cluster_representative_rule = highest_iv` chooses one per cluster.
- Manual cluster override requires reason.
- Report bundle includes `redundancy_review`.
- HTML template renders redundancy section.

## Verification Commands

Run:

```bash
python3 -m pytest tests/ -q --tb=short
```

Run fail-fast if needed:

```bash
python3 -m pytest tests/ -x --tb=long
```

Run frontend typecheck:

```bash
cd frontend && npx tsc --noEmit
```

## Acceptance Criteria

- `VariableClusteringNode` has a full `parameter_schema()`.
- Node emits `cardre.variable_clustering_evidence.v1`.
- Existing scorecard pathway still runs with v1 node type.
- Existing legacy cluster artifacts remain consumable.
- `VariableSelectionNode` can explicitly consume clustering evidence for cluster representative selection.
- Report bundle has a dedicated redundancy review section.
- Tests cover legacy compatibility, new evidence schema, downstream selection, and reporting.
