#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 host for the GPU containers.
#
#   sudo scripts/setup-host.sh driver    # then reboot
#   sudo scripts/setup-host.sh docker
#   sudo scripts/setup-host.sh toolkit
#   scripts/setup-host.sh check
#
# RTX 50xx (Blackwell) cards only work with the open kernel modules, hence the -open driver.
set -euo pipefail

DRIVER=${DRIVER:-nvidia-driver-580-open}

need_root() {
    [[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
}

driver() {
    need_root
    apt-mark unhold $(gpu_packages) >/dev/null 2>&1 || true
    apt-get update
    apt-get install -y "$DRIVER"
    echo "driver installed, reboot before the next step"
}

docker_engine() {
    need_root
    apt-get update
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    if [[ -n ${SUDO_USER:-} ]]; then
        usermod -aG docker "$SUDO_USER"
    fi
}

toolkit() {
    need_root
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update
    apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    # With the systemd cgroup driver a container loses the GPU ("Failed to initialize NVML")
    # after the host reloads systemd; cgroupfs does not have that problem.
    python3 - <<'PY'
import json

path = "/etc/docker/daemon.json"
config = json.load(open(path))
config["exec-opts"] = ["native.cgroupdriver=cgroupfs"]
json.dump(config, open(path, "w"), indent=4)
PY
    systemctl restart docker
    hold_driver
}

gpu_packages() {
    dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' 'nvidia-*' 'libnvidia-*' 2>/dev/null \
        | awk '$1 == "ii" {print $2}'
}

# Unattended upgrades replaced the driver libraries under running containers on a rented
# box, and every new container then failed with "Driver/library version mismatch" until a
# reboot. The driver now changes only when `driver` is run.
hold_driver() {
    apt-mark hold $(gpu_packages) >/dev/null
    printf '%s\n' 'Unattended-Upgrade::Package-Blacklist {' '    "nvidia-";' '    "libnvidia-";' '};' \
        > /etc/apt/apt.conf.d/51reelsmith-no-gpu-upgrades
}

check() {
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
    docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi -L
    df -h --output=avail,target . | tail -1 | awk '{print "free disk here: " $1 " (models need ~150G)"}'
}

case ${1:-} in
    driver) driver ;;
    docker) docker_engine ;;
    toolkit) toolkit ;;
    check) check ;;
    *) sed -n '2,9p' "$0"; exit 1 ;;
esac
