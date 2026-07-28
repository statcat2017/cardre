# Batch 07c — Evidence-Package Migration

## Objective

Give evidence concepts one canonical home: pure models, schemas, and kinds in `cardre/domain/evidence`; I/O readers and parsers in `cardre/adapters/evidence` behind application ports.

## Scope

- Move every remaining `cardre/_evidence` model, schema, kind, and profile to its domain home.
- Move reader/parser behavior to the evidence adapter boundary and update all importers in application, nodes, adapters, and tests.
- Preserve the artifact-reader boundary: domain code has no filesystem or database dependency.
- Delete `cardre/_evidence` in the same PR, including empty package remnants.

## Prohibited

- No `cardre._evidence` re-export package, import alias, or compatibility module.
- No persistence or node-context migration that is owned by 07e or 07f.
- No golden-fixture changes unless an intentional, reviewed behavior change requires them.

## Acceptance

- A production search returns no `cardre._evidence` imports.
- Evidence adapter/parser tests and golden evidence fixture tests pass.
- The canonical contract test's evidence rules are updated for the new ownership without weakening the production read boundary.
