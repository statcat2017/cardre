# Batch 07e — ProjectStore Removal and Test Migration

## Objective

Remove the legacy persistence and ambient-configuration architecture only after every production caller, including deferred nodes and shared helpers, uses application ports, SQLite adapters, and bootstrap settings.

## Scope

- Replace each remaining `ProjectStore` caller with a `UnitOfWorkFactory`, query port, artifact-store port, project registry, or bootstrap setting as appropriate.
- Remove `cardre/store`, `cardre/config.py`, `cardre/artifacts.py`, `cardre/capabilities.py`, and only legacy service glue made unused by that removal.
- Rename or remove legacy types rather than retaining names that obscure the new adapter boundary.
- Migrate store-coupled tests to domain, application, port-contract, or adapter tests according to the behavior they prove.

## Prohibited

- No `ProjectStore` facade over the new UoW, no deprecated import aliases, and no environment/config fallback.
- No execution-context work or dual path; 07f must already have removed every node and helper caller.
- No test `xfail` used to defer a remaining production caller.

## Acceptance

- A production search returns no `ProjectStore`, `cardre.store`, `cardre.config`, `cardre.artifacts`, or `cardre.capabilities` references.
- SQLite adapter, project registry, artifact-store, and migrated application tests pass.
- No architecture test permits legacy persistence outside a narrowly justified adapter boundary, because the legacy surface no longer exists.

## Depends on

07f. This batch must begin with no production import of `cardre.store`, `cardre.artifacts`, or the legacy evidence reader from deferred nodes or shared helpers.
