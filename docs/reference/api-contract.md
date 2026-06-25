# API Contract

## Overview

The API contract is defined by the FastAPI sidecar (`sidecar/`) and generated as an OpenAPI specification. The frontend consumes the generated types.

## Generated Types

OpenAPI types are generated from the sidecar routes and models:

```bash
python3 scripts/generate-openapi-types.py
```

This produces:
- `frontend/src/api/openapi.json` — OpenAPI spec
- `frontend/src/api/schema.d.ts` — TypeScript type definitions

## Boundary Pattern

The service layer (`cardre/services/`) uses plain dataclass DTOs defined in `cardre/services/plan_dto.py`. These mirror the Pydantic models in `sidecar/models.py` but keep the service layer free of FastAPI dependencies.

The route layer converts between them via `dataclasses.asdict()`. This is an intentional boundary contract: the dataclasses are the canonical service-layer return types, and the Pydantic models are the API-layer serialisation types.

## Key Endpoints

| Prefix | Module | Description |
|--------|--------|-------------|
| `/health` | `sidecar/routes/health.py` | Health check |
| `/projects` | `sidecar/routes/projects.py` | Project CRUD |
| `/datasets` | `sidecar/routes/datasets.py` | Dataset import |
| `/plans` | `sidecar/routes/plans.py` | Plan CRUD, step status, staleness, manual binning |
| `/runs` | `sidecar/routes/runs.py` | Run execution, step evidence |
| `/artifacts` | `sidecar/routes/artifacts.py` | Artifact retrieval, preview, summary |
| `/branches` | `sidecar/routes/branches.py` | Branch CRUD (governance-gated) |
| `/node-types` | `sidecar/routes/node_types.py` | Node type listing and schema |
| `/exports` | `sidecar/routes/exports.py` | Audit pack export |
| `/reports` | `sidecar/routes/reports.py` | Report generation and metadata |
| `/branch-comparisons` | `sidecar/routes/comparisons.py` | Branch comparison (governance-gated) |
| `/champion` | `sidecar/routes/champion.py` | Champion assignment (governance-gated) |
| `/migrations` | `sidecar/routes/binning.py` | Schema migrations |
