.DEFAULT_GOAL := help
SHELL := /bin/bash

# Prefer an existing venv python, else system python3.
PY ?= $(shell [ -x server/.venv/bin/python ] && echo server/.venv/bin/python || echo python3)

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: keygen
keygen: ## Generate the stable Ed25519 signing keypair (writes secrets/signing_key, prints pubkey)
	@$(PY) scripts/keygen.py

.PHONY: secret
secret: ## Create swarm secrets from secrets/signing_key (+ empty registry creds)
	docker secret create liteboard_signing_key secrets/signing_key
	echo '{}' | docker secret create liteboard_registry_creds -

.PHONY: build
build: ## Build server + daemon images
	docker compose build

.PHONY: deploy
deploy: ## Deploy the stack (docker stack deploy)
	docker stack deploy -c docker-compose.yml liteboard

.PHONY: remove
remove: ## Remove the stack
	docker stack rm liteboard

.PHONY: web
web: ## Build the Vue SPA locally
	cd web && npm install && npm run build

.PHONY: test
test: ## Run server unit tests
	cd server && .venv/bin/python -m pytest -q

.PHONY: dev-server
dev-server: ## Run the API server locally (auth disabled)
	cd server && LITEBOARD_AUTH_DISABLED=true \
	  LITEBOARD_STATIC_DIR=$(PWD)/web/dist \
	  LITEBOARD_SIGNING_KEY_FILE=$(PWD)/secrets/signing_key \
	  .venv/bin/uvicorn liteboard.main:app --reload --port 8000
