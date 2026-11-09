COMPOSE := docker compose
RUN := $(COMPOSE) run --rm --no-deps worker
WRITER_MODEL ?= $(shell grep -s '^REELSMITH_WRITER_MODEL=' .env | cut -d= -f2)

.PHONY: help setup build models llm-model voice up down migrate graphs \
	add ideas series adapt remix outline jobs status report styles review approve reject retry logs pause resume smoke \
	test lint demo preview pin

help:                        ## этот список
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 14

# Первый запуск на новой машине, по порядку.

setup:                       ## .env из примера и папки для данных
	cp -n .env.example .env || true
	mkdir -p models hf voices outbox studio/output studio/input studio/inbox studio/series \
		studio/user/default/workflows/reelsmith
	touch studio/ideas.txt
	chmod a+rwx models hf voices outbox
	chmod -R a+rwX studio

build:                       ## собрать образы
	$(COMPOSE) build

models:                      ## скачать веса; ONLY=video,music часть, OPTIONAL=1 с необязательными
	$(COMPOSE) run --rm --no-deps --entrypoint python -v $(CURDIR):/project -w /project worker \
		scripts/fetch_models.py --models models --hf-home hf \
		$(if $(ONLY),--only $(ONLY)) $(if $(OPTIONAL),--with-optional)

llm-model:                   ## скачать модель Ollama из .env
	$(COMPOSE) up -d llm
	$(COMPOSE) exec llm ollama pull $(WRITER_MODEL)

voice:                       ## DESC="описание голоса" создать голос диктора
	$(COMPOSE) run --rm --no-deps --entrypoint python tts design_voice.py narrator "$(DESC)"

up:                          ## запустить всё
	$(COMPOSE) up -d

down:                        ## остановить всё
	$(COMPOSE) down

migrate:                     ## создать таблицу задач
	$(COMPOSE) run --rm worker migrate

smoke:                       ## по одному вызову каждой модели с временем: проверка новой машины
	$(RUN) smoke

graphs:                      ## пересобрать workflows/*.json из scripts/make_graphs.py
	python3 scripts/make_graphs.py

# Каждый день.

add:                         ## IDEA="..." [STYLE=noir] поставить одну идею
	$(RUN) add "$(IDEA)" $(if $(STYLE),--style $(STYLE))

ideas:                       ## поставить новые строки из studio/ideas.txt; FILE=studio/series/flood.txt другой файл
	$(RUN) queue /data/$(or $(FILE),studio/ideas.txt)

series:                      ## STORY=studio/stories/x.txt [EPISODES=10] сезон из синопсиса в studio/series/x.*
	$(RUN) series /data/$(STORY) $(if $(EPISODES),--episodes $(EPISODES))

adapt:                       ## BOOK=studio/input/x.fb2 [EPISODES=5] [STYLE=twist] рассказ или книга в серию studio/series/x.*
	$(RUN) adapt /data/$(BOOK) $(if $(EPISODES),--episodes $(EPISODES)) $(if $(STYLE),--style $(STYLE))

remix:                       ## [COUNT=12] [THEME=space] [SEED=7] короткие идеи из библиотеки структур в studio/ideas/
	$(RUN) remix $(if $(COUNT),--count $(COUNT)) $(if $(THEME),--theme $(THEME)) $(if $(SEED),--seed $(SEED))

outline:                     ## FILE=studio/ideas/x.txt планы модели для каждой идеи, без рендера, в x.outlines.md
	$(RUN) outline /data/$(FILE)

jobs:                        ## все задачи с id; STATUS=assembled только собранные
	$(RUN) jobs $(if $(STATUS),--status $(STATUS))

status:                      ## сколько задач на каждой стадии
	$(RUN) status

report:                      ## деньги, брак, GPU-часы, удержание
	$(RUN) report

styles:                      ## стили и для чего каждый
	$(RUN) styles

preview:                     ## STYLE=rules-serial кадр с субтитрами и плашками, в preview/
	mkdir -p preview && chmod a+rwx preview
	$(COMPOSE) run --rm --no-deps -v $(CURDIR)/preview:/out worker preview $(STYLE) --out /out

review:                      ## ID=... скопировать собранный ролик в review/ID.mp4
	mkdir -p review
	$(COMPOSE) cp worker:/data/media/$(ID)/final.mp4 review/$(ID).mp4
	@echo review/$(ID).mp4

approve:                     ## ID=... одобрить, ролик уйдёт в outbox/
	$(RUN) approve $(ID)

reject:                      ## ID=... [REASON="..."] отклонить, клипы переделаются
	$(RUN) reject $(ID) $(if $(REASON),--reason "$(REASON)")

retry:                       ## ID=... [STATUS=framed] вернуть упавшую или зависшую задачу в работу
	$(RUN) retry $(ID) $(if $(STATUS),--status $(STATUS))

logs:                        ## смотреть, что делает воркер
	$(COMPOSE) logs -f --tail 50 worker

pause:                       ## пауза конвейера, карта свободна для ComfyUI
	$(COMPOSE) stop worker

resume:                      ## снять конвейер с паузы
	$(COMPOSE) start worker

# Разработка: любая машина с Python 3.12 и ffmpeg.

test:
	pytest -q

lint:
	ruff check . && ruff format --check . && mypy src

demo:                        ## весь конвейер на заглушках, без GPU
	REELSMITH_STYLES=styles reelsmith demo --ideas 3 --out demo


pin:                         ## хэши образов, чтобы закрепить в .env
	@for img in ollama/ollama postgres:17-alpine; do \
		docker image inspect --format '{{index .RepoDigests 0}}' $$img; done
