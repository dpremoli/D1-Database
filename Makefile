# D1-Database — common commands.
# `make` is optional (Linux/WSL/CI). On Windows you can run the underlying
# commands directly; each recipe is a one-liner you can copy.
.DEFAULT_GOAL := help
SHELL         := /bin/bash

# Migration tooling — dbmate via Docker (no local install required).
DBMATE_IMAGE  := ghcr.io/amacneil/dbmate:2
POSTGRES_HOST ?= localhost
POSTGRES_PORT ?= 5432
POSTGRES_USER ?= d1
POSTGRES_DB   ?= d1_database
# Export DATABASE_URL from .env or environment before running migrate targets.
DATABASE_URL  ?= postgres://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/$(POSTGRES_DB)?sslmode=disable

.PHONY: help setup test smoke schema-test compose-check lint up down logs \
        migrate migrate-down migrate-status seed reset-db \
        bootstrap-minio backup restore prune-backups \
        worker-build worker-test worker-logs phase4-test \
        analysis-build analysis-test

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install pre-commit hooks (needs python + pre-commit)
	pre-commit install
	@echo "Hooks installed. Copy .env.example to .env and edit secrets."

test: smoke ## Run the full local test suite (foundation + schema if DB is up)

smoke: ## Validate the repository foundation (Phase 0 checks)
	bash tests/phase0_smoke.sh

schema-test: ## Run Phase 1 schema tests (requires DATABASE_URL or running stack)
	DATABASE_URL="$(DATABASE_URL)" bash tests/phase1_schema.sh

compose-check: ## Validate docker-compose.yml is well-formed
	docker compose config -q && echo "docker-compose.yml OK"

lint: ## Run all pre-commit hooks across the repo
	pre-commit run --all-files

up: ## Bring up the Docker stack
	docker compose up -d

down: ## Stop the Docker stack
	docker compose down

logs: ## Tail stack logs
	docker compose logs -f

migrate: ## Apply all pending migrations (requires DATABASE_URL)
	docker run --rm \
		-e DATABASE_URL="$(DATABASE_URL)" \
		-v "$(CURDIR)/db:/db" \
		$(DBMATE_IMAGE) --no-dump-schema up

migrate-down: ## Roll back the latest migration (requires DATABASE_URL)
	docker run --rm \
		-e DATABASE_URL="$(DATABASE_URL)" \
		-v "$(CURDIR)/db:/db" \
		$(DBMATE_IMAGE) --no-dump-schema down

migrate-status: ## Show migration status (requires DATABASE_URL)
	docker run --rm \
		-e DATABASE_URL="$(DATABASE_URL)" \
		-v "$(CURDIR)/db:/db" \
		$(DBMATE_IMAGE) status

seed: ## Load reference seed data (requires DATABASE_URL and psql in PATH)
	psql "$(DATABASE_URL)" -f db/seeds/001_reference_data.sql

bootstrap-minio: ## Create MinIO buckets after first `make up` (idempotent)
	docker run --rm \
		--network d1-database_d1net \
		-e MC_HOST_local="http://$(MINIO_ROOT_USER):$(MINIO_ROOT_PASSWORD)@minio:9000" \
		minio/mc:latest \
		sh -c "mc mb --ignore-existing local/d1-files \
			&& mc mb --ignore-existing local/d1-backups \
			&& echo 'Buckets ready: d1-files, d1-backups'"

backup: ## Dump PostgreSQL and upload to MinIO (stack must be running)
	bash infra/backup/backup.sh

restore: ## Restore from MinIO backup — set BACKUP_FILE=d1_<timestamp>.sql.gz
	bash infra/backup/restore.sh

prune-backups: ## Remove local backup files older than 30 days
	find ./backups -name 'd1_*.sql.gz' -mtime +30 -print -delete

worker-build: ## Build the heavy-data worker Docker image
	docker build -t d1-heavy-data-worker plugins/heavy-data-worker/

worker-test: worker-build ## Run heavy-data worker unit tests inside Docker
	docker run --rm d1-heavy-data-worker \
		python -m pytest tests/ -v --tb=short

worker-logs: ## Tail heavy-data worker container logs
	docker compose logs -f heavy-data-worker

phase4-test: ## Phase 4 integration test (requires running stack + MACHINE_TOKEN)
	bash tests/phase4_heavy_data.sh

analysis-build: ## Build the FFT analysis worker Docker image
	docker build -t d1-analysis-worker plugins/analysis-worker/

analysis-test: analysis-build ## Run FFT analysis worker unit tests inside Docker
	docker run --rm d1-analysis-worker \
		python -m pytest tests/ -v --tb=short

reset-db: ## Drop all tables and re-apply migrations + seed (DESTRUCTIVE — dev only)
	@echo "WARNING: this destroys all data. Ctrl-C to abort."
	@sleep 3
	docker run --rm \
		-e DATABASE_URL="$(DATABASE_URL)" \
		-v "$(CURDIR)/db:/db" \
		$(DBMATE_IMAGE) --no-dump-schema drop || true
	docker run --rm \
		-e DATABASE_URL="$(DATABASE_URL)" \
		-v "$(CURDIR)/db:/db" \
		$(DBMATE_IMAGE) --no-dump-schema up
	$(MAKE) seed
