# API Contract

## Overview

The API contract is defined by the FastAPI application in `cardre/api/` and generated as an OpenAPI specification. The frontend consumes the generated types.

## Generated Types

OpenAPI types are generated from the application routes:

```bash
python3 scripts/generate-openapi-types.py
```

This produces:
- `frontend/src/api/openapi.json` — OpenAPI spec
- `frontend/src/api/schema.d.ts` — TypeScript type definitions

## Boundary Pattern

The application layer uses plain dataclass DTOs defined in `cardre/application/`. These mirror the Pydantic models in `cardre/api/schemas.py` but keep the application layer free of FastAPI dependencies.

The route layer converts between them via `cardre/api/mappers.py`. This is an intentional boundary contract: the dataclasses are the canonical application-layer return types, and the Pydantic models are the API-layer serialisation types.

## Key Endpoints

The route modules live under `cardre/api/routes/`. Most routes are project-scoped
(prefix `/projects/{project_id}`); governance is nested under
`/projects/{project_id}/governance`.

| Prefix | Module | Description |
|--------|--------|-------------|
| `/health` | `cardre/api/routes/health.py` | Health check |
| `/projects` | `cardre/api/routes/projects.py` | Project CRUD |
| `/projects/{project_id}/plans` | `cardre/api/routes/plans.py` | Plan CRUD, plan versions, steps |
| `/projects/{project_id}/runs` | `cardre/api/routes/runs.py` | Run submission, run steps, run evidence |
| `/projects/{project_id}/artifacts` | `cardre/api/routes/artifacts.py` | Artifact retrieval |
| `/projects/{project_id}/steps/{step_id}/evidence` | `cardre/api/routes/evidence.py` | Step staleness/evidence explanation |
| `/projects/{project_id}/node-types` | `cardre/api/routes/node_types.py` | Node type listing and schema |
| `/projects/{project_id}/exports` | `cardre/api/routes/exports.py` | Audit pack export listing |
| `/projects/{project_id}/reports` | `cardre/api/routes/reports.py` | Report generation and metadata |
| `/projects/{project_id}/governance/branches` | `cardre/api/routes/governance.py` | Branch CRUD (governance-gated) |
| `/projects/{project_id}/governance/comparisons` | `cardre/api/routes/governance.py` | Branch comparisons (governance-gated) |
| `/projects/{project_id}/governance/champion` | `cardre/api/routes/governance.py` | Champion assignment (governance-gated) |
| `/projects/{project_id}/governance/manual-binning-reviews` | `cardre/api/routes/governance.py` | Manual binning reviews (governance-gated) |

Governance routes require `CARDRE_GOVERNANCE=1`; they return a 403 envelope
otherwise.
