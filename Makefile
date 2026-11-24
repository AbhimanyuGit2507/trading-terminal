.PHONY: help up down migrate backend-test frontend-test typegen parity-check lint

help:
	@echo "Targets: up, down, migrate, backend-test, frontend-test, typegen, parity-check, lint"

up:
	docker compose up -d postgres

down:
	docker compose down

migrate:
	cd backend && uv run alembic upgrade head

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

