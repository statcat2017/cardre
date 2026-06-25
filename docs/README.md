# Cardre Documentation

## Start Here

- [README](../README.md) — project overview, quick start, development setup
- [Launch Mode & Feature Flags](launch-mode.md) — `CARDRE_LAUNCH_MODE` and `CARDRE_GOVERNANCE`
- [Domain Glossary](architecture/domain-model.md) — plan vs pathway, node type vs step, build vs validate stream

## Current Architecture

- [Domain Model](architecture/domain-model.md) — core concepts, glossary, terminology
- [Storage & Migrations](architecture/storage-and-migrations.md) — ProjectStore, repository classes, schema
- [Execution & Staleness](architecture/execution-and-staleness.md) — run lifecycle, executor, staleness detection
- [Node Registry](architecture/node-registry.md) — launch/deferred tiers, registration, instantiation
- [Artifact & Evidence Access](architecture/artifact-evidence-access.md) — read paths, forbidden patterns, evidence kinds
- [Reporting](architecture/reporting.md) — report bundle schema, collector, readiness, renderer, generation service

## Reference

- [Feature Status](reference/feature-status.md) — launch/governance/deferred matrix
- [Node Catalogue](reference/node-catalogue.md) — all registered node types, tiers, contracts
- [Report Bundle v1](reference/report-bundle-v1.md) — Pydantic schema, fields, canonical step IDs
- [Evidence Kinds](reference/evidence-kinds.md) — evidence types, contracts, canonical IDs
- [API Contract](reference/api-contract.md) — generated OpenAPI, boundary pattern
- [Audit Pack Structure](reference/audit-pack-structure.md) — export format, contents

## Architecture Decision Records

ADRs are immutable decision records in [docs/adr/](adr/). They are historical records, not current implementation instructions.

## Historical Plans

Historical implementation plans, sprint prompts, and plan reviews remain under `docs/plans/`, `docs/evidence-hardening/`, and `docs/plan-reviews/`. These are historical design inputs, not current implementation instructions.
