COMPOSE := docker compose
WRITER_MODEL ?= $(shell grep -s '^REELSMITH_WRITER_MODEL=' .env | cut -d= -f2)
ONLY ?=

.PHONY: setup build models llm-model up migrate down logs pin test lint demo

setup:                       ## first run: env file and data folders
	cp -n .env.example .env || true
	mkdir -p models hf voices outbox

build:
	$(COMPOSE) build

models:                      ## ONLY=video,music to fetch some stages
	$(COMPOSE) run --rm --no-deps --entrypoint python \
		-v $(CURDIR)/models:/models worker \
		tools/fetch_models.py --models /models --hf-home /hf $(if $(ONLY),--only $(ONLY))

llm-model:
	$(COMPOSE) up -d llm
	$(COMPOSE) exec llm ollama pull $(WRITER_MODEL)

up:
	$(COMPOSE) up -d

migrate:
	$(COMPOSE) run --rm worker migrate

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f worker

pin:                         ## print image digests to freeze in .env
	@for img in ollama/ollama postgres:17-alpine; do \
		docker image inspect --format '{{index .RepoDigests 0}}' $$img; done

test:
	pytest -q

lint:
	ruff check . && ruff format --check . && mypy src

demo:                        ## the whole conveyor on synthetic providers, no models needed
	reelsmith demo --ideas 3 --out demo
