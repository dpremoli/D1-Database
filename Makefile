# D1-Database — common commands.
# `make` is optional (Linux/WSL/CI). On Windows you can run the underlying
# commands directly; each recipe is a one-liner you can copy.
.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help setup test smoke compose-check lint up down logs

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install pre-commit hooks (needs python + pre-commit)
	pre-commit install
	@echo "Hooks installed. Copy .env.example to .env and edit secrets."

test: smoke ## Run the test suite (currently the Phase 0 smoke test)

smoke: ## Validate the repository foundation
	bash tests/phase0_smoke.sh

compose-check: ## Validate docker-compose.yml is well-formed
	docker compose config -q && echo "docker-compose.yml OK"

lint: ## Run all pre-commit hooks across the repo
	pre-commit run --all-files

up: ## Bring up the Docker stack (Phase 2+)
	docker compose up -d

down: ## Stop the Docker stack
	docker compose down

logs: ## Tail stack logs
	docker compose logs -f
