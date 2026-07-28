# Batch 07f — Legacy Execution-Context Removal

## Objective

Port every remaining deferred node and modeling helper to `NodeContext`, `InputCollection`, `OutputPublisher`, and `NodeResult`, then delete the legacy execution context and its dual-dispatch paths.

## Scope

- Inventory every `ExecutionContext`, `NodeOutput`, `context.store`, and legacy artifact-reader use.
- Port each remaining deferred node and shared modeling helper to the established node contract.
- Remove runtime type/attribute dispatch that accepts both context types.
- Delete `cardre/execution/context.py` and obsolete execution forwarders when no caller remains.
- Replace each deferred node's legacy `cardre.store`, `cardre.artifacts`, and legacy evidence-reader use with the existing port and node-contract interfaces; do not delete those legacy packages in this batch.

## Prohibited

- No `hasattr(context, ...)` or type-dispatch bridge between old and new contexts.
- No retained `NodeOutput` compatibility type or `context.store` access.
- No infrastructure-package deletion, frontend rewrite, or enforcement rewrite; 07e owns deletion after this caller migration.

## Acceptance

- A production search returns no `ExecutionContext`, `NodeOutput`, or `context.store` references.
- Deferred nodes and shared helpers have no imports of `cardre.store`, `cardre.artifacts`, or legacy evidence readers.
- Node-contract, execution behavior, and relevant numerical parity tests pass.
- Each migrated node has one `NodeContext` execution path.
