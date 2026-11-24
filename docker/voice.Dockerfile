# The narrator's voice by Chatterbox Multilingual. It has an image of its own because it
# pins torch 2.6, which Qwen3-TTS in the speech image cannot share.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# Pin it once a build has been listened to.
ARG CHATTERBOX=0.1.7

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/hf \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv libsndfile1 ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3.10 -m venv /opt/venv

RUN pip install "chatterbox-tts==${CHATTERBOX}" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30" "soundfile>=0.12"

WORKDIR /srv
COPY services/voice/app.py ./

RUN useradd --uid 1000 --create-home narrator
USER narrator

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
