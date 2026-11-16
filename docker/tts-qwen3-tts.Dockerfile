# Qwen3-TTS behind the same HTTP API as tts-voxcpm.Dockerfile; REELSMITH_TTS_ENGINE=qwen3-tts picks it.
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ARG TORCH=2.9.1
ARG TORCHAUDIO=2.9.1
# Empty installs the newest release; pin it once a build has been listened to.
ARG QWEN_TTS=

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/hf \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv libsndfile1 ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/venv

RUN pip install torch==${TORCH} torchaudio==${TORCHAUDIO} --index-url https://download.pytorch.org/whl/cu128 \
    && pip install "qwen-tts${QWEN_TTS:+==${QWEN_TTS}}" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30" "soundfile>=0.12"

WORKDIR /srv
COPY services/tts/qwen/app.py services/tts/qwen/design_voice.py ./

# Ubuntu 24.04 images already ship user `ubuntu` with uid 1000; reuse it instead of useradd.
USER ubuntu

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
