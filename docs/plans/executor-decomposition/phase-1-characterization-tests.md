# Phase 1: Characterization Contract Tests

**Goal:** Lock the existing behaviour of PlanExecutor before any refactor
by writing 6 characterization tests that must pass both before and after
all extractions.

## Files

- **Create:** `tests/test_executor_characterization.py`
- **Read (for style):** `tests/test_executor.py`, `tests/helpers/__init__.py`
- **Read (for contract understanding):** `cardre/executor.py`,
  `cardre/audit.py` (RunStepRecord, StepSpec, ArtifactRef),
  `cardre/store/project_store.py` (save_run_step, get_run_steps)

## Tests to Write (all pass against unrefactored executor)

### C1. `test_failed_step_records_resolved_input_evidence`

Setup: `make_store()`, three-step plan:
- `import` (ImportGermanCreditNode) — no parents
- `split` (SplitTrainTestOotNode) — parent: import
- `failing` (custom DummyFitNode subclass raising RuntimeError) — parent: split

Register all three nodes in a `NodeRegistry()`. Create plan version, run.

```python
def test_failed_step_records_resolved_input_evidence(self):
    class FailWithInputsNode(DummyFitNode):
        node_type = "cardre.test.fail_with_inputs"
        def run(self, context: ExecutionContext) -> NodeOutput:
            raise RuntimeError("Intentional failure")
    store, tmp = make_store()
    project_id = store.create_project("test")
    plan_id = store.create_plan(project_id, "test-plan")
    source = make_sample_german_credit_file(tmp)
    steps = [
        StepSpec(step_id="import", node_type="cardre.import_fixture_uci_german_credit",
                 node_version="1", category="transform",
                 params={"source_path": str(source)},
                 params_hash=json_logical_hash({"source_path": str(source)}),
                 parent_step_ids=[], branch_label="", position=0),
        StepSpec(step_id="split", node_type="cardre.split_train_test_oot",
                 node_version="1", category="transform",
                 params={"train_fraction": 0.6, "test_fraction": 0.2,
                         "oot_fraction": 0.2, "method": "random", "random_seed": 42},
                 params_hash=json_logical_hash(
                     {"train_fraction": 0.6, "test_fraction": 0.2,
                      "oot_fraction": 0.2, "method": "random", "random_seed": 42}),
                 parent_step_ids=["import"], branch_label="", position=1),
        StepSpec(step_id="failing", node_type="cardre.test.fail_with_inputs",
                 node_version="1", category="fit",
                 params={}, params_hash=json_logical_hash({}),
                 parent_step_ids=["split"], branch_label="", position=2),
    ]
    pv_id = store.create_plan_version(plan_id, steps)
    reg = NodeRegistry()
    reg.register(ImportGermanCreditNode)
    reg.register(SplitTrainTestOotNode)
    reg.register(FailWithInputsNode)
    executor = PlanExecutor(reg)
    run_id = executor.run_plan_version(store, pv_id)
    run = store.get_run(run_id)
    assert run["status"] == "failed"
    steps = store.get_run_steps(run_id)
    failing = next(s for s in steps if s.step_id == "failing")
    assert failing.status == "failed"
    assert failing.input_artifact_ids, "Failed step should record resolved input artifacts"
    assert failing.errors, "Failed step should have error entries"
    assert failing.errors[0]["code"], "Error entry should have a code"
    assert failing.errors[0]["message"], "Error entry should have a message"
    assert failing.errors[0]["traceback"], "Error entry should have a traceback"
    assert failing.errors[0]["category"], "Error entry should have a category"
```

### C2. `test_role_access_error_when_parent_outputs_have_no_matching_role`

Setup: custom source node producing role=`"test"` artifact. Child node
`input_roles=["train"]`, `category="apply"`.

```python
def test_role_access_error_when_parent_outputs_have_no_matching_role(self):
    class TestRoleSource(NodeType):
        node_type = "cardre.test.role_source"; version = "1"; category = "transform"
        input_roles = []; output_roles = ["test"]
        def run(self, context: ExecutionContext) -> NodeOutput:
            art = write_json_artifact(context.store, artifact_type="dataset", role="test",
                                      stem="test-art", payload={"x": 1}, metadata={})
            return NodeOutput(artifacts=[art], metrics={})
    class TestRoleChild(NodeType):
        node_type = "cardre.test.role_child"; version = "1"; category = "apply"
        input_roles = ["train"]; output_roles = ["prediction"]
        def run(self, context: ExecutionContext) -> NodeOutput:
            return NodeOutput(artifacts=[], metrics={})
    store, tmp = make_store()
    project_id = store.create_project("test")
    plan_id = store.create_plan(project_id, "test-plan")
    steps = [
        StepSpec(step_id="parent", node_type="cardre.test.role_source",
                 node_version="1", category="transform",
                 params={}, params_hash=json_logical_hash({}),
                 parent_step_ids=[], branch_label="", position=0),
        StepSpec(step_id="child", node_type="cardre.test.role_child",
                 node_version="1", category="apply",
                 params={}, params_hash=json_logical_hash({}),
                 parent_step_ids=["parent"], branch_label="", position=1),
    ]
    pv_id = store.create_plan_version(plan_id, steps)
    reg = NodeRegistry()
    reg.register(TestRoleSource); reg.register(TestRoleChild)
    executor = PlanExecutor(reg)
    run_id = executor.run_plan_version(store, pv_id)
    run = store.get_run(run_id)
    assert run["status"] == "failed"
    steps = store.get_run_steps(run_id)
    child = next(s for s in steps if s.step_id == "child")
    assert child.errors[0]["code"] == "ROLE_ACCESS_ERROR"
    assert child.errors[0]["category"] == "RoleAccessError"
```

### C3. `test_leakage_protection_blocks_test_dataset_for_fit_node`

Setup: parent produces `artifact_type="dataset"`, `role="test"`. Child node
`category="fit"`, `input_roles=["train","test"]` (so role filter passes,
leakage check fires). Child must NOT implement `allows_leakage_artifact`.

```python
def test_leakage_protection_blocks_test_dataset_for_fit_node(self):
    class TestLeakageSource(NodeType):
        node_type = "cardre.test.leakage_source"; version = "1"; category = "transform"
        input_roles = []; output_roles = ["test"]
        def run(self, context: ExecutionContext) -> NodeOutput:
            art = write_json_artifact(context.store, artifact_type="dataset", role="test",
                                      stem="leakage-test", payload={"x": 1}, metadata={})
            return NodeOutput(artifacts=[art], metrics={})
    class TestLeakageFit(NodeType):
        node_type = "cardre.test.leakage_fit"; version = "1"; category = "fit"
        input_roles = ["train", "test"]; output_roles = ["prediction"]
        def run(self, context: ExecutionContext) -> NodeOutput:
            return NodeOutput(artifacts=[], metrics={})
    store, tmp = make_store()
    project_id = store.create_project("test")
    plan_id = store.create_plan(project_id, "test-plan")
    steps = [
        StepSpec(step_id="source", node_type="cardre.test.leakage_source",
                 node_version="1", category="transform",
                 params={}, params_hash=json_logical_hash({}),
                 parent_step_ids=[], branch_label="", position=0),
        StepSpec(step_id="fit", node_type="cardre.test.leakage_fit",
                 node_version="1", category="fit",
                 params={}, params_hash=json_logical_hash({}),
                 parent_step_ids=["source"], branch_label="", position=1),
    ]
    pv_id = store.create_plan_version(plan_id, steps)
    reg = NodeRegistry()
    reg.register(TestLeakageSource); reg.register(TestLeakageFit)
    executor = PlanExecutor(reg)
    run_id = executor.run_plan_version(store, pv_id)
    run = store.get_run(run_id)
    assert run["status"] == "failed"
    steps = store.get_run_steps(run_id)
    fit = next(s for s in steps if s.step_id == "fit")
    assert fit.errors[0]["code"] == "LEAKAGE_PROTECTION_ERROR"
    assert fit.errors[0]["category"] == "LeakageProtectionError"
```

### C4. `test_execution_fingerprint_contract_for_successful_step`

Setup: two-step plan (source → child), using `SimpleSourceNode` and
`SimpleTransformNode` (define locally in the test file to avoid coupling).

```python
def test_execution_fingerprint_contract_for_successful_step(self):
    class FpSourceNode(NodeType):
        node_type = "cardre.test.fp_source"; version = "1"; category = "transform"
        input_roles = []; output_roles = ["artifact"]
        def run(self, context: ExecutionContext) -> NodeOutput:
            art = write_json_artifact(context.store, artifact_type="report", role="artifact",
                                      stem="fp-src", payload={}, metadata={})
            return NodeOutput(artifacts=[art], metrics={})
    class FpChildNode(NodeType):
        node_type = "cardre.test.fp_child"; version = "1"; category = "transform"
        input_roles = ["artifact"]; output_roles = ["artifact"]
        def run(self, context: ExecutionContext) -> NodeOutput:
            art = write_json_artifact(context.store, artifact_type="report", role="artifact",
                                      stem="fp-child", payload={}, metadata={})
            return NodeOutput(artifacts=[art], metrics={})
    store, tmp = make_store()
    project_id = store.create_project("test")
    plan_id = store.create_plan(project_id, "test-plan")
    steps = [
        StepSpec(step_id="source", node_type="cardre.test.fp_source",
                 node_version="1", category="transform",
                 params={}, params_hash=json_logical_hash({}),
                 parent_step_ids=[], branch_label="", position=0),
        StepSpec(step_id="child", node_type="cardre.test.fp_child",
                 node_version="1", category="transform",
                 params={}, params_hash=json_logical_hash({}),
                 parent_step_ids=["source"], branch_label="", position=1),
    ]
    pv_id = store.create_plan_version(plan_id, steps)
    reg = NodeRegistry()
    reg.register(FpSourceNode); reg.register(FpChildNode)
    executor = PlanExecutor(reg)
    run_id = executor.run_plan_version(store, pv_id)
    steps = store.get_run_steps(run_id)
    child = next(s for s in steps if s.step_id == "child")
    fp = child.execution_fingerprint
    assert fp["plan_version_id"] == pv_id
    assert fp["step_id"] == "child"
    assert fp["node_type"] == "cardre.test.fp_child"
    assert fp["node_version"] == "1"
    assert fp["params_hash"] == json_logical_hash({})
    assert isinstance(fp["parent_run_step_ids"], list) and len(fp["parent_run_step_ids"]) == 1
    assert isinstance(fp["input_artifact_logical_hashes"], list)
    assert isinstance(fp["output_artifact_logical_hashes"], list) and len(fp["output_artifact_logical_hashes"]) == 1
    assert "source" in fp["parent_output_logical_hashes_by_step"]
    assert isinstance(fp["parent_output_logical_hashes_by_step"]["source"], list)
    assert fp["python_version"].startswith("3.")
    assert fp["cardre_version"] == "0.1.0"
```

### C5. `test_run_to_node_executes_only_target_ancestor_closure`

Reuse `FpSourceNode` / `FpChildNode` (or define `SimpleSourceNode` /
`SimpleTransformNode`-like nodes). 5-step plan with unrelated branch.

```python
def test_run_to_node_executes_only_target_ancestor_closure(self):
    class TnSource(NodeType): ...  # same as FpSourceNode
    class TnTransform(NodeType): ...  # same as FpChildNode
    store, tmp = make_store()
    project_id = store.create_project("test")
    plan_id = store.create_plan(project_id, "test-plan")
    steps = [
        StepSpec(step_id="import", ..., parent_step_ids=[], ...),
        StepSpec(step_id="step_a", ..., parent_step_ids=["import"], ...),
        StepSpec(step_id="step_b", ..., parent_step_ids=["import"], ...),
        StepSpec(step_id="target", ..., parent_step_ids=["step_a"], ...),
        StepSpec(step_id="other_target", ..., parent_step_ids=["step_b"], ...),
    ]
    pv_id = store.create_plan_version(plan_id, steps)
    reg = NodeRegistry()
    reg.register(TnSource); reg.register(TnTransform)  # register once
    executor = PlanExecutor(reg)
    run_id = executor.run_to_node(store, pv_id, "target")
    run = store.get_run(run_id)
    assert run["status"] == "succeeded"
    executed = {s.step_id for s in store.get_run_steps(run_id)}
    assert "import" in executed
    assert "step_a" in executed
    assert "target" in executed
    assert "step_b" not in executed, "step_b is not in ancestor closure"
    assert "other_target" not in executed, "other_target is not in ancestor closure"
```

### C6. `test_replay_from_step_reuses_unaffected_and_executes_affected`

Setup: `unaffected-upstream` → `changed` → `changed-descendant` chain.

```python
def test_replay_from_step_reuses_unaffected_and_executes_affected(self):
    class RpSource(NodeType): ...
    class RpTransform(NodeType): ...
    store, tmp = make_store()
    project_id = store.create_project("test")
    plan_id = store.create_plan(project_id, "test-plan")
    steps = [
        StepSpec(step_id="unaffected-upstream", ...),
        StepSpec(step_id="changed", ...,
                 parent_step_ids=["unaffected-upstream"]),
        StepSpec(step_id="changed-descendant", ...,
                 parent_step_ids=["changed"]),
    ]
    pv_id = store.create_plan_version(plan_id, steps)
    reg = NodeRegistry()
    reg.register(RpSource); reg.register(RpTransform)
    executor = PlanExecutor(reg)
    original_run_id = executor.run_plan_version(store, pv_id)
    # Params change only triggers re-execute of "changed" and descendants.
    # Use identical params_hash target so unaffected-upstream is reused.
    new_run_id = executor.replay_from_step(
        store, plan_id, pv_id, "changed", {"k": "v"},
    )
    replay_steps = store.get_run_steps(new_run_id)
    reused = [s for s in replay_steps
              if s.execution_fingerprint.get("cardre_step_carried_forward")]
    executed = [s for s in replay_steps
                if not s.execution_fingerprint.get("cardre_step_carried_forward")]
    assert any(s.step_id == "unaffected-upstream" for s in reused)
    assert any(s.step_id == "changed" for s in executed)
    assert any(s.step_id == "changed-descendant" for s in executed)
    # Verify carry-forward fingerprint keys exist on reused steps
    for rs in reused:
        assert rs.execution_fingerprint["carried_forward_from_run_step_id"]
        assert rs.execution_fingerprint["carried_forward_from_run_id"] == original_run_id
```

## Verification

```bash
python3 -m pytest tests/test_executor_characterization.py -q --tb=short
```

Expected: all 6 tests pass against the unrefactored executor.

## Definition Of Done

- [ ] `tests/test_executor_characterization.py` created with all 6 tests.
- [ ] All 6 tests green against current `main` with `make preflight`.
- [ ] Tests do not depend on any refactored code (they test PlanExecutor
      public API only).

## Failure Mode

If a test fails:
- Check test data setup: `StepSpec` fields, node registration, store creation.
- The characterisation test asserts **current** behaviour. If the test fails
  on `main`, the behaviour is different from the plan's assumption — adjust
  the test to match reality, then proceed.
- Do not refactor to make the test pass. The test must pass the unrefactored
  code.
