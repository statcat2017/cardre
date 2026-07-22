# 02 — Domain and Use Cases

## Glossary

Preserved from `CONTEXT.md` and `docs/architecture/domain-model.md`. Vocabulary is stable; ADR-0002 forbade gratuitous renaming and this plan honours that.

- **Project** — a scorecard project root directory (`<name>.cardre/`) containing SQLite metadata, objects, manifests, exports.
- **Plan** — a named, versioned container of steps under a project.
- **PlanVersion** — an immutable snapshot of a plan. `is_committed=False` (draft, editable) or `is_committed=True` (frozen, executable). Every run references exactly one committed plan version.
- **StepSpec** — one node occurrence within a plan version. Has `step_id`, `node_type`, `node_version`, `category`, `params`, `params_hash`, `parent_step_ids`, `branch_label`, `position`, `canonical_step_id`, `branch_id`.
- **PlanGraph** — the DAG of `StepSpec`s within a plan version, encoded by `parent_step_ids` (and `plan_step_edges` rows).
- **Node type** — a reusable implementation registered in the node catalogue (e.g. `cardre.logistic_regression`).
- **Run** — one execution of a committed plan version. Status lifecycle: `submitted → running → {succeeded|failed|cancelled|interrupted}`. (Drops `created`/`queued` per D10.)
- **RunStep** — one step's execution record within a run. Status: `running → {succeeded|failed}`. (Drops `pending`/`skipped` per D10.)
- **Artifact** — an immutable output file. Dual-hashed: `physical_hash` (bytes) + `logical_hash` (canonical content). Content-addressed by `physical_hash`.
- **Evidence** — typed interpretation of an artifact via `EvidenceKind` + adapter. The two-level model (`evidence_edges` + `evidence_artifacts`) is preserved.
- **Lineage** — `artifact_lineage` rows linking artifacts to run_steps with `direction` (input/output).
- **Branch** — a diverged copy of a plan from a permitted branch point. Governance-gated.
- **Comparison** — intent to compare baseline vs challenger branches. Produces immutable snapshots.
- **Champion** — designated best-performing branch for a scope. Supersedes previous champions.
- **Manual intervention** — manual binning review/edit producing a new draft plan version.
- **Build stream** — train-only fitting nodes (import → binning → WOE → selection → logistic → score scaling).
- **Validate stream** — apply nodes consuming definitions on test/oot (apply WOE, apply model, validation metrics, cutoff).
- **Canonical step ID** — stable identifier for a logical step across versions/branches (e.g. `model-fit`, `final-woe-iv`).

## Aggregate model

| Aggregate | Root entity | Entities inside | Value objects | Consistency boundary |
|-----------|-------------|-----------------|---------------|---------------------|
| Project | `Project` | — | `ProjectId`, `CreatedAt`, `CardreVersion` | project registration row + filesystem root existence |
| Plan | `Plan` | — | `PlanId`, `ProjectId`, `Name` | plan belongs to one project |
| PlanVersion | `PlanVersion` | `StepSpec` (value object), `PlanStepEdge` (value object) | `PlanVersionId`, `PlanId`, `VersionNumber`, `IsCommitted`, `Description`, `ParamsHash` | all steps + edges commit atomically; immutable once committed |
| Run | `Run` | `RunStep` | `RunId`, `PlanVersionId`, `RunStatus`, `RunScope`, `BranchId`, `StartedAt`, `FinishedAt`, `HeartbeatAt`, `ActiveStepId` | run state transitions atomic via compare-and-set; run_steps commit per-step |
| Artifact | `Artifact` | — | `ArtifactId`, `ArtifactType`, `Role`, `Path`, `PhysicalHash`, `LogicalHash`, `MediaType`, `SchemaVersion`, `Metadata` | immutable; dedup by physical_hash |
| Evidence | (no aggregate root; query model) | `EvidenceEdge`, `EvidenceArtifact` | — | edges + artifacts commit with their run_step |
| Branch | `Branch` | `BranchStepMap` (value object) | `BranchId`, `PlanId`, `BranchType`, `BasePlanVersionId`, `HeadPlanVersionId`, `BranchPointStepId`, `Status` | branch + step map + head update atomic |
| Comparison | `Comparison` | `ComparisonChallengerBranch` (value object), `ComparisonSnapshot` (value object) | `ComparisonId`, `BaselineBranchId`, `Spec` | comparison + challengers + snapshots commit atomically on refresh |
| ChampionAssignment | `ChampionAssignment` | — | `AssignmentId`, `ProjectId`, `PlanId`, `ScopeType`, `ScopeKey`, `ChampionBranchId`, `ComparisonSnapshotId`, `AssignedReason`, `AssignedAt`, `SupersededAt` | new + supersede in one transaction |

`ManualBinningReview` is an entity inside the PlanVersion aggregate (a review row is created atomically with a new draft version).

## Where dataclasses are sufficient

- `StepSpec`, `PlanStepEdge`, `RunStep`, `EvidenceEdge`, `EvidenceArtifact`, `BranchStepMap`, `ComparisonSnapshot`, `ComparisonChallengerBranch` — frozen dataclasses. No need for aggregate-root methods beyond construction validation.
- `ResolvedEvidence` — read model (computed view), frozen dataclass.
- `RunPlanDecision`, `StalenessExplanation` — application-only result types, plain dataclasses.
- `TargetMeta`, `ExecutionFingerprint`, `NodeOutput` — execution-only dataclasses.

## Invariants (enforced in domain + application)

| Invariant | Enforced where |
|-----------|----------------|
| Committed plan versions are immutable | `CommitPlanVersion` use case sets `is_committed=True`; no update path for steps of a committed version |
| Graphs are acyclic | `validate_topology` (Kahn's) at commit and at run submit |
| Step IDs unique within a plan version | DB `PRIMARY KEY (plan_version_id, step_id)` |
| All parents exist | `validate_topology` missing-parent check |
| Node identities are valid | `NodeCataloguePort.availability(node_type)` at run submit |
| Parameters are valid | `normalize_node_params` + `node.validate_params` at step execution |
| Runs reference committed plan versions | `SubmitRun` checks `is_committed=True` |
| Run transitions are legal | `RunStatus._check_transition` + `RunRepository.transition` compare-and-set |
| Terminal runs cannot reopen | `_VALID_TRANSITIONS` has empty sets for terminal states |
| Artifacts are immutable | No update path; `ArtifactRepository.register` dedup + INSERT only |
| Lineage is explicit | `artifact_lineage` rows written per run_step for inputs + outputs |
| Node outputs satisfy declared contracts | `OutputPublisher.validate` rejects undeclared roles/kinds (NEW) |

## Use-case catalogue

Each use case is a callable class (or function) taking injected ports. Direct injection, no command bus.

### Projects

| Use case | Command/Query | Principal domain rules | Required ports | Transaction boundary | Result | Failure modes | Current code |
|----------|---------------|------------------------|----------------|-----------------------|--------|---------------|--------------|
| `CreateProject` | `CreateProjectCommand(name, path)` | path absolute, no `..`, root not already a store | `ProjectProvisionerPort`, `ProjectRegistryPort`, `UoW` | provisioner initializes filesystem+sqlite; registry registers; two operations (not one txn — registry is a file) | `Project` | `INVALID_PROJECT_PATH`, `STORE_ALREADY_EXISTS`, `PROJECT_NOT_FOUND` (path missing) | `api/routes/projects.py:107` + `ProjectStore.initialize` + `ProjectResolver.register_project` |
| `ListProjects` | — | unavailable projects reported separately | `ProjectRegistryPort` | read-only | `list[Project]` + unavailable list | registry file missing → empty | `api/routes/projects.py:32` |
| `GetProject` | `GetProjectQuery(project_id)` | project exists in registry | `ProjectRegistryPort`, `UoW` (read-only) | read-only | `Project` | `PROJECT_NOT_FOUND` | `api/routes/projects.py:86` |
| `ResolveProject` | (internal) `project_id → root` | registry lookup | `ProjectRegistryPort` | read-only | `Path` | `PROJECT_NOT_FOUND` | `services/project_resolver.py` |

### Plans

| Use case | Command/Query | Principal domain rules | Required ports | Transaction boundary | Result | Failure modes | Current code |
|----------|---------------|------------------------|----------------|-----------------------|--------|---------------|--------------|
| `CreatePlan` | `CreatePlanCommand(project_id, name)` | project exists | `UoW` (PlanRepo) | one IMMEDIATE txn: insert plan | `Plan` | `PROJECT_NOT_FOUND` | `api/routes/plans.py:80` + `PlanRepository.create_plan` |
| `GetPlan` | `GetPlanQuery(project_id, plan_id)` | plan belongs to project | `UoW` (PlanRepo) | read-only | `Plan` | `PLAN_NOT_FOUND` | `plans.py:56` + `PlanService.get_plan` |
| `ListPlans` | `ListPlansQuery(project_id)` | — | `UoW` (PlanRepo) | read-only | `list[Plan]` | `PROJECT_NOT_FOUND` | `plans.py:43` |
| `GetPlanVersion` | `GetPlanVersionQuery(project_id, version_id)` | version belongs to project | `UoW` (PlanRepo, StepRepo) | read-only | `PlanVersion` + `list[StepSpec]` | `PLAN_VERSION_NOT_FOUND` | `plans.py:124` |
| `ListPlanVersions` | `ListPlanVersionsQuery(project_id, plan_id)` | plan belongs to project | `UoW` (PlanRepo) | read-only | `list[PlanVersionSummary]` | `PLAN_NOT_FOUND` | `plans.py:99` |
| `UpdatePlanVersion` | `UpdatePlanVersionCommand(project_id, version_id, description)` | version is draft (not committed) | `UoW` (PlanRepo) | one IMMEDIATE txn: update description | `PlanVersion` | `PLAN_VERSION_IMMUTABLE` (committed), `PLAN_VERSION_NOT_FOUND` | `plans.py:148` |
| `CommitPlanVersion` | `CommitPlanVersionCommand(project_id, version_id)` | version exists; version is draft; graph is acyclic; all parents exist | `UoW` (PlanRepo, StepRepo) | one IMMEDIATE txn: `UPDATE is_committed=1` | `PlanVersion` | `PLAN_VERSION_NOT_FOUND`, `PLAN_VERSION_ALREADY_COMMITTED`, `GRAPH_VALIDATION_ERROR` | `plans.py:189` + `PlanService.commit_plan_version` |
| `ApplyManualBinningEdit` | `ApplyManualBinningEditCommand(...)` | base version exists + committed; source evidence structurally valid; overrides valid; new draft version number = max+1 | `UoW` (PlanRepo, StepRepo, ManualBinningRepo) | one IMMEDIATE txn: new version + steps + edges + review | `ManualBinningEditResult` | `PLAN_VERSION_NOT_FOUND`, `PLAN_VERSION_NOT_COMMITTED`, `MANUAL_BINNING_INVALID` | `services/plan_mutation_service.py:72` |

### Runs

| Use case | Command/Query | Principal domain rules | Required ports | Transaction boundary | Result | Failure modes | Current code |
|----------|---------------|------------------------|----------------|-----------------------|--------|---------------|--------------|
| `SubmitRun` | `SubmitRunCommand(project_id, plan_version_id, run_scope, branch_id, force, requested_by)` | version exists + committed; governance enabled if branch scope; no concurrent run (unless force); branch evidence policy (if branch, not force) | `UoW` (PlanRepo, RunRepo), `RunDispatcher`, `EvidenceReader` | one IMMEDIATE txn: sweep stale + insert run | `Run` (status `running`) | `PLAN_VERSION_NOT_FOUND`, `PLAN_VERSION_NOT_COMMITTED`, `GOVERNANCE_NOT_ENABLED`, `CONCURRENT_RUN`, `EVIDENCE_POLICY_CURRENT` | `services/run_coordinator.py:107` |
| `ExecuteRun` | `ExecuteRunCommand(run_id)` | run is `running`; plan version committed; topology valid; all nodes available | `UoW`, `NodeCatalogue`, `StepRunner`, `RunDispatcher` (sync) | per-step IMMEDIATE txn for persistence; no txn during computation | `Run` (terminal) | `RUN_NOT_FOUND`, `RUN_NOT_RUNNING`, `PLAN_CONTAINS_UNAVAILABLE_NODES`, `GRAPH_VALIDATION_ERROR`, `RUN_EXECUTION_FAILED` | `services/run_coordinator.py:179` + `execution/executor.py` |
| `CancelRun` | `CancelRunCommand(run_id)` | run is `running` | `UoW` (RunRepo) | one IMMEDIATE txn: set `cancel_requested=1` | `Run` | `RUN_NOT_FOUND`, `RUN_NOT_RUNNING` | NEW (D14) |
| `GetRun` | `GetRunQuery(project_id, run_id)` | run belongs to project | `UoW` (RunRepo, RunStepRepo) | read-only | `RunSummary` | `RUN_NOT_FOUND` | `runs.py:43` |
| `ListRuns` | `ListRunsQuery(project_id)` | — | `UoW` (RunRepo) | read-only | `list[RunSummary]` | — | `runs.py:30` |
| `GetRunSteps` | `GetRunStepsQuery(project_id, run_id)` | run belongs to project | `UoW` (RunStepRepo) | read-only | `list[RunStep]` | `RUN_NOT_FOUND` | `runs.py:79` |
| `GetRunEvidence` | `GetRunEvidenceQuery(project_id, run_id)` | run belongs to project | `UoW` (EvidenceRepo) | read-only | `list[EvidenceEdgeView]` | `RUN_NOT_FOUND` | `runs.py:97` |

### Evidence

| Use case | Command/Query | Principal domain rules | Required ports | Transaction boundary | Result | Failure modes | Current code |
|----------|---------------|------------------------|----------------|-----------------------|--------|---------------|--------------|
| `ExplainStaleness` | `ExplainStalenessQuery(project_id, plan_version_id, step_id, branch_id)` | step exists in version; recursive DAG walk comparing parent output hashes | `UoW` (StepRepo, RunRepo, RunStepRepo, EvidenceRepo), `EvidenceReader` | read-only | `StalenessExplanation` | `STEP_NOT_FOUND`, `PLAN_VERSION_NOT_FOUND` | `services/staleness_service.py:41` |

### Governance

| Use case | Command/Query | Principal domain rules | Required ports | Transaction boundary | Result | Failure modes | Current code |
|----------|---------------|------------------------|----------------|-----------------------|--------|---------------|--------------|
| `CreateBranch` | `CreateBranchCommand(...)` | governance enabled; branch-point allow-list; plan/version scoping; base branch active; name/reason present; segment filter valid | `UoW` (BranchRepo, PlanRepo, StepRepo) | one IMMEDIATE txn: new plan_version + steps + edges + branch row + step_map | `Branch` | `BRANCH_VALIDATION_ERROR`, `GOVERNANCE_NOT_ENABLED` | `services/branch_service.py:29` |
| `CreateComparison` | `CreateComparisonCommand(...)` | governance enabled; baseline + challengers exist | `UoW` (ComparisonRepo, BranchRepo) | one IMMEDIATE txn: comparison + challengers | `Comparison` | `BRANCH_NOT_FOUND`, `GOVERNANCE_NOT_ENABLED` | `services/comparison_service.py:119` |
| `RefreshComparison` | `RefreshComparisonCommand(comparison_id)` | governance enabled; all branches ready; one snapshot per challenger | `UoW` (ComparisonRepo, BranchRepo, EvidenceRepo), `ArtifactStore`, `EvidenceReader` | one IMMEDIATE txn: all snapshots + final UPDATE | `Comparison` (with `latest_ready=True`) | `COMPARISON_NOT_FOUND`, `BRANCH_NOT_READY`, `GOVERNANCE_NOT_ENABLED` | `services/comparison_service.py:190` |
| `AssignChampion` | `AssignChampionCommand(...)` | governance enabled; reason non-empty; branch active; project+plan match; snapshot ready; branch head in snapshot; branch in comparison | `UoW` (ChampionRepo, BranchRepo, ComparisonRepo) | one IMMEDIATE txn: insert new + supersede previous | `ChampionAssignment` | `BRANCH_NOT_FOUND`, `STALE_SNAPSHOT`, `GOVERNANCE_NOT_ENABLED` | `services/champion_service.py:20` |

### Reporting

| Use case | Command/Query | Principal domain rules | Required ports | Transaction boundary | Result | Failure modes | Current code |
|----------|---------------|------------------------|----------------|-----------------------|--------|---------------|--------------|
| `GenerateReport` | `GenerateReportCommand(project_id, run_id, target_branch_id, report_mode)` | run terminal; readiness checks pass | `UoW`, `EvidenceReader`, `ArtifactReader`, `ReportRenderer` | read-only (write to filesystem via renderer) | `ReportResult` (paths) | `REPORT_BLOCKED`, `RUN_NOT_FOUND`, `RUN_NOT_TERMINAL` | `services/report_service.py:73` |
| `ExportAuditPack` | `ExportAuditPackCommand(project_id, plan_id, branch_id, include_row_level_data, include_report)` | governance enabled; branch exists; atomic tmp→rename with backup/restore | `UoW`, `ArtifactReader`, `EvidenceReader`, `ReportRenderer` | filesystem atomic; no DB txn | `ExportResult` (path, partial flag) | `BRANCH_NOT_FOUND`, `EXPORT_FAILED` | `services/export_service.py:34` |

## Commands and queries

Commands are frozen dataclasses in `application/<subsystem>/<use_case>.py`. Queries are similar but named with `Query` suffix. No command bus — handlers are methods on the use-case class:

```python
class SubmitRun:
    def __init__(self, uow_factory, dispatcher, evidence_reader): ...
    def __call__(self, command: SubmitRunCommand) -> Run: ...
```

## Transaction boundaries

- **One use case = one or zero logical transactions.** A logical transaction is a `UnitOfWork` that owns a SQLite connection + `IMMEDIATE` txn.
- Use cases that only read use a read-only `UnitOfWork` (still a connection, but no `BEGIN`).
- Use cases that write multiple rows open one `UnitOfWork`, do all writes via query objects on `uow.conn`, commit on success.
- **Long-running computation is NEVER inside a UoW.** `ExecuteRun` opens a UoW per step *finalization* (after `node.run` returns); the node execution itself runs without a UoW. Artifact staging happens via `ArtifactStore.stage(...)` (filesystem, no DB), then the finalization UoW does atomic publish + DB registration + lineage + evidence + run_step row.
- The manifest write is inside the run-finalization UoW (atomic with the status transition). (D8 — changes current behaviour where manifest is written before a separate `transition`.)

## Problem codes

Preserved from `cardre/domain/errors.py:ErrorCode` (35 codes). New codes added:
- `RUN_CANCELLED` (cooperative cancel accepted)
- `OUTPUT_CONTRACT_VIOLATION` (node returned undeclared role/kind)
- `ARTIFACT_STAGING_FAILED`
- `ARTIFACT_PUBLISH_FAILED`

`ErrorCode` sync with `frontend/src/api/errorCodes.ts` enforced by `tests/test_error_code_sync.py` (existing).