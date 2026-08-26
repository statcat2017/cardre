# Cardre Documentation

## Start Here

- [README](../README.md) — project overview, quick start, development setup
- [Domain Glossary](architecture/domain-model.md) — plan vs pathway, node type vs step, build vs validate stream

## Current Architecture

- [Domain Model](architecture/domain-model.md) — core concepts, glossary, terminology
- [Storage](architecture/storage-and-migrations.md) — ProjectStore, repository classes, schema
- [Execution & Staleness](architecture/execution-and-staleness.md) — run lifecycle, executor, staleness detection
- [Node Registry](architecture/node-registry.md) — canonical production node registration and instantiation
- [Artifact & Evidence Access](architecture/artifact-evidence-access.md) — read paths, forbidden patterns, evidence kinds
- [Reporting](architecture/reporting.md) — report bundle schema, collector, readiness, renderer, generation service

## Reference

- [Feature Status](reference/feature-status.md) — current scorecard capabilities
- [Node Catalogue](reference/node-catalogue.md) — registered production node types and contracts
- [Report Bundle v1](reference/report-bundle-v1.md) — Pydantic schema, fields, canonical step IDs
- [Evidence Kinds](reference/evidence-kinds.md) — evidence types, contracts, canonical IDs
- [API Contract](reference/api-contract.md) — generated OpenAPI, boundary pattern
- [Audit Pack Structure](reference/audit-pack-structure.md) — export format, contents

## Architecture Decision Records

ADRs are immutable decision records in [docs/adr/](adr/). They explain *why* each structural choice was made. The active product policy is [ADR 0015](adr/0015-no-compatibility-policy.md) (one current persisted shape) and its enforcement, [ADR 0017](adr/0017-one-product-purge-enforcement.md) (the one-product purge). The test suite architecture is recorded in [ADR 0018](adr/0018-test-architecture-layered-suite.md).

## Roadmap

See the [Roadmap](../README.md#roadmap) section in the root README.

## Implementation Plans

- [One Cardre Purge Plan](plans/one-cardre-purge-plan.md) — **completed**
  decision record for removing deferred product surface, governance,
  compatibility handling, alternate methodologies, and duplicate
  representations
