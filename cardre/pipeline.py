"""Auditable pipeline plans and run records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Protocol

from cardre.audit import ArtifactRef, JsonDict, StepRecord, stable_hash, utc_now_iso
from cardre.store import DataSnapshot, ProjectStore


class PipelineStep(Protocol):
    """A model-building step that records its inputs and outputs."""

    name: str
    version: str

    def run(self, context: "StepContext") -> StepRecord:
        """Execute the step and return its audit record."""


@dataclass(frozen=True)
class StepSpec:
    """Planned step configuration, independent of execution results."""

    step_id: str
    name: str
    version: str
    params: JsonDict = field(default_factory=dict)
    parent_step_ids: list[str] = field(default_factory=list)
    branch_label: str = ""

    def to_dict(self) -> JsonDict:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "version": self.version,
            "params": self.params,
            "params_hash": self.params_hash,
            "parent_step_ids": self.parent_step_ids,
            "branch_label": self.branch_label,
        }

    @property
    def params_hash(self) -> str:
        return stable_hash(self.params)

    @classmethod
    def from_dict(cls, data: JsonDict) -> "StepSpec":
        return cls(
            step_id=data["step_id"],
            name=data["name"],
            version=data["version"],
            params=dict(data.get("params", {})),
            parent_step_ids=list(data.get("parent_step_ids", [])),
            branch_label=data.get("branch_label", ""),
        )


@dataclass(frozen=True)
class PipelinePlan:
    """A reproducible recipe for building a scorecard model."""

    plan_id: str
    name: str
    steps: list[StepSpec]
    created_at: str = field(default_factory=utc_now_iso)
    description: str = ""

    def to_dict(self) -> JsonDict:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> "PipelinePlan":
        return cls(
            plan_id=data["plan_id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data.get("created_at", utc_now_iso()),
            steps=[StepSpec.from_dict(step) for step in data.get("steps", [])],
        )

    def replace_step_params(self, step_id: str, params: JsonDict) -> "PipelinePlan":
        """Return a new plan with one step's parameters changed.

        Plans are treated as recipes. Editing a historical plan in-place would
        destroy auditability, so parameter edits produce a new plan object while
        preserving step ids and downstream ordering.
        """

        next_steps = []
        for step in self.steps:
            next_steps.append(replace(step, params=params) if step.step_id == step_id else step)
        if len(next_steps) == len(self.steps) and all(
            before is after for before, after in zip(self.steps, next_steps, strict=True)
        ):
            raise KeyError(step_id)
        return replace(self, steps=next_steps)

    def step_index(self, step_id: str) -> int:
        for index, step in enumerate(self.steps):
            if step.step_id == step_id:
                return index
        raise KeyError(step_id)

    def step_ids(self) -> set[str]:
        return {step.step_id for step in self.steps}

    def descendants_of(self, step_id: str) -> set[str]:
        if step_id not in self.step_ids():
            raise KeyError(step_id)
        descendants = set()
        changed = True
        while changed:
            changed = False
            for step in self.steps:
                if step.step_id in descendants:
                    continue
                if step_id in step.parent_step_ids or descendants.intersection(step.parent_step_ids):
                    descendants.add(step.step_id)
                    changed = True
        return descendants


@dataclass
class StepContext:
    """Runtime context passed to a pipeline step."""

    store: ProjectStore
    run_id: str
    spec: StepSpec
    input_artifacts: list[ArtifactRef]
    previous_records: list[StepRecord] = field(default_factory=list)
    working_artifacts: list[ArtifactRef] = field(default_factory=list)

    @property
    def latest_artifacts(self) -> list[ArtifactRef]:
        return self.input_artifacts

    def publish(self, outputs: list[ArtifactRef]) -> None:
        self.working_artifacts = outputs

    def record(
        self,
        *,
        outputs: list[ArtifactRef],
        metrics: JsonDict | None = None,
        status: str = "succeeded",
        notes: str = "",
    ) -> StepRecord:
        return StepRecord(
            step_id=self.spec.step_id,
            name=self.spec.name,
            version=self.spec.version,
            params=self.spec.params,
            params_hash=self.spec.params_hash,
            parent_step_ids=self.spec.parent_step_ids,
            inputs=self.latest_artifacts,
            outputs=outputs,
            branch_label=self.spec.branch_label,
            metrics=metrics or {},
            status=status,
            notes=notes,
        )


@dataclass(frozen=True)
class PipelineRun:
    """Complete audit record for one model-building run."""

    run_id: str
    plan: PipelinePlan
    input_snapshot: DataSnapshot
    records: list[StepRecord]
    started_at: str
    completed_at: str
    status: str = "succeeded"

    @classmethod
    def start(cls, plan: PipelinePlan, input_snapshot: DataSnapshot) -> "PipelineRunBuilder":
        return PipelineRunBuilder(
            run_id=str(uuid.uuid4()),
            plan=plan,
            input_snapshot=input_snapshot,
            started_at=utc_now_iso(),
        )

    def to_dict(self) -> JsonDict:
        return {
            "run_id": self.run_id,
            "plan": self.plan.to_dict(),
            "input_snapshot": self.input_snapshot.to_dict(),
            "records": [record.to_dict() for record in self.records],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> "PipelineRun":
        return cls(
            run_id=data["run_id"],
            plan=PipelinePlan.from_dict(data["plan"]),
            input_snapshot=DataSnapshot.from_dict(data["input_snapshot"]),
            records=[StepRecord.from_dict(record) for record in data.get("records", [])],
            started_at=data["started_at"],
            completed_at=data.get("completed_at", utc_now_iso()),
            status=data.get("status", "succeeded"),
        )


@dataclass
class PipelineRunBuilder:
    run_id: str
    plan: PipelinePlan
    input_snapshot: DataSnapshot
    started_at: str
    records: list[StepRecord] = field(default_factory=list)

    def append(self, record: StepRecord) -> None:
        self.records.append(record)

    def finish(self, *, status: str = "succeeded") -> PipelineRun:
        return PipelineRun(
            run_id=self.run_id,
            plan=self.plan,
            input_snapshot=self.input_snapshot,
            records=list(self.records),
            started_at=self.started_at,
            completed_at=utc_now_iso(),
            status=status,
        )

    def save(self, store: ProjectStore, *, status: str = "succeeded") -> PipelineRun:
        run = self.finish(status=status)
        store.write_json(store.runs_dir / f"{self.run_id}.json", run.to_dict())
        return run


class PipelineExecutor:
    """Execute and replay branching scorecard-building plans.

    A plan is a topologically ordered tree/DAG. Multiple steps can share a
    parent, which gives the GUI PowerBI-style branching: try two binning options
    from the same profile node, score both, and compare their outputs. Replaying
    from one node only regenerates that node and its descendants.
    """

    def __init__(self, steps: dict[str, PipelineStep]) -> None:
        self.steps = steps

    def run(
        self,
        plan: PipelinePlan,
        input_snapshot: DataSnapshot,
        store: ProjectStore,
        *,
        previous_run: PipelineRun | None = None,
        from_step_id: str | None = None,
    ) -> PipelineRun:
        self._validate_plan(plan)
        replay_step_ids = set(plan.step_ids()) if from_step_id is None else {from_step_id} | plan.descendants_of(from_step_id)
        previous_records = {} if previous_run is None else {record.step_id: record for record in previous_run.records}
        builder = PipelineRun.start(plan, input_snapshot)
        records_by_id: dict[str, StepRecord] = {}

        for spec in plan.steps:
            if spec.step_id not in replay_step_ids:
                retained = previous_records.get(spec.step_id)
                if retained is None:
                    raise ValueError(f"Cannot retain missing prior record for {spec.step_id!r}")
                builder.append(retained)
                records_by_id[spec.step_id] = retained
                continue

            step = self.steps.get(spec.name)
            if step is None:
                raise KeyError(f"No implementation registered for step {spec.name!r}")
            input_artifacts = self._input_artifacts_for(spec, input_snapshot, records_by_id)
            context = StepContext(
                store=store,
                run_id=builder.run_id,
                spec=spec,
                input_artifacts=input_artifacts,
                previous_records=list(records_by_id.values()),
            )
            record = step.run(context)
            builder.append(record)
            records_by_id[spec.step_id] = record

        return builder.save(store)

    def replay_from(
        self,
        previous_run: PipelineRun,
        plan: PipelinePlan,
        input_snapshot: DataSnapshot,
        store: ProjectStore,
        *,
        step_id: str,
        params: JsonDict,
    ) -> PipelineRun:
        updated_plan = plan.replace_step_params(step_id, params)
        return self.run(
            updated_plan,
            input_snapshot,
            store,
            previous_run=previous_run,
            from_step_id=step_id,
        )

    def _validate_plan(self, plan: PipelinePlan) -> None:
        seen = set()
        for step in plan.steps:
            if step.step_id in seen:
                raise ValueError(f"Duplicate step_id {step.step_id!r}")
            missing_parents = set(step.parent_step_ids) - seen
            if missing_parents:
                raise ValueError(
                    f"Step {step.step_id!r} references missing or later parents: "
                    f"{sorted(missing_parents)!r}"
                )
            seen.add(step.step_id)

    def _input_artifacts_for(
        self,
        spec: StepSpec,
        input_snapshot: DataSnapshot,
        records_by_id: dict[str, StepRecord],
    ) -> list[ArtifactRef]:
        if not spec.parent_step_ids:
            return [input_snapshot.artifact]
        artifacts = []
        for parent_step_id in spec.parent_step_ids:
            parent_record = records_by_id.get(parent_step_id)
            if parent_record is None:
                raise ValueError(f"Parent step {parent_step_id!r} has no record yet")
            artifacts.extend(parent_record.outputs)
        return artifacts
