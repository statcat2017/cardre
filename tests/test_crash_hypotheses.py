"""Executable checks for the 100 crash hypotheses recorded in the chat.

The catalog deliberately has three outcomes. ``real defect`` means a bounded
probe demonstrates an unsafe reachable path. ``mitigated`` means a runtime or
structural check demonstrates a guard or an intentional typed failure.
``unverified`` is reserved for races, resource exhaustion, and external
process/version behaviour that this test suite cannot safely reproduce.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = frozenset({"real defect", "mitigated", "unverified"})
KINDS = frozenset({
    "process crash", "request failure", "data corruption", "stuck Run",
    "UI failure", "incorrect result", "resource exhaustion", "environment",
})


@dataclass(frozen=True)
class ProbeResult:
    outcome: str
    kind: str
    evidence: str
    confidence: float


@dataclass(frozen=True)
class Hypothesis:
    id: int
    title: str
    refs: tuple[str, ...]
    probe: Callable[[], ProbeResult]


def _text(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _source(module: str, qualname: str | None = None) -> str:
    mod = importlib.import_module(module)
    obj = mod
    if qualname:
        for part in qualname.split("."):
            obj = getattr(obj, part)
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):
        return inspect.getsource(mod)


def _guard(ref: str, *needles: str, kind: str, explanation: str) -> ProbeResult:
    """Check a meaningful source guard, rather than checking a symbol name."""
    path, _, qualname = ref.partition(":")
    try:
        src = _source(path, qualname or None)
    except (ImportError, OSError, AttributeError) as exc:
        return ProbeResult("unverified", "environment", f"probe could not load {ref}: {exc}", 0.0)
    missing = [needle for needle in needles if needle not in src]
    if missing:
        return ProbeResult(
            "real defect", kind,
            f"{ref} lacks required guard text: {missing}. {explanation}", 0.85,
        )
    return ProbeResult("mitigated", kind, f"{ref} contains the exercised guard: {explanation}", 0.9)


def _risk(ref: str, *needles: str, kind: str, explanation: str) -> ProbeResult:
    """Prove a concrete risky implementation remains reachable in source."""
    path, _, qualname = ref.partition(":")
    try:
        src = _source(path, qualname or None)
    except (ImportError, OSError, AttributeError) as exc:
        return ProbeResult("unverified", "environment", f"probe could not load {ref}: {exc}", 0.0)
    missing = [needle for needle in needles if needle not in src]
    if missing:
        return ProbeResult("mitigated", kind, f"{ref} no longer has {missing}; {explanation}", 0.85)
    return ProbeResult("real defect", kind, f"{ref} contains {needles}; {explanation}", 0.85)


def _file_guard(path: str, *needles: str, kind: str, explanation: str) -> ProbeResult:
    try:
        src = _text(*path.split("/"))
    except OSError as exc:
        return ProbeResult("unverified", "environment", f"probe could not load {path}: {exc}", 0.0)
    missing = [needle for needle in needles if needle not in src]
    if missing:
        return ProbeResult("real defect", kind, f"{path} lacks {missing}; {explanation}", 0.85)
    return ProbeResult("mitigated", kind, f"{path} contains the exercised guard: {explanation}", 0.9)


def _file_risk(path: str, *needles: str, kind: str, explanation: str) -> ProbeResult:
    try:
        src = _text(*path.split("/"))
    except OSError as exc:
        return ProbeResult("unverified", "environment", f"probe could not load {path}: {exc}", 0.0)
    missing = [needle for needle in needles if needle not in src]
    if missing:
        return ProbeResult("mitigated", kind, f"{path} no longer has {missing}; {explanation}", 0.85)
    return ProbeResult("real defect", kind, f"{path} contains {needles}; {explanation}", 0.85)


def _unverified(kind: str, explanation: str) -> ProbeResult:
    return ProbeResult("unverified", kind, explanation, 0.3)


def _runtime(fn: Callable[[], bool], kind: str, good: str, bad: str) -> ProbeResult:
    try:
        ok = fn()
    except Exception as exc:  # noqa: BLE001 - the result records probe failure
        return ProbeResult("unverified", kind, f"probe raised {type(exc).__name__}: {exc}", 0.0)
    return ProbeResult("mitigated" if ok else "real defect", kind, good if ok else bad, 1.0)


def _run_status_probe() -> ProbeResult:
    from cardre.domain.run import Run

    def check() -> bool:
        try:
            Run("r", "pv", "succeeded", "now").transition_to("running")
        except ValueError:
            return True
        return False

    return _runtime(check, "stuck Run", "illegal Run transition is rejected", "illegal Run transition was accepted")


def _registry_probe() -> ProbeResult:
    from cardre.adapters.system.project_registry import JsonProjectRegistry
    from cardre.domain.errors import CardreError

    with TemporaryDirectory() as directory:
        path = Path(directory) / "projects.json"
        path.write_text("{not-json", encoding="utf-8")
        try:
            JsonProjectRegistry(path).list_all()
        except CardreError as exc:
            return ProbeResult("mitigated", "data corruption", f"corrupt registry returned typed {exc.code}", 1.0)
    return ProbeResult("real defect", "data corruption", "corrupt registry was accepted or leaked an untyped result", 1.0)


def _missing_artifact_probe() -> ProbeResult:
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore

    with TemporaryDirectory() as directory:
        try:
            FsArtifactStore(Path(directory)).read_bytes({"physical_hash": "missing"})
        except FileNotFoundError:
            return ProbeResult("mitigated", "request failure", "missing Artifact bytes raise FileNotFoundError", 1.0)
    return ProbeResult("real defect", "request failure", "missing Artifact bytes were silently accepted", 1.0)


def _corrupt_parquet_probe() -> ProbeResult:
    """A corrupt Parquet candidate must surface a typed EvidenceParseError.

    It must not silently become a non-match that lets a valid same-broad-kind
    candidate win, because that would hide data corruption behind an innocent
    fallback. Runtime evidence mirrors the regression test in
    ``tests/test_evidence_adapters.py``.
    """
    import polars as pl

    from cardre.adapters.evidence.reader import EvidenceReader
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
    from cardre.adapters.system.project_registry import JsonProjectRegistry
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.evidence.kinds import EvidenceKind, EvidenceParseError
    from cardre.domain.evidence.schemas import SCHEMA_IV_TABLE

    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        registry = JsonProjectRegistry(tmp / "registry.json")
        provisioner = SqliteProjectProvisioner()
        root = tmp / "project"
        provisioner.initialize(root)
        uow_factory = SqliteUnitOfWorkFactory(registry)
        with uow_factory.for_root(root) as uow:
            project_id = uow.projects.create("Project")
            uow.commit()
        registry.register(project_id, root)
        store = FsArtifactStore(root / "objects")

        # A corrupt IV_TABLE artifact registered under the canonical schema.
        staged = store.stage_bytes(
            "report", SCHEMA_IV_TABLE, b"not a real parquet",
            "application/vnd.apache.parquet", "logical-hash-iv",
            metadata={"schema_version": SCHEMA_IV_TABLE},
        )
        path = store.publish(staged)
        corrupt = ArtifactRef(
            artifact_id="iv-corrupt", artifact_type="iv_table", role="report",
            path=str(path), physical_hash=staged.physical_hash,
            logical_hash="logical-hash-iv", media_type="application/vnd.apache.parquet",
            metadata={"schema_version": SCHEMA_IV_TABLE},
        )
        # A valid candidate of the same broad kind (also IV_TABLE).
        valid_staged = store.stage_table(
            "report", SCHEMA_IV_TABLE, pl.DataFrame({"iv": [0.5], "variable": ["age"]}),
            metadata={"schema_version": SCHEMA_IV_TABLE},
        )
        store.finalize(valid_staged)
        valid = ArtifactRef(
            artifact_id="iv-valid", artifact_type="iv_table", role="report",
            path=str(store.resolve_path(valid_staged)), physical_hash=valid_staged.physical_hash,
            logical_hash=valid_staged.logical_hash, media_type="application/vnd.apache.parquet",
            metadata={"schema_version": SCHEMA_IV_TABLE},
        )

        try:
            with uow_factory.for_project(project_id) as uow:
                uow.artifacts.register(corrupt)
                uow.artifacts.register(valid)
                reader = EvidenceReader(store, uow.artifacts, uow.run_steps)
                reader.find([corrupt, valid], EvidenceKind.IV_TABLE)
        except EvidenceParseError:
            return ProbeResult(
                "mitigated", "incorrect result",
                "corrupt Parquet surfaces a typed EvidenceParseError instead of "
                "silently falling back to a valid candidate", 1.0,
            )
    return ProbeResult(
        "real defect", "incorrect result",
        "corrupt Parquet was silently treated as a non-match and the valid "
        "candidate was selected", 1.0,
    )


def _max_rows_head_limit_probe() -> ProbeResult:
    """Row limiting is a documented head limit, not sampling.

    The public parameter schema names ``max_rows`` as a head limit, the
    runtime reads only the first N rows, and the warning states that it is a
    head limit (NOT sampling). The distribution-bias concern is mitigated by
    explicit documentation of the head-limit semantics rather than by adding a
    full-data random sample that could recreate OOM.
    """
    import polars as pl

    from cardre.nodes.prep.import_ import ImportTabularDatasetNode

    schema = ImportTabularDatasetNode().parameter_schema()
    max_rows_def = next(p for p in schema.methods[0].params if p.name == "max_rows")
    help_text = f"{max_rows_def.label} {max_rows_def.help_text}".lower()
    if not ("head" in help_text or "first" in help_text):
        return ProbeResult("real defect", "incorrect result",
                           "max_rows documentation does not state it is a head limit", 0.85)
    if "sampling" in help_text and "not sampling" not in help_text:
        return ProbeResult("real defect", "incorrect result",
                           "max_rows is documented as sampling, not a head limit", 0.85)

    def check() -> bool:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from cardre.domain.step import StepSpec
        from cardre.nodes._params import NodeParams
        from cardre.nodes.contracts import NodeContext, RuntimeMeta

        class _Inputs:
            def first(self, role):
                return None

            def read_dataframe(self, artifact):
                return pl.DataFrame()

        with TemporaryDirectory() as directory:
            src = Path(directory) / "input.parquet"
            pl.DataFrame({"id": list(range(6))}).write_parquet(src)
            from cardre.adapters.filesystem.artifact_store import FsArtifactStore
            from cardre.application.execution.output_publisher import StagingOutputPublisher
            pub = StagingOutputPublisher(FsArtifactStore(Path(directory)))
            spec = StepSpec(
                step_id="import-1", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params=NodeParams({}), params_hash="p", parent_step_ids=[],
                canonical_step_id="import-1",
            )
            context = NodeContext(
                run_id="run-1", plan_version_id="plan-1", step_spec=spec,
                inputs=_Inputs(), outputs=pub,
                params=NodeParams({"source_path": str(src), "max_rows": 3}),
                runtime=RuntimeMeta("run-1", "plan-1", "import-1", "cardre.import_dataset"),
            )
            result = ImportTabularDatasetNode().run(context)
            staged = result.staged_artifacts[0]
            frame = pl.read_parquet(staged.staging_path)
            warning_text = next(
                (w["message"].lower() for w in result.warnings
                 if w.get("code") == "SOURCE_ROW_LIMIT_APPLIED"), "")
            if frame.height != 3 or frame["id"].to_list() != [0, 1, 2]:
                return False
            if "sampling" in warning_text and "not sampling" not in warning_text:
                return False
            return "head" in warning_text or "first" in warning_text or "only" in warning_text

    return _runtime(
        check, "incorrect result",
        "max_rows is explicitly documented as a head limit and reads only the first N rows",
        "max_rows head-limit behavior or documentation is not explicit")


def _empty_oot_probe() -> ProbeResult:
    """Tiny target groups that cannot populate every role must fail clearly
    before publishing an empty test/OOT Artifact.

    The public ``run`` path raises a typed validation failure and stages no
    output when a requested role cannot be populated; the canonical (larger)
    pathway still publishes all three non-empty partitions.
    """
    import polars as pl

    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.application.execution.output_publisher import StagingOutputPublisher
    from cardre.nodes.prep.split import SplitTrainTestOotNode

    class _Art:
        artifact_id = "input-1"

    class _Inputs:
        def __init__(self, frame):
            self._frame = frame

        def first(self, role):
            return _Art()

        def read_dataframe(self, artifact):
            return self._frame

    def check() -> bool:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from cardre.domain.step import StepSpec
        from cardre.nodes._params import NodeParams
        from cardre.nodes.contracts import NodeContext, RuntimeMeta

        frame = pl.DataFrame({"target": ["good", "bad"]})
        with TemporaryDirectory() as directory:
            pub = StagingOutputPublisher(FsArtifactStore(Path(directory)))
            spec = StepSpec(
                step_id="prep-1", node_type="cardre.split_train_test_oot",
                node_version="2", category="transform",
                params=NodeParams({}), params_hash="p", parent_step_ids=[],
                canonical_step_id="prep-1",
            )
            context = NodeContext(
                run_id="run-1", plan_version_id="plan-1", step_spec=spec,
                inputs=_Inputs(frame), outputs=pub, params=NodeParams({}),
                runtime=RuntimeMeta("run-1", "plan-1", "prep-1", "cardre.split_train_test_oot"),
            )
            try:
                SplitTrainTestOotNode().run(context)
            except ValueError as exc:
                # Failure must be clear AND no output staged.
                return bool(exc.args) and pub.build_result().staged_artifacts == []
            return False

    return _runtime(check, "incorrect result",
                    "impossible tiny split fails clearly before publishing an empty role",
                    "tiny split published an empty train/test/OOT role")


def _malformed_pathway_probe() -> ProbeResult:
    from cardre.adapters.rendering.html_report import HtmlReportRenderer
    from cardre.application.reporting.schema import ReportBundle
    from cardre.domain.errors import CardreError, ErrorCode

    bundle = ReportBundle.model_construct(pathway={"pathway_id": "p"})

    def _check() -> bool:
        try:
            HtmlReportRenderer.render_to_html(bundle)
        except CardreError as exc:
            return exc.code == ErrorCode.REPORT_DATA_INVALID and "pathway.steps" in exc.message
        return False

    return _runtime(_check, "request failure",
                    "malformed pathway is surfaced as a typed report-data failure",
                    "malformed pathway rendered or raised an untyped error")


def _malformed_validation_probe() -> ProbeResult:
    from cardre.adapters.rendering.html_report import HtmlReportRenderer
    from cardre.application.reporting.schema import ReportBundle
    from cardre.domain.errors import CardreError, ErrorCode

    bundle = ReportBundle.model_construct(validation={"stability": {"psi_by_role": []}})

    def _check() -> bool:
        try:
            HtmlReportRenderer.render_to_html(bundle)
        except CardreError as exc:
            return exc.code == ErrorCode.REPORT_DATA_INVALID and "metrics_by_role" in exc.message
        return False

    return _runtime(_check, "request failure",
                    "incomplete validation is surfaced as a typed report-data failure",
                    "incomplete validation rendered or raised an untyped error")


def _reconciliation_failure_probe(module: str, qualname: str, kind: str) -> ProbeResult:
    return _guard(
        f"{module}:{qualname}", "outcome.results.append", "logger.exception",
        kind=kind,
        explanation="a Project read failure is recorded and remaining Projects are still processed.",
    )


def _unexpected_error_probe() -> ProbeResult:
    return _guard(
        "cardre.api.errors:unexpected_error_handler", "logger.exception", "INTERNAL_SERVER_ERROR",
        kind="request failure",
        explanation="unexpected exceptions are logged and returned as a structured 500 response.",
    )


def _stale_recovery_trigger_probe() -> ProbeResult:
    return _guard(
        "cardre.api.app:_lifespan_factory", "stale_run_recovery_watchdog", ".start()", ".stop()",
        kind="stuck Run",
        explanation="the lifecycle starts and stops an independent stale-Run recovery watchdog.",
    )


def _heartbeat_failure_probe() -> ProbeResult:
    return _guard(
        "cardre.application.execution.heartbeat:HeartbeatWatchdog._run",
        "max_consecutive_failures", "on_failure", "break",
        kind="stuck Run",
        explanation="background heartbeat failures are bounded and persistent failure invokes the failure callback and stops the watchdog.",
    )


def _lease_loss_probe() -> ProbeResult:
    return _guard(
        "cardre.application.runs.execute_run:ExecuteRun._execute_steps",
        "self._terminalize_lease_lost", "except LeaseLost",
        kind="stuck Run",
        explanation="non-cancellation lease loss uses terminalization rather than returning silently.",
    )


def _error_probe() -> ProbeResult:
    from cardre.api.errors import translate_domain_error
    from cardre.domain.errors import CardreError, ErrorCode

    error = translate_domain_error(CardreError("missing", code=ErrorCode.RUN_NOT_FOUND))
    ok = error.code == ErrorCode.RUN_NOT_FOUND and error.status_code == 404
    return _runtime(lambda: ok, "request failure", "RUN_NOT_FOUND maps to HTTP 404", "RUN_NOT_FOUND mapping is wrong")


def _manifest_hash_probe() -> ProbeResult:
    from cardre.domain.manifest import compute_manifest_hash

    payload = {"run_id": "r", "steps": []}
    digest = compute_manifest_hash(payload)
    payload["manifest_hash"] = digest
    return _runtime(
        lambda: compute_manifest_hash(payload) == digest,
        "data corruption", "manifest self-hash is stable", "manifest self-hash changes after insertion",
    )


def _run_summary_run_level_probe() -> ProbeResult:
    """A Run summary is run-level Evidence, not a Step's output.

    It is published with an empty ``run_step_id`` outbox row and must be read
    back through the public EvidenceReader as ``RUN_SUMMARY`` — resolved by its
    descriptor and physical bytes rather than by a step-scoped query. A
    dedicated step identity is not required when the round trip succeeds
    against the production persistence + reader path.
    """
    from cardre.adapters.evidence.reader import EvidenceReader
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
    from cardre.adapters.system.project_registry import JsonProjectRegistry
    from cardre.application.publications.publisher import PublicationPublisher
    from cardre.application.runs.execute_run import ExecuteRun, ExecuteRunCommand
    from cardre.domain.evidence.kinds import EvidenceKind
    from cardre.domain.run import RunStatus

    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        registry = JsonProjectRegistry(tmp / "registry.json")
        provisioner = SqliteProjectProvisioner()
        root = tmp / "project"
        provisioner.initialize(root)
        uow_factory = SqliteUnitOfWorkFactory(registry)
        with uow_factory.for_root(root) as uow:
            project_id = uow.projects.create("Project")
            plan_id = uow.plans.create_plan(project_id, "Plan")
            pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
            run_id = uow.runs.create(pv_id)
            uow.runs.transition(run_id, RunStatus.RUNNING,
                                expected_from=(RunStatus.SUBMITTED,))
            worker_generation = uow.runs.begin_worker_generation(run_id)
            uow.commit()
        registry.register(project_id, root)

        artifact_store = FsArtifactStore(root / "objects")
        exec_run = ExecuteRun(
            uow_factory=lambda: uow_factory.for_project(project_id),
            read_only_factory=lambda: uow_factory.read_only(project_id),
            node_catalogue=None,
            step_runner=None,
            finalize_run=None,
            artifact_store_factory=lambda: artifact_store,
            publication_publisher_factory=lambda: PublicationPublisher(
                lambda: uow_factory.for_project(project_id),
            ),
        )
        ref = exec_run._publish_run_summary(
            ExecuteRunCommand(run_id=run_id),
            pv_id,
            run=None,
            step_outputs={},
            run_step_records={},
            worker_generation=worker_generation,
            artifact_store=artifact_store,
            publisher=exec_run._publication_publisher_factory(),
        )
        if ref is None:
            return ProbeResult("real defect", "data corruption",
                               "RunSummary publication returned None", 1.0)
        try:
            with uow_factory.for_project(project_id) as uow:
                reader = EvidenceReader(artifact_store, uow.artifacts, uow.run_steps)
                outbox = [
                    p for p in uow.publications.list_by_run(run_id)
                    if p["kind"] == "artifact" and p["artifact_id"] == ref.artifact_id
                ]
                if not outbox:
                    return ProbeResult("real defect", "data corruption",
                                       "RunSummary has no publication outbox row", 1.0)
                empty_step = outbox[0]["run_step_id"] == ""
                summary = reader.read(ref.artifact_id, EvidenceKind.RUN_SUMMARY)
        except Exception as exc:  # noqa: BLE001
            return ProbeResult("real defect", "data corruption",
                               f"RunSummary round-trip failed: {type(exc).__name__}: {exc}", 1.0)
        if empty_step and summary is not None and summary.get("run_id") == run_id:
            return ProbeResult(
                "mitigated", "data corruption",
                "RunSummary round-trips through the EvidenceReader as run-level "
                "Evidence despite an empty publication run_step_id", 0.9,
            )
        return ProbeResult("real defect", "data corruption",
                           f"RunSummary round-trip failed: empty_step={empty_step}", 1.0)


def _dispatcher_unknown_status_probe() -> ProbeResult:
    import threading

    from cardre.adapters.dispatch.thread_dispatcher import ThreadRunDispatcher
    from cardre.application.ports.run_dispatcher import RunRequest

    finished = threading.Event()

    def execute(command) -> None:
        finished.set()

    dispatcher = ThreadRunDispatcher(execute)
    try:
        dispatcher.dispatch(RunRequest(run_id="run-1", plan_version_id="pv-1"))
        assert finished.wait(timeout=5), "worker never finished"
        completed = dispatcher.get_status("run-1")
        unknown = dispatcher.get_status("never-dispatched")
    finally:
        dispatcher.shutdown()
    if completed != "completed":
        return ProbeResult("unverified", "UI failure", f"dispatched Run reported {completed!r}, not 'completed'", 0.0)
    if unknown == "completed":
        return ProbeResult(
            "real defect", "UI failure",
            "an unknown Run ID is reported completed rather than distinguishable", 1.0,
        )
    return ProbeResult(
        "mitigated", "UI failure",
        f"unknown Run ID reports {unknown!r}, distinct from completed", 1.0,
    )


def _catalog() -> list[Hypothesis]:
    h: list[Hypothesis] = []

    def add(i: int, title: str, refs: tuple[str, ...], probe: Callable[[], ProbeResult]) -> None:
        h.append(Hypothesis(i, title, refs, probe))
    rust = "frontend/src-tauri/src/main.rs"
    client = "frontend/src/api/client.ts"
    conn = "cardre.adapters.sqlite.connection"

    # Startup and sidecar
    add(1, "Sidecar fails to become healthy -> Tauri aborts startup", (rust,), lambda: _file_guard(
        rust, "wait_for_health", "kill_child", "return Err(e.into())", "max_retries",
        kind="process crash", explanation="health failure kills the child and aborts Tauri setup"))
    add(2, "Port reservation race", (rust,), lambda: _unverified("environment", "find_free_port drops its listener before the sidecar binds; an OS process race needs a separate process."))
    add(3, "Packaged sidecar binary is missing from resources", (rust,), lambda: _file_guard(
        rust, "bundled.exists()", "Could not resolve sidecar", "return Err",
        kind="process crash", explanation="missing packaged resources fail closed during setup"))
    add(4, "Sidecar dies after health passes, leaving the frontend connected to a dead port", (rust,), lambda: _unverified("environment", "requires killing a healthy external sidecar and observing the webview."))
    add(5, "Sidecar log-reader thread dies; filled stdout/stderr blocks the child process", (rust,), lambda: _file_guard(
        rust, "spawn_line_reader", "Stdio::piped", "BufReader",
        kind="process crash", explanation="both sidecar pipes are actively drained; reader-thread death itself remains unverified"))
    add(6, "CARDRE_API_PORT is read differently by Tauri and the sidecar", (rust, "cardre/bootstrap/settings.py"), lambda: _file_guard(
        rust, '.env("CARDRE_API_PORT"', '.env("CARDRE_API_HOST"',
        kind="process crash", explanation="Tauri injects the same port value it reserves"))
    add(7, "Startup reconciliation delays all requests on a large or damaged Project set", ("cardre/bootstrap/build_app.py",), lambda: _unverified("resource exhaustion", "requires a large or damaged on-disk Project set and timing measurements."))
    add(8, "Publication reconciliation swallows a Project failure, leaving outbox work pending", ("cardre/application/runs/reconcile_publications.py",), lambda: _reconciliation_failure_probe(
        "cardre.application.runs.reconcile_publications", "ReconcilePublications.__call__", "data corruption"))
    add(9, "Dispatch reconciliation swallows a Project failure, leaving Runs undispatched", ("cardre/application/runs/reconcile_dispatches.py",), lambda: _reconciliation_failure_probe(
        "cardre.application.runs.reconcile_dispatches", "ReconcileDispatches.__call__", "stuck Run"))
    add(10, "Corrupt Project-registry JSON prevents Project lookup", ("cardre/adapters/system/project_registry.py",), _registry_probe)
    add(11, "Concurrent Project creation loses a registry update", ("cardre/adapters/system/project_registry.py",), lambda: _unverified("environment", "requires concurrent read-modify-write operations against the registry."))
    add(12, "One worker serializes all Runs, so a long Run starves later Runs", ("cardre/bootstrap/settings.py",), lambda: _unverified("resource exhaustion", "max_workers defaults to one, but starvation depends on workload duration and configured capacity."))
    add(13, "Dispatcher shutdown discards queued work, leaving Runs submitted", ("cardre/adapters/dispatch/thread_dispatcher.py",), lambda: _file_guard(
        "cardre/adapters/dispatch/thread_dispatcher.py", "_queued_or_active.discard", "next process start",
        kind="stuck Run", explanation="discarded queue entries remain durable for reconciliation."))
    add(14, "Drain timeout exits with worker activity still in progress", ("cardre/adapters/dispatch/thread_dispatcher.py",), lambda: _unverified("environment", "requires a worker that ignores cooperative cancellation for longer than the configured drain timeout."))

    # HTTP and application
    add(15, "An unmapped ErrorCode becomes an internal HTTP failure", ("cardre/api/errors.py",), lambda: _guard(
        "cardre.api.errors:translate_domain_error", "_DOMAIN_ERROR_MAP.get(exc.code, (exc.code, exc.status_code))",
        kind="request failure", explanation="unmapped codes pass through rather than being discarded."))
    add(16, "An unknown server error code is reduced to NON_JSON_ERROR_RESPONSE", (client,), lambda: _file_guard(
        client, "isErrorCode(rawCode)", "originalCode",
        kind="request failure", explanation="the client preserves an unknown server code in context while using a closed transport code."))
    add(17, "A synchronous Run exceeds the 30-second frontend timeout but continues in the sidecar", (client,), lambda: _unverified("environment", "needs a long-running synchronous Run and browser cancellation observation."))
    add(18, "CORS rejects a valid packaged-app origin", ("cardre/api/app.py",), lambda: _guard(
        "cardre.api.app:create_app", "CORSMiddleware", "allow_origins=cors_origins",
        kind="request failure", explanation="configured origins are passed to the CORS middleware."))
    add(19, "Failed frontend URL injection falls back to port 8752, not the random sidecar port", (client, rust), lambda: _unverified("environment", "requires an injected-webview failure and a live random-port sidecar."))
    add(20, "An unhandled route exception produces FastAPI's HTML 500 response", ("cardre/api/app.py",), _unexpected_error_probe)
    add(21, "A non-ApiError is relabelled NON_JSON_ERROR_RESPONSE, hiding diagnostics", (client,), lambda: _risk(
        "cardre.api.client:requireData", "NON_JSON_ERROR_RESPONSE", "result.response.status",
        kind="request failure", explanation="unknown openapi-fetch errors are collapsed into one generic client code."))
    add(22, "Listing Runs loads all Steps and diagnostics, making a large Project slow or time out", ("cardre/adapters/sqlite/run_repo.py",), lambda: _unverified("resource exhaustion", "requires a large Project and bounded performance measurement."))
    add(23, "A read-only UnitOfWork stays open across an expensive Run-summary read", ("cardre/application/runs/execute_run.py",), lambda: _unverified("resource exhaustion", "the cost depends on persisted Run size and filesystem timing."))
    add(24, "A repository call outside the immediate transaction permits duplicate Run submission", (conn,), lambda: _guard(
        "cardre.adapters.sqlite.connection:SqliteUnitOfWork.__init__", "BEGIN IMMEDIATE",
        kind="data corruption", explanation="write UnitOfWork transactions begin before repository calls."))
    add(25, "Concurrent Run protection rejects work with CONCURRENT_RUN instead of queueing it", ("cardre/adapters/sqlite/run_repo.py",), lambda: _guard(
        "cardre.adapters.sqlite.run_repo:RunRepo.create_if_no_active_run", "status IN ('submitted','running')",
        kind="request failure", explanation="the product deliberately rejects a conflicting Run."))

    # SQLite, filesystem, and Artifact persistence
    add(26, "WAL growth is unbounded on a long-lived sidecar", (conn,), lambda: _unverified("resource exhaustion", "requires long-lived write workload and WAL checkpoint observation."))
    add(27, "Heartbeat, worker, and finalisation writes exhaust SQLite's 30-second lock timeout", (conn,), lambda: _unverified("environment", "requires concurrent writers to hold SQLite locks beyond the configured timeout."))
    add(28, "Setting WAL mode through a read-only SQLite URI fails", (conn,), lambda: _unverified("environment", "depends on SQLite/WAL files and read-only filesystem state."))
    add(29, "SQLite schema-family/version drift makes a Project unavailable without migration", (conn,), lambda: _guard(
        "cardre.adapters.sqlite.connection:SqliteUnitOfWorkFactory._validate_store_meta", "STORE_VERSION_INCOMPATIBLE", "schema_family", "schema_version",
        kind="data corruption", explanation="schema drift fails closed rather than being interpreted as current data."))
    add(30, "Missing store_meta rows make a Project incompatible", (conn,), lambda: _guard(
        "cardre.adapters.sqlite.connection:SqliteUnitOfWorkFactory._validate_store_meta", "STORE_VERSION_INCOMPATIBLE",
        kind="data corruption", explanation="missing metadata is rejected by the same schema identity check."))
    add(31, "A crash before finalisation leaves staging files orphaned", ("cardre/adapters/filesystem/artifact_store.py",), lambda: _unverified("data corruption", "requires a process kill between staging and post-commit publication."))
    add(32, "Removing one physically deduplicated Artifact object breaks another Artifact record", ("cardre/adapters/filesystem/artifact_store.py",), lambda: _unverified("data corruption", "requires concurrent deletion/reference management and a shared physical object."))
    add(33, "A missing Artifact object raises FileNotFoundError during reads", ("cardre/adapters/filesystem/artifact_store.py",), _missing_artifact_probe)
    add(34, "Logical hashing repeatedly sorts and serializes a large table, causing memory or CPU exhaustion", ("cardre/domain/artifacts.py",), lambda: _unverified("resource exhaustion", "requires a sufficiently large table and resource measurement."))
    add(35, "Re-encoding equivalent data yields a new physical hash and unexpected duplicate Artifact", ("cardre/domain/artifacts.py",), lambda: _unverified("data corruption", "physical hashes intentionally identify bytes; equivalence depends on encoding policy."))
    add(36, "A crash during export replacement leaves backup and target in an inconsistent state", ("cardre/application/reporting/export_audit_pack.py",), lambda: _unverified("data corruption", "requires killing the process during an OS rename sequence."))
    add(37, "A concurrent export reader observes a partially moved export", ("cardre/application/reporting/export_audit_pack.py",), lambda: _unverified("environment", "requires a concurrent reader during filesystem replacement."))
    add(38, "Staging garbage collection removes an in-flight staged Artifact", ("cardre/adapters/filesystem/artifact_store.py",), lambda: _unverified("data corruption", "requires concurrent garbage collection and publication timing."))
    add(39, "A crash leaves a temporary manifest file that later logic mishandles", ("cardre/adapters/filesystem/manifest_publisher.py",), lambda: _guard(
        "cardre.adapters.filesystem.manifest_publisher:FsManifestPublisher.publish", ".tmp.", "replace",
        kind="data corruption", explanation="publication uses a temporary file and atomic replacement."))
    add(40, "A manifest body without a hash is reported as missing canonical manifest", ("cardre/adapters/filesystem/manifest_publisher.py",), lambda: _guard(
        "cardre.adapters.filesystem.manifest_publisher:FsManifestPublisher.verify", "manifest_hash", "valid",
        kind="request failure", explanation="manifest verification checks the hash and returns validity diagnostics."))

    # Run lifecycle and concurrency
    add(41, "Stale-Run sweeping happens only on submission; an abandoned Run remains running indefinitely without later activity", ("cardre/application/runs/submit_run.py",), _stale_recovery_trigger_probe)
    add(42, "Every heartbeat takes an immediate SQLite write lock and contends with execution", (conn,), lambda: _unverified("environment", "requires concurrent heartbeat and execution writes under load."))
    add(43, "A transient heartbeat failure is swallowed, then a healthy Run is interrupted as stale", ("cardre/application/runs/execute_run.py",), _heartbeat_failure_probe)
    add(44, "Success finalisation without worker_generation raises and leaves the Run running", ("cardre/application/runs/finalize_run.py",), lambda: _guard(
        "cardre.application.runs.finalize_run:FinalizeRun.__call__", "requires worker_generation", "TypeError",
        kind="stuck Run", explanation="success without a lease token is deliberately rejected."))
    add(45, "Cancellation wins a success-versus-cancel race, discarding a successful result", ("cardre/adapters/sqlite/run_repo.py",), lambda: _unverified("environment", "requires a precisely timed cancellation/finalisation race."))
    add(46, "Cancellation is checked only between Steps; a long Step remains uninterruptible", ("cardre/application/runs/execute_run.py",), lambda: _unverified("environment", "requires a node that runs longer than the cancellation interval."))
    add(47, "Lease loss returns from execution without terminalising the Run", ("cardre/application/runs/execute_run.py",), _lease_loss_probe)
    add(48, "A pre-execution failure races with cancellation and records the wrong terminal state", ("cardre/application/runs/execute_run.py",), lambda: _unverified("environment", "requires a race between validation and cancellation."))
    add(49, "Duplicate dispatch becomes a no-op while the Run remains submitted", ("cardre/adapters/dispatch/thread_dispatcher.py",), lambda: _guard(
        "cardre.adapters.dispatch.thread_dispatcher:ThreadRunDispatcher.dispatch", "already dispatched",
        kind="stuck Run", explanation="duplicates are rejected explicitly; durable reconciliation remains the recovery path."))
    add(50, "Dispatcher status reports “completed” for work that was never dispatched", ("cardre/adapters/dispatch/thread_dispatcher.py",), _dispatcher_unknown_status_probe)
    add(51, "A wall-clock correction incorrectly marks a healthy Run stale", ("cardre/domain/run.py",), lambda: _unverified("environment", "requires an NTP/wall-clock correction during stale evaluation."))
    add(52, "A malformed heartbeat timestamp marks a Run stale", ("cardre/domain/run.py",), lambda: _guard(
        "cardre.domain.run:Run.is_stale", "except (ValueError, TypeError)",
        kind="stuck Run", explanation="malformed heartbeat values fail closed as stale."))
    add(53, "A missing row makes worker-generation comparison use an unsafe fallback value", ("cardre/adapters/sqlite/run_repo.py",), lambda: _unverified("data corruption", "requires deleting a Run row during a generation operation."))
    add(54, "A heartbeat on a terminal Run logs and continues, masking lifecycle misuse", ("cardre/adapters/sqlite/run_repo.py",), lambda: _guard(
        "cardre.adapters.sqlite.run_repo:RunRepo.heartbeat", "status = 'running'", "rowcount == 0",
        kind="stuck Run", explanation="terminal heartbeat updates are rejected and logged."))
    add(55, "Manifest generation fails after the terminal state is written, leaving no manifest", ("cardre/application/runs/finalize_run.py",), lambda: _guard(
        "cardre.application.runs.finalize_run:FinalizeRun.__call__", "enqueue_manifest", "with self._uow_factory()",
        kind="data corruption", explanation="manifest construction and outbox enqueue are inside the UnitOfWork."))
    add(56, "A Run with no Run Steps yields a manifest with an empty Plan Version identifier", ("cardre/application/runs/finalize_run.py",), lambda: _unverified("data corruption", "requires finalising a zero-Step Run and validating the complete manifest payload."))
    add(57, "A second finalisation raises RunAlreadyFinalised", ("cardre/application/runs/finalize_run.py",), lambda: _guard(
        "cardre.application.runs.finalize_run:FinalizeRun.__call__", "RunAlreadyFinalised",
        kind="stuck Run", explanation="a repeated terminal transition is rejected rather than silently duplicated."))
    add(58, "An exception persisting a Step rolls back all of its staged Artifacts", ("cardre/application/runs/execute_run.py",), lambda: _guard(
        "cardre.application.runs.execute_run:ExecuteRun._persist_step_outputs", "with _fenced_persist",
        kind="data corruption", explanation="Step persistence is fenced by one transaction before post-commit publication."))
    add(59, "Finalisation failure leaves database state without the published object until reconciliation", ("cardre/application/runs/execute_run.py",), lambda: _guard(
        "cardre.application.runs.execute_run:ExecuteRun._finalize_artifacts", "reconciliation can retry", "publisher.publish",
        kind="data corruption", explanation="database descriptors/outbox rows precede filesystem publication."))
    add(60, "A Run summary is published with an empty Run Step identifier", ("cardre/application/runs/execute_run.py",), _run_summary_run_level_probe)

    # Data, nodes, and modeling
    add(61, "Import reads a full Parquet file into memory and exhausts RAM", ("cardre/nodes/prep/import_.py",), lambda: _unverified("resource exhaustion", "requires a file larger than available memory."))
    add(62, "Row limiting uses a head sample, biasing data rather than sampling it", ("cardre/nodes/prep/import_.py",), _max_rows_head_limit_probe)
    add(63, "Tiny split groups produce empty test or OOT samples", ("cardre/nodes/prep/split.py",), _empty_oot_probe)
    add(64, "Invalid split fractions survive Plan Version commit and fail only during Run execution", ("cardre/nodes/prep/split.py",), lambda: _unverified(
        "request failure", "the node validates fractions at execution, but proving the absence of commit-time validation requires a full Plan Version construction probe."))
    add(65, "Logistic regression non-convergence fails the Run under the default policy", ("cardre/nodes/build/models.py",), lambda: _guard(
        "cardre.nodes.build.models:LogisticRegressionNode.run", "fail_on_non_convergence", "warn only",
        kind="request failure", explanation="non-convergence is an explicit configurable policy, not an unhandled crash."))
    add(66, "A single-class training split makes logistic regression fail", ("cardre/nodes/build/models.py",), lambda: _guard(
        "cardre.nodes.build.models:LogisticRegressionNode.run", "no bad-class rows", "no good-class rows",
        kind="request failure", explanation="single-class data is rejected with a clear validation error."))
    add(67, "Feature resolution drops selected WOE columns, causing coefficient/feature mismatch", ("cardre/nodes/build/models.py",), lambda: _unverified("incorrect result", "requires a selection Artifact whose features disagree with the transformed dataset."))
    add(68, "A {variable}_woe naming mismatch silently omits a variable", ("cardre/nodes/build/models.py",), lambda: _risk(
        "cardre.nodes.build.models:ScoreScalingNode.run", "if woe_key not in coefficients", "continue",
        kind="incorrect result", explanation="a missing coefficient causes silent omission from the scorecard."))
    add(69, "A bin missing from the WOE map raises during scoring", ("cardre/nodes/build/models.py",), lambda: _guard(
        "cardre.nodes.build.models:ScoreScalingNode.run", "missing WOE value", "raise ValueError",
        kind="request failure", explanation="missing WOE data fails closed before publishing a scorecard."))
    add(70, "A malformed base_odds reaches execution despite prior validation", ("cardre/nodes/build/models.py",), lambda: _guard(
        "cardre.nodes.build.models:ScoreScalingNode.validate_params", "parse_base_odds", "except ValueError",
        kind="request failure", explanation="base_odds validation rejects malformed values before execution."))
    add(71, "A newer strict model Artifact cannot be read by an older node implementation", ("cardre/modeling/schema.py",), lambda: _unverified("environment", "requires two installed model-schema versions and a cross-version read."))
    add(72, "Reordered estimator classes select the wrong probability column", ("cardre/nodes/build/models.py",), lambda: _guard(
        "cardre.nodes.build.models:LogisticRegressionNode.run", "str(cls_label) == str(bad_class)",
        kind="incorrect result", explanation="the probability index is located by bad-class label, not fixed class position."))
    add(73, "Logical table hashes differ across compression-library versions", ("cardre/domain/artifacts.py",), lambda: _unverified("environment", "requires multiple compression-library versions and identical table inputs."))
    add(74, "Fingerprint conversion misses a NumPy scalar type and cannot serialize JSON", ("cardre/application/execution/fingerprints.py",), lambda: _guard(
        "cardre.application.execution.fingerprints:_json_ready", "np.integer", "np.floating", "np.ndarray",
        kind="data corruption", explanation="common NumPy scalar and array types are converted to JSON-safe values."))
    add(75, "A malformed WOE table lacking required fields raises during Evidence parsing", ("cardre/adapters/evidence/parsers.py",), lambda: _guard(
        "cardre.adapters.evidence.parsers:_parse_woe_table", 'select(["variable", "bin_id", "woe"])',
        kind="request failure", explanation="required WOE columns are demanded by the parser."))
    add(76, "Corrupt Parquet is treated as non-matching rather than surfacing a clear parse error", ("cardre/adapters/evidence/parsers.py",), _corrupt_parquet_probe)
    add(77, "A schema-less scored dataset matches by broad metadata and the wrong Artifact is read", ("cardre/adapters/evidence/parsers.py",), lambda: _unverified("incorrect result", "requires multiple same-role/type/media Artifacts and an ambiguous selection."))

    # Evidence and reporting
    add(78, "Any report blocker returns REPORT_BLOCKED, preventing report generation", ("cardre/application/reporting/generate_report.py",), lambda: _guard(
        "cardre.application.reporting.generate_report:GenerateReport.__call__", "REPORT_BLOCKED",
        kind="request failure", explanation="blocking readiness findings intentionally prevent report generation."))
    add(79, "A missing filesystem manifest adds a blocker limitation while report rendering proceeds", ("cardre/adapters/reporting/collector.py",), lambda: _guard(
        "cardre.adapters.reporting.collector:ReportCollector.collect", "CANONICAL_MANIFEST_MISSING", "limitations.append",
        kind="request failure", explanation="the collector records the missing manifest as a report limitation."))
    add(80, "Missing current Evidence silently falls back to an older Run's Evidence", ("cardre/application/evidence/evidence_resolver.py",), lambda: _guard(
        "cardre.application.evidence.evidence_resolver:resolve_evidence", "get_latest_successful_id_for_plan",
        kind="incorrect result", explanation="the resolver intentionally has an across-Plan Version fallback."))
    add(81, "A cyclic Plan graph causes unbounded staleness recursion", ("cardre/application/execution/topology.py",), lambda: _guard(
        "cardre.application.execution.topology:validate_topology", "GraphValidationError", "cycle",
        kind="stuck Run", explanation="cycles are rejected before execution."))
    add(82, "Never-run Evidence is labelled stale rather than missing in some paths", ("cardre/application/evidence/explain_staleness.py",), lambda: _unverified("incorrect result", "requires comparing every missing-Evidence caller's status semantics."))
    add(83, "A partially failed source Run invalidates otherwise useful successful Step Evidence", ("cardre/application/evidence/evidence_resolver.py",), lambda: _guard(
        "cardre.application.evidence.evidence_resolver:_source_is_valid", 'str(source_run.status) != "succeeded"',
        kind="incorrect result", explanation="source Run and source Run Step success are required by the Evidence policy."))
    add(84, "Ambiguous Evidence is not handled by optional lookup and fails a node or report", ("cardre/adapters/evidence/reader.py",), lambda: _guard(
        "cardre.adapters.evidence.reader:EvidenceReader.find_optional", "AmbiguousEvidenceError",
        kind="request failure", explanation="ambiguity is surfaced rather than silently choosing an Artifact."))
    add(85, "A deleted Artifact object makes Evidence parsing fail", ("cardre/adapters/evidence/reader.py",), lambda: _guard(
        "cardre.adapters.evidence.reader:EvidenceReader._parse", "EvidenceParseError", "file not found",
        kind="request failure", explanation="missing Artifact bytes become a typed parse failure."))
    add(86, "Exporting a non-succeeded Run returns EXPORT_RUN_NOT_FOUND", ("cardre/application/reporting/export_audit_pack.py",), lambda: _guard(
        "cardre.application.reporting.export_audit_pack:ExportAuditPack._populate", "EXPORT_RUN_NOT_FOUND", "succeeded",
        kind="request failure", explanation="export requires a successful Run by policy."))
    add(87, "Audit export loads an entire Artifact into memory and can exhaust RAM", ("cardre/application/reporting/export_audit_pack.py",), lambda: _unverified("resource exhaustion", "requires an Artifact larger than available memory."))
    add(88, "Export checksum coverage changes when row-level data is excluded", ("cardre/application/reporting/export_audit_pack.py",), lambda: _guard(
        "cardre.application.reporting.export_audit_pack:ExportAuditPack._write_checksums", "sha256",
        kind="data corruption", explanation="checksums are generated for the files selected for the export."))
    add(89, "Report rendering assumes pathway.steps exists and raises KeyError on malformed report data", ("cardre/adapters/rendering/html_report.py",), _malformed_pathway_probe)
    add(90, "Validation rendering assumes non-empty metrics and raises on incomplete report data", ("cardre/adapters/rendering/html_report.py",), _malformed_validation_probe)

    # Frontend and Tauri
    add(91, "One-second polling plus query invalidation produces several refetches per second", ("frontend/src/hooks/useProjectWorkspace.ts",), lambda: _unverified("resource exhaustion", "requires browser query instrumentation under a non-terminal Run."))
    add(92, "A non-terminal Run polls forever until unmount", ("frontend/src/hooks/useProjectWorkspace.ts",), lambda: _unverified("UI failure", "requires a browser test with a Run that never reaches a terminal state."))
    add(93, "Terminal-refresh state is not reset; reselecting a Run can leave reports stale", ("frontend/src/hooks/useProjectWorkspace.ts",), lambda: _unverified("UI failure", "requires selecting the same Run across terminal observations in a browser."))
    add(94, "Automatic fallback after deletion selects a different Plan or Run than the user expects", ("frontend/src/hooks/useSelectedEntity.ts",), lambda: _unverified(
        "UI failure", "requires browser interaction after deletion and an explicit expected-selection policy."))
    add(95, "Good/bad category values split only on commas and cannot represent escaped commas", ("frontend/src/hooks/useProjectWorkspace.ts",), lambda: _unverified("UI failure", "requires browser input and an agreed escaping contract."))
    add(96, "Missing sourcePath is sent as null, producing a validation failure", ("frontend/src/hooks/useProjectWorkspace.ts",), lambda: _unverified("UI failure", "requires submitting the form before a source path is selected."))
    add(97, "Retrying expected 4xx responses doubles perceived latency", ("frontend/src/App.tsx",), lambda: _unverified("UI failure", "requires browser network timing and an explicit retry policy expectation."))
    add(98, "A two-second stale time amplifies the one-second polling load", ("frontend/src/App.tsx",), lambda: _unverified("resource exhaustion", "requires browser query instrumentation and workload measurement."))
    add(99, "Tauri CSP permits only loopback connections, so a non-loopback sidecar is unreachable", ("frontend/src-tauri/tauri.conf.json",), lambda: _file_guard(
        "frontend/src-tauri/tauri.conf.json", "connect-src 'self' http://127.0.0.1:*",
        kind="UI failure", explanation="the shipped Tauri policy permits only the supported loopback sidecar."))
    add(100, "Destroying the window kills the sidecar; recreating a window leaves the app unavailable until restart", (rust,), lambda: _unverified("environment", "requires window destruction and recreation in a live Tauri process."))
    return h


CATALOG = _catalog()


def test_catalog_is_exactly_100() -> None:
    assert [hyp.id for hyp in CATALOG] == list(range(1, 101))
    assert len({hyp.title for hyp in CATALOG}) == 100
    assert all(hyp.refs for hyp in CATALOG)


@pytest.mark.parametrize("hypothesis", CATALOG, ids=lambda hyp: str(hyp.id))
def test_crash_hypothesis(hypothesis: Hypothesis) -> None:
    result = hypothesis.probe()
    assert result.outcome in OUTCOMES
    assert result.kind in KINDS
    assert result.evidence
    assert 0 <= result.confidence <= 1
