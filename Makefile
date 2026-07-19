.DEFAULT_GOAL := help
SHELL := /bin/bash

# Prefer an existing venv python, else system python3.
PY ?= $(shell [ -x server/.venv/bin/python ] && echo server/.venv/bin/python || echo python3)

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: build
build: ## Build server + daemon images
	docker compose build

.PHONY: deploy
deploy: ## Deploy the stack (no pre-config needed — configure via the wizard)
	docker stack deploy -c docker-compose.yml liteboard

.PHONY: token
token: ## Print the first-login setup token from the server logs
	@docker service logs liteboard_server 2>&1 | grep "Setup token" | tail -1 \
	  || echo "No setup token found — the server may already be configured."

.PHONY: remove
remove: ## Remove the stack
	docker stack rm liteboard

# --- Advanced / offline (optional) ------------------------------------------
.PHONY: keygen
keygen: ## (Advanced) Pre-generate a signing keypair offline instead of via the wizard
	@$(PY) scripts/keygen.py

.PHONY: web
web: ## Build the Vue SPA locally
	cd web && npm install && npm run build

.PHONY: test
test: ## Run server unit tests
	cd server && .venv/bin/python -m pytest -q

.PHONY: dev-server
dev-server: ## Run the API server locally (auth disabled)
	cd server && LITEBOARD_AUTH_DISABLED=true \
	  LITEBOARD_DATA_DIR=$(PWD)/.devdata \
	  LITEBOARD_STATIC_DIR=$(PWD)/web/dist \
	  LITEBOARD_SIGNING_KEY_FILE=$(PWD)/secrets/signing_key \
	  .venv/bin/uvicorn liteboard.main:app --reload --port 8000
