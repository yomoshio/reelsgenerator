#!/usr/bin/env bash
# Ставит reelsmith на эту машину и запускает. Повторный запуск пропускает сделанное и
# пересобирает образы из текущего кода.
#
#   ./install.sh                       Linux с видеокартой NVIDIA: свой компьютер или сервер
#   ./install.sh --no-models           без весов моделей (около 110 ГБ) и без проверки
#   ./install.sh --voice "описание"    свой голос диктора вместо стандартного
#   ./install.sh driver                только драйвер NVIDIA на чистой Ubuntu, потом перезагрузка
#
# Windows: install.cmd, он ставит WSL и Docker Desktop и запускает этот файл в Ubuntu.
# macOS: нужен Docker Desktop. Видеокарты NVIDIA там нет, поэтому ставится только то, что
# нужно для ./run.sh demo и для управления сервером через ./run.sh server.
# Арендованный сервер ставится с вашего компьютера: ./run.sh server install.
set -euo pipefail
cd "$(dirname "$0")"

VOICE="A gripping storyteller in his forties, low warm voice, lively intonation, dramatic pauses, building tension, never monotone"
DRIVER=nvidia-driver-580-open  # RTX 50xx (Blackwell) runs only on the open kernel modules
MODELS=1

say() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail() { printf '\n%s\n' "$*" >&2; exit 1; }
as_root() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }
run() { bash run.sh "$@"; }

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

host_linux() {
    local wsl=0
    grep -qi microsoft /proc/version 2>/dev/null && wsl=1
    command -v nvidia-smi > /dev/null \
        || fail "Нет драйвера NVIDIA. На Ubuntu: ./install.sh driver, перезагрузка и ./install.sh снова."
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
    note "Docker видит видеокарту."
    local free ram
    free=$(df -BG --output=avail . | tail -1 | tr -dc 0-9)
    ((free >= 250)) || note "Свободно ${free} ГБ, а весам и образам нужно около 250 ГБ."
    ram=$(free -g | awk '/^Mem:/ {print $2}')
    if ((ram < 60)) && ! grep -q '^COMFY_ARGS=.*--fast-disk' .env 2>/dev/null; then
        note "Памяти ${ram} ГБ: ComfyUI не удержит все модели в RAM. В .env ставлю COMFY_ARGS=--fast-disk."
        [[ -f .env ]] || cp .env.example .env
        if grep -q '^COMFY_ARGS=' .env; then
            sed -i 's/^COMFY_ARGS=.*/COMFY_ARGS=--fast-disk/' .env
        else
            echo 'COMFY_ARGS=--fast-disk' >> .env
        fi
    fi
}

while (($#)); do
    case $1 in
        --no-models) MODELS=0 ;;
        --voice) VOICE=${2:?--voice "описание голоса"}; shift ;;
        driver) driver; exit 0 ;;
        -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
        *) fail "непонятный параметр: $1" ;;
    esac
    shift
done

say "Машина"
case $(uname -s) in
    Darwin)
        command -v docker > /dev/null || fail "Поставьте Docker Desktop с docker.com и запустите ./install.sh снова."
        run setup
        note "На macOS нет видеокарты NVIDIA: модели не ставятся."
        note "Прогон на заглушках: ./run.sh demo. Сервер: SERVER_HOST в .env и ./run.sh server install."
        exit 0 ;;
    Linux) host_linux ;;
    *) fail "Эта система не поддерживается; на Windows запустите install.cmd." ;;
esac

say "Проект"
run setup
note "Настройки: $PWD/.env"

say "Образы, 10-20 минут при первом запуске"
run build

if ((MODELS)); then
    say "Веса моделей, около 110 ГБ"
    run models
fi

say "Запуск"
run up
run migrate

if ((MODELS)); then
    say "Модель сценариста"
    run llm-model
    if [[ ! -f voices/narrator.wav ]]; then
        say "Голос диктора"
        run voice "$VOICE"
    fi
    say "Проверка: по одному вызову каждой модели"
    run smoke || note "Проверка не прошла, смотрите вывод выше и docs/setup.md."
fi

say "Готово"
note "ComfyUI: http://localhost:8188. Идея в очередь: ./run.sh add \"идея\". Все команды: ./run.sh help"
