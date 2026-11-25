#!/usr/bin/env bash
# Все команды reelsmith. Linux, macOS, WSL; на Windows то же самое делает run.cmd.
#
# Каждый день:
#   ./run.sh add "идея" [--style blackout]   идея или рассказ в очередь
#   ./run.sh add --file книга.fb2            рассказ или книга: по задаче на каждую часть
#   ./run.sh run [--once]                    провести все задачи по стадиям
#   ./run.sh jobs | show ID                  задачи и их ход
#   ./run.sh storyboard ID                   ключевые кадры всех битов на одном листе
#   ./run.sh redo ID --beat 5 --note "..."   переделать один бит по замечанию
#   ./run.sh approve ID | reject ID --reason "..." | retry ID [--status voiced]
#   ./run.sh styles                          стили
#
# Модели на этой машине (если есть видеокарта, ./install.sh --models):
#   ./run.sh up | down | logs                сервисы моделей: ollama и речь
#   ./run.sh voice "описание" [имя]          голос диктора в voices/имя.wav (по умолчанию narrator)
#   ./run.sh smoke                           по одному вызову каждой модели и один кадр
#   ./run.sh rehearse [--beats 4]            весь путь от идеи до ролика без моделей, с заглушками
#
# Арендованный сервер (адрес в .env: SERVER_HOST, SERVER_PORT, SERVER_KEY, VAST_INSTANCE):
#   ./run.sh box rent [--vram 80] [--price 2.5] [--dry-run]
#                                            арендовать сервер на vast.ai и вписать его адрес в .env
#   ./run.sh box install                     залить проект, поставить модели, включить сторож
#   ./run.sh box run                         залить задачи и провести их на сервере
#   ./run.sh box pull                        забрать задачи и голоса
#   ./run.sh box status                      задачи и видеокарта на сервере
#   ./run.sh box tunnel                      модели сервера на этой машине: ./run.sh run здесь
#   ./run.sh box autostop [--dry-run]        удалить сервер, когда задачи кончатся, он простаивает
#                                            или баланса останется меньше чем на час
#   ./run.sh box push | logs | shell [команда]
#
# Разработка: ./run.sh test | lint
set -euo pipefail
cd "$(dirname "$0")"

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }
setting() { grep -s "^$1=" .env | tail -1 | cut -d= -f2-; }
quoted() { local a out=(); for a in "$@"; do out+=("$(printf '%q' "$a")"); done; echo "${out[*]}"; }
bin() { if [[ -x .venv/bin/$1 ]]; then echo ".venv/bin/$1"; else echo "$1"; fi; }

here() {
    local command=${1:-help}
    shift || true
    case $command in
        up)
            if [[ $(setting REELSMITH_TTS) == qwen ]]; then docker compose up -d llm speech
            else docker compose up -d llm speech voice; fi ;;
        down) docker compose down ;;
        logs) docker compose logs --tail 100 -f "$@" ;;
        voice)
            local description=${1:?usage: ./run.sh voice "описание голоса" [имя]}
            docker compose run --rm speech python design_voice.py "${2:-narrator}" "$description" ;;
        test)
            "$(bin pytest)" -q
            (cd runtime && npm test --silent) ;;
        rehearse) "$(bin python)" scripts/rehearse.py "$@" ;;
        lint)
            "$(bin ruff)" check src tests scripts tools
            "$(bin ruff)" format --check src tests
            "$(bin mypy)" src ;;
        box) box "$@" ;;
        help | -h | --help) usage ;;
        *) "$(bin reelsmith)" "$command" "$@" ;;
    esac
}

box() {
    if [[ ${1:-} == rent ]]; then
        shift
        python3 scripts/rent.py "$@"
        return
    fi
    local host port key dir
    host=$(setting SERVER_HOST)
    [[ -n $host ]] || { echo "впишите в .env адрес сервера: SERVER_HOST=root@1.2.3.4, SERVER_PORT, SERVER_KEY" >&2; exit 1; }
    port=$(setting SERVER_PORT)
    key=$(setting SERVER_KEY)
    key=${key:-~/.ssh/id_ed25519}
    key=${key/#\~/$HOME}
    dir=$(setting SERVER_DIR)
    dir=${dir:-/root/reelsmith}
    local ssh=(ssh -i "$key" -p "${port:-22}" -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new)
    local rsync=(rsync -a -e "ssh -i '$key' -p ${port:-22}")
    # Code goes to the server and jobs come back; weights are never copied. A push deletes
    # code files there that were deleted here and leaves the excluded paths alone: the thing
    # library is one of them, each machine imports its own.
    local code=(--exclude .venv --exclude __pycache__ --exclude .mypy_cache --exclude .ruff_cache
        --exclude .pytest_cache --exclude node_modules --exclude review --exclude .git
        --exclude logs --exclude hf --exclude outbox --exclude voices --exclude jobs
        --exclude studio --exclude .env --exclude backups --exclude library
        --exclude '*.zip' --exclude '*.tar' --exclude '*.tar.gz')
    # -n: without it ssh swallows the rest of stdin and breaks `while read ...; do ./run.sh`.
    there() { "${ssh[@]}" -n "$host" "cd $dir && $*"; }
    push() {
        "${ssh[@]}" -n "$host" "mkdir -p $dir"
        "${rsync[@]}" --delete "${code[@]}" ./ "$host:$dir/"
    }

    local command=${1:-help}
    shift || true
    case $command in
        install)
            push
            "${rsync[@]}" .env "$host:$dir/.env"
            [[ -d voices ]] && "${rsync[@]}" voices/ "$host:$dir/voices/"
            # The watcher starts before anything else: a box that sits idle bills all the same.
            # shellcheck disable=SC2046
            here box autostop $(setting AUTOSTOP_ARGS)
            "${ssh[@]}" -t "$host" "cd $dir && bash install.sh --models $(quoted "$@")" ;;
        push) push ;;
        run)
            push
            mkdir -p jobs
            "${rsync[@]}" jobs/ "$host:$dir/jobs/"
            # In brackets: a bare `a && b &` backgrounds a shell that keeps the SSH channel open,
            # and this command would hang until the last job is done.
            there "mkdir -p logs && (nohup .venv/bin/reelsmith run >> logs/run.log 2>&1 < /dev/null &)"
            echo "задачи идут на сервере; ход: ./run.sh box logs, забрать: ./run.sh box pull" ;;
        pull)
            mkdir -p jobs voices
            "${rsync[@]}" "$host:$dir/jobs/" jobs/
            "${rsync[@]}" "$host:$dir/voices/" voices/ ;;
        status)
            there ".venv/bin/reelsmith jobs; nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader" ;;
        logs) there "tail -n 60 -f logs/run.log" ;;
        tunnel)
            echo "модели сервера видны здесь, пока открыто это окно; Ctrl+C закрывает туннель"
            "${ssh[@]}" -N -L 11434:localhost:11434 -L 8000:localhost:8000 -L 8001:localhost:8001 "$host" ;;
        autostop)
            mkdir -p logs
            nohup python3 scripts/autostop.py "$@" >> logs/autostop.log 2>&1 < /dev/null &
            echo "сторож следит в фоне, pid $!; ход в logs/autostop.log; остановить: kill $!" ;;
        shell) "${ssh[@]}" "$host" "$@" ;;
        help) usage ;;
        *) echo "нет такой команды сервера: $command; ./run.sh help" >&2; exit 1 ;;
    esac
}

here "$@"
