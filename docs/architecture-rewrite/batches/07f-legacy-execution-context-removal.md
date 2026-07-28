# Batch 07f — Legacy Execution-Context Removal

## Objective

Port every remaining deferred node and modeling helper to `NodeContext`, `InputCollection`, `OutputPublisher`, and `NodeResult`, then delete the legacy execution context and its dual-dispatch paths.

## Scope

- Inventory every `ExecutionContext`, `NodeOutput`, `context.store`, and legacy artifact-reader use.
- Port each remaining deferred node and shared modeling helper to the established node contract.
- Remove runtime type/attribute dispatch that accepts both context types.
- Delete `cardre/execution/context.py` and obsolete execution forwarders when no caller remains.

## Prohibited

- No `hasattr(context, ...)` or type-dispatch bridge between old and new contexts.
- No retained `NodeOutput` compatibility type or `context.store` access.
- No unrelated persistence, frontend, or enforcement rewrite.

## Acceptance

- A production search returns no `ExecutionContext`, `NodeOutput`, or `context.store` references.
- Node-contract, execution behavior, and relevant numerical parity tests pass.
- Each migrated node has one `NodeContext` execution path.
