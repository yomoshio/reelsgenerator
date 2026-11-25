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

RUN pip install "chatterbox-tts==${CHATTERBOX}" "ruaccent==1.6.0" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30" "soundfile>=0.12"

# Chatterbox pins torch 2.6, which has no code for the 50-series cards (a 5090, an RTX PRO
# 5000): "no kernel image is available". 2.7 built for CUDA 12.8 runs on them and on the
# older cards alike.
RUN pip install "torch==2.7.1" "torchaudio==2.7.1" --index-url https://download.pytorch.org/whl/cu128

WORKDIR /srv
COPY services/voice/app.py ./

RUN useradd --uid 1000 --create-home narrator
USER narrator

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
