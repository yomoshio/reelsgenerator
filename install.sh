#!/usr/bin/env bash
# Ставит reelsmith. Повторный запуск пропускает сделанное и служит обновлением.
#
#   ./install.sh                  конвейер на этой машине: Python, Node, ffmpeg. Видеокарта не нужна,
#                                 модели работают на арендованном сервере (./run.sh box install)
#   ./install.sh --models         ещё и модели на этой машине: Docker, ollama, сервис речи,
#                                 веса из .env и голос диктора. Нужна NVIDIA от 24 ГБ
#   ./install.sh --voice "описание"  свой голос диктора вместо стандартного
#   ./install.sh driver           только драйвер NVIDIA на чистой Ubuntu, потом перезагрузка
#
# Windows: install.cmd ставит WSL и Docker Desktop и запускает этот файл в Ubuntu.
set -euo pipefail
cd "$(dirname "$0")"

VOICE="A calm low male voice in his thirties, close to the microphone, unhurried and a little tense, telling a friend what happened last night"
DRIVER=nvidia-driver-580-open  # RTX 50xx (Blackwell) runs only on the open kernel modules
MODELS=0

say() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail() { printf '\n%s\n' "$*" >&2; exit 1; }
as_root() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }
setting() { grep -s "^$1=" .env | tail -1 | cut -d= -f2-; }

gpu_packages() {
    dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' 'nvidia-*' 'libnvidia-*' 2>/dev/null \
        | awk '$1 == "ii" {print $2}'
}

driver() {
    as_root apt-mark unhold $(gpu_packages) >/dev/null 2>&1 || true
    as_root apt-get update
    as_root apt-get install -y "$DRIVER"
    echo "драйвер поставлен; перезагрузите машину и запустите ./install.sh снова"
}

pipeline() {
    say "Конвейер"
    [[ -f .env ]] || cp .env.example .env
    mkdir -p jobs outbox voices review logs
    if ! command -v ffmpeg >/dev/null; then
        command -v apt-get >/dev/null || fail "Поставьте ffmpeg и запустите ./install.sh снова."
        as_root apt-get update && as_root apt-get install -y ffmpeg
    fi
    local node_major=0
    command -v node >/dev/null && node_major=$(node -p 'process.versions.node.split(".")[0]')
    if ((node_major < 22)); then
        command -v apt-get >/dev/null || fail "Нужен Node 22 или новее: nodejs.org."
        curl -fsSL https://deb.nodesource.com/setup_22.x | as_root bash -
        as_root apt-get install -y nodejs
    fi
    note "node $(node -v), $(ffmpeg -version | head -1 | cut -d' ' -f1-3)"
    (cd runtime && npm ci --no-audit --no-fund --loglevel=error)
    local python
    python=$(command -v python3.12 || command -v python3)
    "$python" -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
        || fail "Нужен Python 3.12 или новее."
    [[ -x .venv/bin/python ]] || "$python" -m venv .venv
    .venv/bin/python -m pip --version >/dev/null 2>&1 || .venv/bin/python -m ensurepip --upgrade
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -e ".[check]"
    if [[ ! -f library/things/index.json ]]; then
        note "Библиотека вещей: силуэты game-icons.net"
        .venv/bin/python scripts/import_icons.py
    fi
    note "Настройки: $PWD/.env"
}

docker_engine() {
    say "Docker"
    as_root apt-get update
    as_root apt-get install -y ca-certificates curl
    as_root install -m 0755 -d /etc/apt/keyrings
    as_root curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    as_root chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        | as_root tee /etc/apt/sources.list.d/docker.list > /dev/null
    as_root apt-get update
    as_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    if [[ $EUID -ne 0 ]]; then
        as_root usermod -aG docker "$USER"
        fail "Docker поставлен. Выйдите из системы и войдите снова, чтобы он заработал без sudo, и запустите ./install.sh ещё раз."
    fi
}

toolkit() {
    say "Видеокарта в контейнерах"
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | as_root gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | as_root tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
    as_root apt-get update
    as_root apt-get install -y nvidia-container-toolkit
    as_root nvidia-ctk runtime configure --runtime=docker
    # With the systemd cgroup driver a container loses the GPU ("Failed to initialize NVML")
    # after the host reloads systemd; cgroupfs does not have that problem.
    as_root python3 - <<'PY'
import json

path = "/etc/docker/daemon.json"
config = json.load(open(path))
config["exec-opts"] = ["native.cgroupdriver=cgroupfs"]
json.dump(config, open(path, "w"), indent=4)
PY
    as_root systemctl restart docker
    # Unattended upgrades replaced the driver libraries under running containers on a rented
    # box, and every new container then failed with "Driver/library version mismatch" until
    # a reboot. The driver now changes only through ./install.sh driver.
    as_root apt-mark hold $(gpu_packages) >/dev/null
    printf '%s\n' 'Unattended-Upgrade::Package-Blacklist {' '    "nvidia-";' '    "libnvidia-";' '};' \
        | as_root tee /etc/apt/apt.conf.d/51reelsmith-no-gpu-upgrades > /dev/null
}

models() {
    say "Видеокарта"
    local wsl=0
    grep -qi microsoft /proc/version 2>/dev/null && wsl=1
    command -v nvidia-smi > /dev/null \
        || fail "Нет драйвера NVIDIA. На Ubuntu: ./install.sh driver, перезагрузка и ./install.sh --models снова."
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | sed 's/^/   видеокарта: /'
    if ! command -v docker > /dev/null; then
        ((wsl)) && fail "Docker не виден в Ubuntu. В Docker Desktop: Settings, Resources, WSL integration."
        docker_engine
    fi
    docker info > /dev/null 2>&1 || fail "Docker не отвечает: запустите его или добавьте себя в группу docker."
    if ! docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi -L > /dev/null 2>&1; then
        ((wsl)) && fail "Docker не видит видеокарту. Обновите драйвер NVIDIA в Windows и Docker Desktop."
        toolkit
        docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi -L > /dev/null \
            || fail "Контейнеры так и не видят видеокарту."
    fi
    say "Сервисы моделей: ollama и речь"
    mkdir -p hf voices
    chmod a+rwx hf voices
    docker compose build speech
    docker compose up -d llm speech
    say "Языковые модели из .env"
    local model
    for model in $(for k in PLANNER DIRECTOR CODER VISION EDITOR; do setting "REELSMITH_$k"; done | sort -u); do
        note "ollama pull $model"
        docker compose exec -T llm ollama pull "$model"
    done
    if [[ ! -f voices/narrator.wav ]]; then
        say "Голос диктора"
        bash run.sh voice "$VOICE" narrator
    fi
}

while (($#)); do
    case $1 in
        --models) MODELS=1 ;;
        --voice) VOICE=${2:?--voice "описание голоса"}; shift ;;
        driver) driver; exit 0 ;;
        -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
        *) fail "непонятный параметр: $1" ;;
    esac
    shift
done

pipeline
if ((MODELS)); then
    models
    say "Проверка: по одному вызову каждой модели и отрисовка одного кадра"
    bash run.sh smoke || note "Проверка не прошла, смотрите вывод выше и docs/setup.md."
fi
say "Готово"
note "Идея в очередь: ./run.sh add \"идея\". Все команды: ./run.sh help"
