# Trading Terminal — Indian F&O Strategy Builder & Option Simulator

A decoupled, zero-lag Indian F&O Strategy Builder and Option Simulator (NIFTY, BANKNIFTY, FINNIFTY, SENSEX) designed for historical replay and future live execution via DhanHQ v2.5.

## Monorepo Layout
- `backend/`: Async Python FastAPI + NumPy/SciPy Black-76 quant engine + SQLAlchemy 2 / Alembic + DuckDB/Parquet readiness
- `frontend/`: Next.js (App Router, TypeScript) + Zustand + Apache ECharts + `Float64Array` client quant engine
- `shared/`: Generated OpenAPI schema (`openapi.json`), TypeScript API types (`types/api.ts`), and Python-generated golden parity vectors (`golden/quant_vectors.json`)
- `docker-compose.yml`: Local PostgreSQL 16 service

## Quick Start (Milestone 1)
```bash
# Start local Postgres
make up

# Run Alembic migrations
make migrate

# Run Python quant & DB tests (also generates shared/golden/quant_vectors.json)
make backend-test

# Export OpenAPI schema & generate TypeScript types
make typegen

# Run Frontend TS quant parity tests
make frontend-test
```

