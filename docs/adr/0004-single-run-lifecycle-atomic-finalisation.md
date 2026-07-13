# Single Run Lifecycle And Atomic Finalisation

## Status

Proposed

## Historical note

PR4 removed the dead evidence-reuse / `run_to_node` execution subsystem.
PR8 replaced the bare-string run-status writer (`RunRepository.finish`)
with `RunRepository.transition(run_id, RunStatus.X, expected_from=...)`,
the single atomic terminal-status writer, and introduced the `RunStatus`
enum. References below to reuse actions or `run_to_node` describe the
pre-PR4 shape that motivated this ADR, not the current implementation.

## Context

Cardre's execution core (`PlanExecutor`) has three public run methods: `run_plan_version`, `run_branch`, and `run_to_node`. A fourth path, `replay_from_step`, exists outside the public seam. Each path handles run creation, step execution, reuse/carry-forward, cancellation, finalisation, and manifest writing differently.

The current state has several structural problems:

1. **Planning writes before execution.** `run_to_node` calls `_reuse_run_step` while building the action list, and `_reuse_run_step` immediately saves a carried-forward run step to the store. This means planning mutates run state before cancellation checks or execution begins. A cancelled run can already contain carried-forward evidence that was never processed.

2. **Replay bypasses the lifecycle entirely.** `replay_from_step` creates runs directly, saves carried-forward steps directly, and calls `store.finish_run` without writing a run manifest or registering cancellation. It is a second orchestration path beside `RunLifecycle`.

3. **Finalisation is not atomic.** `finalise_run` calls `store.finish_run` before `write_manifest`. If manifest generation fails, a run can be marked `succeeded` without its audit manifest. The docstring on `RunFinalisation` acknowledges that `run_step_records` and `steps` are "reserved for future deterministic manifest construction" but are not forwarded to `write_manifest`, which reads directly from store state.

4. **Cancellation is not guaranteed.** Executor paths call `finalise` after `_execute_actions` rather than in a `finally` block, despite `RunLifecycle`'s docstring promising that pattern. An exception between execution and finalisation can leave a run stuck in `running` state.

ADR 0002 committed to a single execution path through `PlanExecutor`. The subsequent `RunLifecycle` extraction was consistent with that commitment, but the current code has drifted from the intent.

## Decision

1. **`RunLifecycle` becomes the only supported finalisation mechanism.** Every execution mode — full-plan, branch, to-node, and replay — must use `RunLifecycle` for run creation, cancellation registration, and finalisation. No direct `store.create_run`, `store.finish_run`, or `store.save_run_step` calls outside `RunLifecycle` or `_execute_actions`.

2. **Planning is pure.** Action planning (building the `_StepAction` list) must not write to the store. Reuse/carry-forward writes happen only inside `_execute_actions`, through the same result-recording path as executed steps. A reuse action carries a source reference; the store write is deferred until execution.

3. **Finalisation is atomic.** `finalise_run` must either succeed completely (finish run + write manifest) or leave the run in a state that reflects the failure. The manifest write must happen before or atomically with the status transition. If manifest writing fails, the run must not be marked `succeeded`.

4. **Finalisation is guaranteed.** `RunLifecycle` must be used as a context manager or with a `try/finally` pattern so that interrupted execution cannot skip finalisation. A cancelled or crashed run must be marked `failed` or `cancelled`, never left `running`.

5. **Replay is expressed as planned actions.** `replay_from_step` is replaced by building `_StepAction` instances for the affected steps and running them through `_execute_actions` with a `RunLifecycle`. Carried-forward steps for unaffected steps are planned as reuse actions, not written directly.

## Consequences

- **Easier:** run state is predictable. Every execution mode follows the same lifecycle, so cancellation, finalisation, and manifest writing cannot diverge.
- **Easier:** new execution modes (e.g., "run to node on a branch") can be added without reimplementing lifecycle mechanics.
- **Easier:** tests can assert on lifecycle outcomes (run status, manifest presence, cancellation) uniformly across modes.
- **Harder:** `replay_from_step` must be refactored to use the action pipeline, which may require changes to how the replay caller expects the run to be created and returned.
- **Harder:** the action planning loop must be restructured so that reuse decisions are recorded as action metadata rather than executed eagerly.
- **Risk:** if the atomic finalisation path is too strict, a manifest write failure could leave a run in an ambiguous state. The design should handle this by recording manifest failure explicitly rather than silently succeeding.
