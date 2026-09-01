# Tesla System — Docker convenience targets
.PHONY: help build up up-gpu down logs ps shell health env-check

COMPOSE ?= docker compose
COMPOSE_GPU := $(COMPOSE) -f docker-compose.yml -f docker-compose.gpu.yml

help:
	@echo "Targets:"
	@echo "  make env-check   Copy .env.example -> .env if missing"
	@echo "  make build       Build app image"
	@echo "  make up          Start stack (CPU container; RAG needs GPU override)"
	@echo "  make up-gpu      Start stack with NVIDIA GPU for RAG"
	@echo "  make down        Stop and remove containers"
	@echo "  make logs        Follow app logs"
	@echo "  make ps          Show service status"
	@echo "  make shell       Shell into app container"
	@echo "  make health      Hit /api/model-status"

env-check:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — edit secrets before production.")

build: env-check
	$(COMPOSE) build

up: env-check
	$(COMPOSE) up -d --build

up-gpu: env-check
	$(COMPOSE_GPU) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f app

ps:
	$(COMPOSE) ps

shell:
	$(COMPOSE) exec app bash

health:
	curl -fsS "http://127.0.0.1:$${APP_PUBLISH_PORT:-6006}/api/model-status" | python -m json.tool
