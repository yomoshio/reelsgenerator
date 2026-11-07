#!/usr/bin/env bash
# Управление GPU-сервером с этого компьютера. Адрес сервера в scripts/remote.env.
#
#   scripts/remote.sh add "идея" [--style rules-serial]   поставить идею
#   scripts/remote.sh ideas [studio/series/flood.txt]   поставить новые строки файла идей
#   scripts/remote.sh series studio/stories/x.txt [--episodes 10]   сезон из синопсиса в studio/series/
#   scripts/remote.sh adapt studio/input/x.fb2 [--episodes 5] [--style twist]   рассказ или книга в серию
#   scripts/remote.sh jobs [--status assembled]          все задачи с id и статусом
#   scripts/remote.sh status | report | styles           счётчики, деньги, стили
#   scripts/remote.sh review ID                          скачать собранный ролик в review/ID.mp4
#   scripts/remote.sh approve ID | reject ID             одобрить или отправить на переделку
#   scripts/remote.sh retry ID [--status framed]         вернуть упавшую или зависшую задачу в работу
#   scripts/remote.sh logs                               смотреть, что делает воркер
#   scripts/remote.sh pause | resume                     пауза конвейера, чтобы работать в ComfyUI
#   scripts/remote.sh comfy                              туннель к ComfyUI: http://localhost:8188
#   scripts/remote.sh gpu                                кто сейчас занимает карту
#   scripts/remote.sh smoke                              по одному вызову каждой модели: проверка машины
#   scripts/remote.sh push | deploy                      залить код; deploy ещё пересобирает и перезапускает
#   scripts/remote.sh restart                            перезапустить воркер, например после правки стиля
#   scripts/remote.sh pull                               забрать готовые ролики и голоса
#   scripts/remote.sh restore                            отправить голоса и .env на новый сервер
#   scripts/remote.sh backup                             снять копию базы задач в backups/
#   scripts/remote.sh check                              какие файлы кода отличаются здесь и там
#   scripts/remote.sh up | down | shell [команда]
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f scripts/remote.env ]] || { echo "скопируйте scripts/remote.env.example в scripts/remote.env и впишите адрес сервера" >&2; exit 1; }
# shellcheck source=/dev/null
source scripts/remote.env
: "${REMOTE_HOST:?REMOTE_HOST is not set in scripts/remote.env}"
REMOTE_PORT=${REMOTE_PORT:-22}
REMOTE_KEY=${REMOTE_KEY:-$HOME/.ssh/id_ed25519}
REMOTE_DIR=${REMOTE_DIR:-/root/projects/reelsgenerator}

SSH=(ssh -i "$REMOTE_KEY" -p "$REMOTE_PORT" -o ServerAliveInterval=30)
RSYNC=(rsync -a -e "ssh -i $REMOTE_KEY -p $REMOTE_PORT")
# Код идёт на сервер, данные с сервера сюда. Веса не копируются никогда. Заливка удаляет
# на сервере файлы кода, удалённые здесь; исключённые пути она не трогает.
CODE_ONLY=(--exclude .venv --exclude __pycache__ --exclude .mypy_cache --exclude .ruff_cache
           --exclude .pytest_cache --exclude demo --exclude preview --exclude review --exclude .git
           --exclude logs --exclude models --exclude hf --exclude outbox --exclude voices --exclude studio
           --exclude .env --exclude scripts/remote.env --exclude backups)

# -n: without it ssh swallows the rest of stdin, which breaks `while read ...; do remote.sh add`.
on_server() { "${SSH[@]}" -n "$REMOTE_HOST" "cd $REMOTE_DIR && $*"; }
worker() { on_server "docker compose run --rm --no-deps -T worker $(printf '%q ' "$@")"; }

command=${1:-help}
shift || true
case $command in
    add | jobs | status | report | compare | styles | approve | reject | retry | rate | fork | measure | smoke)
        worker "$command" "$@" ;;
    review)
        id=${1:?usage: review JOB_ID}
        mkdir -p review
        on_server "docker compose exec -T worker cat /data/media/$id/final.mp4" > "review/$id.mp4"
        echo "review/$id.mp4" ;;
    ideas)
        file=${1:-studio/ideas.txt}
        "${SSH[@]}" "$REMOTE_HOST" "mkdir -p $REMOTE_DIR/$(dirname "$file")"
        "${RSYNC[@]}" "$file" "$REMOTE_HOST:$REMOTE_DIR/$file"
        on_server "chmod -R a+rwX studio && docker compose run --rm --no-deps -T worker queue /data/$file"
        "${RSYNC[@]}" "$REMOTE_HOST:$REMOTE_DIR/$file" "$file" ;;
    series)
        file=${1:?usage: series studio/stories/NAME.txt [--episodes N]}
        shift
        "${SSH[@]}" -n "$REMOTE_HOST" "mkdir -p $REMOTE_DIR/$(dirname "$file") $REMOTE_DIR/studio/series"
        "${RSYNC[@]}" "$file" "$REMOTE_HOST:$REMOTE_DIR/$file"
        on_server "chmod -R a+rwX studio && docker compose run --rm --no-deps -T worker series /data/$file $(printf '%q ' "$@")"
        mkdir -p studio/series
        "${RSYNC[@]}" "$REMOTE_HOST:$REMOTE_DIR/studio/series/" studio/series/ ;;
    adapt)
        file=${1:?usage: adapt studio/input/NAME.fb2 [--episodes N] [--style twist]}
        shift
        "${SSH[@]}" -n "$REMOTE_HOST" "mkdir -p $REMOTE_DIR/$(dirname "$file") $REMOTE_DIR/studio/series"
        "${RSYNC[@]}" "$file" "$REMOTE_HOST:$REMOTE_DIR/$file"
        on_server "chmod -R a+rwX studio && docker compose run --rm --no-deps -T worker adapt /data/$file $(printf '%q ' "$@")"
        mkdir -p studio/series
        "${RSYNC[@]}" "$REMOTE_HOST:$REMOTE_DIR/studio/series/" studio/series/ ;;
    logs) on_server "docker compose logs -f --tail 50 worker" ;;
    pause) on_server "docker compose stop worker" ;;
    resume) on_server "docker compose start worker" ;;
    comfy)
        echo "откройте http://localhost:8188 и не закрывайте это окно; Ctrl+C закрывает туннель"
        "${SSH[@]}" -N -L 8188:localhost:8188 "$REMOTE_HOST" ;;
    gpu) on_server 'nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv; docker compose exec -T llm ollama ps' ;;
    push)
        "${SSH[@]}" "$REMOTE_HOST" "mkdir -p $REMOTE_DIR"
        "${RSYNC[@]}" --delete "${CODE_ONLY[@]}" ./ "$REMOTE_HOST:$REMOTE_DIR/" ;;
    deploy)
        "${SSH[@]}" "$REMOTE_HOST" "mkdir -p $REMOTE_DIR"
        "${RSYNC[@]}" --delete "${CODE_ONLY[@]}" ./ "$REMOTE_HOST:$REMOTE_DIR/"
        on_server "docker compose build worker tts && docker compose up -d" ;;
    pull)
        "${RSYNC[@]}" "$REMOTE_HOST:$REMOTE_DIR/outbox/" outbox/
        "${RSYNC[@]}" "$REMOTE_HOST:$REMOTE_DIR/voices/" voices/ ;;
    restore)
        "${SSH[@]}" "$REMOTE_HOST" "mkdir -p $REMOTE_DIR/voices"
        "${RSYNC[@]}" voices/ "$REMOTE_HOST:$REMOTE_DIR/voices/"
        "${RSYNC[@]}" .env "$REMOTE_HOST:$REMOTE_DIR/.env"
        on_server "chmod a+rwx voices" ;;
    backup)
        mkdir -p backups
        file="backups/jobs-$(date +%Y%m%d-%H%M).sql.gz"
        on_server "docker compose exec -T db pg_dump -U reelsmith reelsmith" | gzip > "$file"
        echo "$file" ;;
    restart) on_server "docker compose restart worker" ;;
    check)
        "${RSYNC[@]}" -rcn --delete --itemize-changes "${CODE_ONLY[@]}" ./ "$REMOTE_HOST:$REMOTE_DIR/" \
            | grep -v '^\.d' || echo "код одинаковый здесь и на сервере" ;;
    up) on_server "docker compose up -d" ;;
    down) on_server "docker compose stop" ;;
    shell) "${SSH[@]}" "$REMOTE_HOST" "$@" ;;
    *) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" ;;
esac
