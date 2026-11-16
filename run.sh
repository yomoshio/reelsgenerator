#!/usr/bin/env bash
# Все команды reelsmith. Linux, macOS, WSL; на Windows то же самое делает run.cmd.
#
# На этой машине:
#   ./run.sh up | down                      запустить или остановить все сервисы
#   ./run.sh add "идея" [--style twist]     поставить идею в очередь
#   ./run.sh ideas [studio/ideas.txt]       поставить новые строки файла идей
#   ./run.sh series studio/stories/x.txt [--episodes 10]       сезон из синопсиса
#   ./run.sh adapt studio/input/x.fb2 [--episodes 5] [--style twist]   рассказ или книга в серию
#   ./run.sh remix [--count 12] [--theme space] [--seed 7]     идеи из библиотеки структур
#   ./run.sh outline studio/ideas/x.txt     планы для каждой идеи, без рендера
#   ./run.sh beats studio/ideas/x.txt --series studio/series/proto   сценарии в битах
#   ./run.sh jobs [--status assembled]      задачи с id и статусом
#   ./run.sh status | report | styles       счётчики; деньги и брак; стили
#   ./run.sh preview STYLE                  кадр с субтитрами и плашками в preview/
#   ./run.sh review ID                      собранный ролик в review/ID.mp4
#   ./run.sh approve ID | reject ID [--reason "..."] | retry ID [--status framed]
#   ./run.sh logs | pause | resume | restart   воркер: журнал, пауза, перезапуск
#   ./run.sh smoke                          по одному вызову каждой модели: проверка машины
#
# Установка по шагам (./install.sh делает их сам):
#   ./run.sh setup | build | migrate | llm-model | pin
#   ./run.sh models [video,music] [--optional]   веса моделей, все или часть
#   ./run.sh voice "описание голоса" [имя]  голос диктора в voices/narrator.wav или voices/имя.wav
#
# На арендованном сервере (адрес в .env: SERVER_HOST, SERVER_PORT, SERVER_KEY):
#   ./run.sh server install                 залить проект на свежий сервер и поставить всё
#   ./run.sh server КОМАНДА                 любая команда выше, но на сервере
#   ./run.sh server deploy                  залить код, пересобрать воркер, перезапустить
#   ./run.sh server pull | backup           забрать ролики, медиа и голоса; копия базы
#   ./run.sh server restore                 отправить .env, голоса и медиа на новый сервер
#   ./run.sh server comfy                   туннель к ComfyUI: http://localhost:8188
#   ./run.sh server gpu | check | shell [команда]
#   ./run.sh server autostop [--dry-run]    удалить сервер, когда очередь кончится или
#                                           баланса останется меньше чем на час
#
# Разработка: ./run.sh test | lint | demo | graphs
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE=(docker compose)

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

setting() { grep -s "^$1=" .env | tail -1 | cut -d= -f2-; }

worker() { "${COMPOSE[@]}" run --rm --no-deps worker "$@"; }

# The worker sees the project's studio/ at /data/studio.
worker_paths() {
    local command=$1 arg
    shift
    local args=()
    for arg in "$@"; do
        [[ $arg == studio/* ]] && arg="/data/$arg"
        args+=("$arg")
    done
    worker "$command" ${args[@]+"${args[@]}"}
}

# Tools for development come from .venv when there is one.
dev() {
    local tool=$1
    shift
    if [[ -x .venv/bin/$tool ]]; then ".venv/bin/$tool" "$@"; else "$tool" "$@"; fi
}

here() {
    local command=${1:-help}
    shift || true
    case $command in
        setup)
            [[ -f .env ]] || cp .env.example .env
            mkdir -p models hf voices outbox review studio/output studio/input studio/inbox \
                studio/series studio/user/default/workflows/reelsmith
            touch studio/ideas.txt
            chmod a+rwx models hf voices outbox
            chmod -R a+rwX studio ;;
        build) "${COMPOSE[@]}" build ;;
        models)
            local arg flags=()
            for arg in "$@"; do
                case $arg in
                    --optional) flags+=(--with-optional) ;;
                    *) flags+=(--only "$arg") ;;
                esac
            done
            "${COMPOSE[@]}" run --rm --no-deps --entrypoint python -v "$PWD:/project" -w /project \
                worker scripts/fetch_models.py --models models --hf-home hf ${flags[@]+"${flags[@]}"} ;;
        llm-model)
            "${COMPOSE[@]}" up -d llm
            "${COMPOSE[@]}" exec llm ollama pull "$(setting REELSMITH_WRITER_MODEL)" ;;
        voice)
            local description=${1:?usage: ./run.sh voice \"описание голоса\" [имя] [--text \"образец\"]}
            "${COMPOSE[@]}" run --rm --no-deps --entrypoint python tts design_voice.py \
                "${2:-narrator}" "$description" "${@:3}" ;;
        up) "${COMPOSE[@]}" up -d ;;
        down) "${COMPOSE[@]}" down ;;
        migrate) "${COMPOSE[@]}" run --rm worker migrate ;;
        pin)
            local image
            for image in ollama/ollama postgres:17-alpine; do
                docker image inspect --format '{{index .RepoDigests 0}}' "$image"
            done ;;
        ideas) worker_paths queue "${1:-studio/ideas.txt}" ;;
        series | adapt | outline | beats) worker_paths "$command" "$@" ;;
        add | jobs | status | report | styles | approve | reject | retry | rate | fork | measure \
            | compare | remix | smoke | queue)
            worker "$command" "$@" ;;
        preview)
            mkdir -p preview && chmod a+rwx preview
            "${COMPOSE[@]}" run --rm --no-deps -v "$PWD/preview:/out" worker preview \
                "${1:?usage: ./run.sh preview STYLE}" --out /out ;;
        review)
            local id=${1:?usage: ./run.sh review JOB_ID}
            mkdir -p review
            final "$id" > "review/$id.mp4"
            echo "review/$id.mp4" ;;
        final) final "${1:?usage: ./run.sh final JOB_ID}" ;;
        logs) "${COMPOSE[@]}" logs -f --tail 50 worker ;;
        pause) "${COMPOSE[@]}" stop worker ;;
        resume) "${COMPOSE[@]}" start worker ;;
        restart) "${COMPOSE[@]}" restart worker ;;
        test) dev pytest -q "$@" ;;
        lint) dev ruff check . && dev ruff format --check . && dev mypy src ;;
        demo) REELSMITH_STYLES=styles dev reelsmith demo --ideas 3 --out demo ;;
        graphs) dev python scripts/make_graphs.py ;;
        server) server "$@" ;;
        help | -h | --help) usage ;;
        *) echo "нет такой команды: $command; список: ./run.sh help" >&2; exit 1 ;;
    esac
}

final() { "${COMPOSE[@]}" run --rm --no-deps -T --entrypoint cat worker "/data/media/$1/final.mp4"; }

# Arguments quoted for the remote shell; nothing at all when there are none.
quoted() { (($#)) && printf '%q ' "$@"; true; }

server() {
    local host port key dir
    host=$(setting SERVER_HOST)
    [[ -n $host ]] || { echo "впишите в .env адрес сервера: SERVER_HOST=root@1.2.3.4, SERVER_PORT, SERVER_KEY" >&2; exit 1; }
    port=$(setting SERVER_PORT)
    key=$(setting SERVER_KEY)
    key=${key:-~/.ssh/id_ed25519}
    key=${key/#\~/$HOME}
    dir=$(setting SERVER_DIR)
    dir=${dir:-/root/reelsmith}
    local ssh=(ssh -i "$key" -p "${port:-22}" -o ServerAliveInterval=30)
    local rsync=(rsync -a -e "ssh -i '$key' -p ${port:-22}")
    # Code goes to the server and data comes back; weights are never copied. A push deletes
    # code files there that were deleted here and leaves the excluded paths alone.
    local code=(--exclude .venv --exclude __pycache__ --exclude .mypy_cache --exclude .ruff_cache
        --exclude .pytest_cache --exclude demo --exclude preview --exclude review --exclude .git
        --exclude logs --exclude models --exclude hf --exclude outbox --exclude voices
        --exclude studio --exclude .env --exclude backups --exclude '*.zip' --exclude '*.tar'
        --exclude '*.tar.gz')
    # -n: without it ssh swallows the rest of stdin and breaks `while read ...; do ./run.sh`.
    there() { "${ssh[@]}" -n "$host" "cd $dir && $*"; }
    run_there() { there "bash run.sh $(quoted "$@")"; }
    send() { "${ssh[@]}" -n "$host" "mkdir -p $dir/$(dirname "$1")"; "${rsync[@]}" "$1" "$host:$dir/$1"; }
    media_there() { there "docker volume inspect -f '{{.Mountpoint}}' reelsmith_media 2>/dev/null || true"; }

    local command=${1:-help}
    shift || true
    case $command in
        install)
            push
            "${rsync[@]}" .env "$host:$dir/.env"
            [[ -d voices ]] && "${rsync[@]}" voices/ "$host:$dir/voices/"
            "${ssh[@]}" -t "$host" "cd $dir && bash install.sh $(quoted "$@")" ;;
        push) push ;;
        deploy) push && there "docker compose build worker tts && docker compose up -d" ;;
        ideas | series | adapt)
            local file=${1:-studio/ideas.txt}
            send "$file"
            there "chmod -R a+rwX studio"
            run_there "$command" "$@"
            mkdir -p studio/series
            if [[ $command == ideas ]]; then
                "${rsync[@]}" "$host:$dir/$file" "$file"
            else
                "${rsync[@]}" "$host:$dir/studio/series/" studio/series/
            fi ;;
        review)
            local id=${1:?usage: ./run.sh server review JOB_ID}
            mkdir -p review
            run_there final "$id" > "review/$id.mp4"
            echo "review/$id.mp4" ;;
        comfy)
            echo "откройте http://localhost:8188 и не закрывайте это окно; Ctrl+C закрывает туннель"
            "${ssh[@]}" -N -L 8188:localhost:8188 "$host" ;;
        gpu)
            there 'nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv; docker compose exec -T llm ollama ps' ;;
        pull)
            mkdir -p outbox voices studio/output/reelsmith/videos studio/series backups/media
            there "mkdir -p studio/output/reelsmith/videos studio/series"
            "${rsync[@]}" "$host:$dir/outbox/" outbox/
            "${rsync[@]}" "$host:$dir/voices/" voices/
            "${rsync[@]}" "$host:$dir/studio/output/reelsmith/videos/" studio/output/reelsmith/videos/
            "${rsync[@]}" "$host:$dir/studio/series/" studio/series/
            "${rsync[@]}" "$host:$(media_there)/" backups/media/ ;;
        restore)
            there "mkdir -p voices"
            "${rsync[@]}" voices/ "$host:$dir/voices/"
            "${rsync[@]}" .env "$host:$dir/.env"
            there "chmod a+rwx voices"
            restore_media ;;
        backup)
            mkdir -p backups
            local file
            file="backups/jobs-$(date +%Y%m%d-%H%M).sql.gz"
            there "docker compose exec -T db pg_dump -U reelsmith reelsmith" | gzip > "$file"
            echo "$file" ;;
        autostop)
            mkdir -p logs
            nohup python3 scripts/autostop.py "$@" >> logs/autostop.log 2>&1 < /dev/null &
            echo "следит в фоне, pid $!; ход в logs/autostop.log; остановить: kill $!" ;;
        check)
            "${rsync[@]}" -rcn --delete --itemize-changes "${code[@]}" ./ "$host:$dir/" \
                | grep -v '^\.d' || echo "код одинаковый здесь и на сервере" ;;
        shell) "${ssh[@]}" "$host" "$@" ;;
        help) usage ;;
        *) run_there "$command" "$@" ;;
    esac
}

push() {
    "${ssh[@]}" -n "$host" "mkdir -p $dir"
    "${rsync[@]}" --delete "${code[@]}" ./ "$host:$dir/"
}

restore_media() {
    [[ -d backups/media && -n "$(ls -A backups/media)" ]] || return 0
    local media
    media=$(media_there)
    if [[ -n $media ]]; then
        "${rsync[@]}" backups/media/ "$host:$media/"
        there "chown -R 1000:1000 $media"
    else
        echo "файлы задач из backups/media вернутся, если повторить ./run.sh server restore после up"
    fi
}

here "$@"
