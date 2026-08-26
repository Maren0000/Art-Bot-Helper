# Self-contained image: the source is COPYed in, not bind-mounted.
#
# The previous compose.yml mounted ./:/app and left this file with no COPY and
# no CMD, so the image was really just "python + requirements" and the code came
# from the host. That does not survive the trip to a server -- Portainer clones
# the repo to its own directory, so the mount would either be missing or
# root-owned. CI builds a real image and Portainer only pulls it.
#
# Built with DOCKER_BUILDKIT=0 against Podman's docker-compat API, which serves
# the classic /build endpoint. Do NOT introduce heredoc COPY,
# --mount=type=cache, or --mount=type=secret here -- the classic builder cannot
# parse them and the build fails.

FROM python:3.13.3-slim

# Stamped by CI so /healthz-adjacent debugging can tell which build is running.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Runtime deps for the wheels that have no manylinux build for 3.13 (lxml,
# scipy, cryptography fall back to source on some platforms) plus curl for the
# healthcheck. Kept in one layer so the apt lists are dropped in the same step.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first: this layer only rebuilds when requirements.txt changes,
# and installing ~70 pinned wheels is by far the slowest step.
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . /app

# Both directories are volume mount points. Create them owned by the app user so
# a first-boot empty volume is writable -- Docker copies image ownership onto a
# fresh named volume, and the bot writes char_map.json into /config from the
# web UI and the SQLite WAL files into /data.
RUN groupadd --system --gid 1001 artbot && \
    useradd --system --uid 1001 --gid artbot --no-create-home artbot && \
    mkdir -p /config /data && \
    chown -R artbot:artbot /config /data /app

ENV CONFIG_PATH=/config \
    SQLITE_PATH=/data/artbot.db \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000

USER artbot

EXPOSE 8000

CMD ["python", "main.py"]
