# No GPU here: the models run in their own containers; ffmpeg and whisper run on the CPU.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/hf \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv ffmpeg fonts-montserrat fontconfig ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/venv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[subtitles]" "huggingface-hub[hf_transfer]>=0.25"

COPY migrations ./migrations
COPY workflows ./workflows
COPY styles ./styles
COPY scripts ./scripts
COPY models.toml ./

# Ubuntu 24.04 images already ship user `ubuntu` with uid 1000; reuse it instead of useradd.
RUN mkdir -p /data/media /data/outbox && chown -R ubuntu:ubuntu /data
USER ubuntu

ENTRYPOINT ["reelsmith"]
CMD ["work"]
