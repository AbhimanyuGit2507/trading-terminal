.PHONY: help up down migrate dev-backend dev-frontend seed-history ingest-dhan backend-test frontend-test typegen parity-check lint

help:
	@echo "Targets: up, down, migrate, dev-backend, dev-frontend, seed-history, ingest-dhan, backend-test, frontend-test, typegen, parity-check, lint"

up:
	docker compose up -d postgres

down:
	docker compose down

migrate:
	cd backend && uv run alembic upgrade head

dev-backend:
	cd backend && MOCK_LIVE_JITTER=true uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && pnpm dev

seed-history:
	cd backend && uv run python scripts/seed_synthetic_history.py

ingest-dhan:
	cd backend && uv run python scripts/ingest_dhan_rolling.py --symbol $(SYMBOL) --from $(FROM) --to $(TO)

backend-test:
	cd backend && uv run pytest -v

frontend-test:
	cd frontend && pnpm test

typegen:
	cd backend && uv run python scripts/export_openapi.py
	cd frontend && pnpm run typegen

parity-check: backend-test frontend-test

lint:
	cd backend && uv run ruff check .
	cd frontend && pnpm run typecheck

