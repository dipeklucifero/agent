FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: build-essential only needed if any pure-Python wheel is missing.
# libsecp256k1 headers help eth-account build fast on slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
        libsecp256k1-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for layer cache.
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install .

COPY src ./src
COPY config ./config
RUN mkdir -p /app/data

RUN pip install .

# Data (SQLite, keystore) lives on a mounted volume.
VOLUME ["/app/data", "/app/config"]

CMD ["hermes-agent"]
