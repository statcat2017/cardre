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

The route modules live under `cardre/api/routes/`:

| Prefix | Module | Description |
|--------|--------|-------------|
| `/health` | `cardre/api/routes/health.py` | Health check |
| `/projects` | `cardre/api/routes/projects.py` | Project CRUD |
| `/plans` | `cardre/api/routes/plans.py` | Plan CRUD, step status, staleness, manual binning |
| `/runs` | `cardre/api/routes/runs.py` | Run execution, step evidence |
| `/artifacts` | `cardre/api/routes/artifacts.py` | Artifact retrieval, preview, summary |
| `/branches` | `cardre/api/routes/governance.py` | Branch CRUD (governance-gated) |
| `/node-types` | `cardre/api/routes/node_types.py` | Node type listing and schema |
| `/exports` | `cardre/api/routes/exports.py` | Audit pack export |
| `/reports` | `cardre/api/routes/reports.py` | Report generation and metadata |
| `/evidence` | `cardre/api/routes/evidence.py` | Evidence retrieval |
