#!/usr/bin/env bash
# Готовит арендованный сервер к тестам видеомоделей: ComfyUI, веса LTX-2.5 и MiniMax H3.
# Запускается на сервере из папки проекта:
#
#   bash bench/box.sh comfy            поставить ComfyUI и запустить его на 127.0.0.1:8188
#   bash bench/box.sh weights ltx      скачать веса: ltx, h3, dfr (тяжёлый режим LTX) или всё сразу
#   bash bench/box.sh restart          перезапустить ComfyUI
#
# Токен Hugging Face читается из /root/.hf-token (LTX-2.5 закрыт до принятия лицензии).
set -euo pipefail

COMFY=${COMFY_DIR:-/root/ComfyUI}
VENV=${COMFY_VENV:-/root/comfy-venv}
MODELS=$COMFY/models
export PATH="$HOME/.local/bin:$PATH"

comfy() {
    # Автообновления держат замок dpkg и ломают драйвер новой версией ядра.
    systemctl disable --now unattended-upgrades apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
    command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
    [ -d "$COMFY" ] || git clone -q --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$COMFY"
    [ -d "$VENV" ] || uv venv -q --python 3.12 "$VENV"
    local driver wheels=cu128
    driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)
    [ "$driver" -ge 580 ] && wheels=cu130
    uv pip install -q --python "$VENV/bin/python" torch torchvision torchaudio \
        --index-url "https://download.pytorch.org/whl/$wheels"
    uv pip install -q --python "$VENV/bin/python" -r "$COMFY/requirements.txt" "huggingface_hub[hf_transfer]"
    restart
}

restart() {
    pkill -f "$COMFY/main.py" 2>/dev/null || true
    sleep 2
    nohup "$VENV/bin/python" "$COMFY/main.py" --listen 127.0.0.1 --port 8188 \
        >"$COMFY/server.log" 2>&1 &
    for _ in $(seq 60); do
        curl -fsS -m 3 http://127.0.0.1:8188/system_stats >/dev/null 2>&1 && { echo "ComfyUI отвечает"; return; }
        sleep 3
    done
    tail -30 "$COMFY/server.log"
    echo "ComfyUI не поднялся" >&2
    exit 1
}

fetch() {
    local repo=$1
    shift
    HF_TOKEN=$(cat /root/.hf-token) HF_HUB_ENABLE_HF_TRANSFER=1 \
        "$VENV/bin/hf" download "$repo" "$@" --local-dir "$MODELS" >/dev/null
    echo "есть: $repo ($# файлов)"
}

ltx() {
    fetch Lightricks/LTX-2.5 \
        diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors \
        text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors \
        vae/ltx-2.5-video-vae-bf16.safetensors vae/ltx-2.5-audio-vae-bf16.safetensors \
        latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors
    fetch Comfy-Org/gemma-4 text_encoders/gemma4_e2b_it_int8_convrot.safetensors
}

dfr() {
    fetch Lightricks/LTX-2.5 \
        text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors \
        latent_upscale_models/ltx-2.5-latent-temporal-upscaler-x2-bf16-1.0.safetensors
    fetch Comfy-Org/gemma-4 text_encoders/gemma4_e2b_it_bf16.safetensors
    HF_TOKEN=$(cat /root/.hf-token) HF_HUB_ENABLE_HF_TRANSFER=1 "$VENV/bin/hf" download \
        Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler \
        ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors \
        --local-dir "$MODELS/loras" >/dev/null
}

h3() {
    fetch Comfy-Org/MiniMax-H3 \
        diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
        diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors \
        text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
        vae/minimax_h3_video_vae_int8_convrot.safetensors vae/minimax_h3_video_vae_fp16.safetensors \
        vae/minimax_h3_audio_vae_fp32.safetensors \
        loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors \
        loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
}

weights() {
    for what in "${@:-ltx h3}"; do "$what"; done
    df -h "$MODELS" | tail -1
}

"$@"
