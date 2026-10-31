# ComfyUI, headless. CUDA 12.8 is the first release with Blackwell (RTX 50xx) kernels.
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ARG COMFYUI_REF=v0.43.1
ARG TORCH=2.9.1
ARG TORCHVISION=0.24.1
ARG TORCHAUDIO=2.9.1
# Custom nodes move fast and break; pin each to a commit you have tested.
ARG VHS_REF=main
ARG RIFE_REF=main
ARG GGUF_REF=main

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev build-essential git \
        ffmpeg libgl1 libglib2.0-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/venv

RUN pip install torch==${TORCH} torchvision==${TORCHVISION} torchaudio==${TORCHAUDIO} \
        --index-url https://download.pytorch.org/whl/cu128

WORKDIR /opt/comfy
RUN git clone --depth 1 --branch ${COMFYUI_REF} https://github.com/comfyanonymous/ComfyUI.git . \
    && pip install -r requirements.txt

COPY docker/install-node.sh /usr/local/bin/install-node
RUN install-node https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git ${VHS_REF} \
    && install-node https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git ${RIFE_REF} \
    && install-node https://github.com/city96/ComfyUI-GGUF.git ${GGUF_REF}

# Ubuntu 24.04 images already ship user `ubuntu` with uid 1000; reuse it instead of useradd.
RUN mkdir -p models input output user && chown -R ubuntu:ubuntu /opt/comfy
USER ubuntu

EXPOSE 8188
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8188/system_stats')"

# --reserve-vram leaves room for the desktop and the CUDA context of other containers.
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", \
     "--disable-auto-launch", "--preview-method", "none", "--reserve-vram", "1.0"]
