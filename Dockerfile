FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libsecp256k1-dev speeds up eth-account wheels; rest is build toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
        libsecp256k1-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the package first (hatchling needs src/ to build the wheel) then install.
# One install keeps the image small on a 40GB VPS.
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /app/data

# Data (SQLite, keystore) lives on a mounted volume.
VOLUME ["/app/data", "/app/config"]

CMD ["hermes-agent"]
