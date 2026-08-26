# Multi-stage: dependencies are resolved into a venv in the builder, and only
# the finished venv crosses into the runtime image. That keeps pip, setuptools,
# wheel and any sdist build residue out of the shipped layers.
#
# Self-contained by design: the source is COPYed in, not bind-mounted. The old
# compose.yml mounted ./:/app and supplied the command, so the image was really
# just "python + requirements". That does not survive the trip to a server --
# Portainer clones the repo to its own root-owned directory.
#
# Built with DOCKER_BUILDKIT=0 against Podman's docker-compat API, which serves
# the classic /build endpoint. Do NOT introduce heredoc COPY, --mount=type=cache
# or --mount=type=secret here; the classic builder cannot parse them.

# --------------------------------------------------------------------------
# Stage 1: build the virtualenv
# --------------------------------------------------------------------------
FROM python:3.13.3-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# No apt layer: every remaining pin ships a cp313 manylinux x86_64 wheel, so
# nothing is compiled from source and no toolchain is needed. If you add a
# dependency without a wheel, install build-essential HERE (builder only)
# rather than in the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Requirements first so this layer -- by far the slowest, ~60 wheels including
# numpy and scipy -- is reused whenever only application code changed.
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Wheels ship tests and bundled headers that a running bot never touches.
# scipy/numpy test suites alone are tens of megabytes.
RUN find /opt/venv -type d -name tests -prune -exec rm -rf {} + && \
    find /opt/venv -type d -name test -prune -exec rm -rf {} + && \
    find /opt/venv -type d -name include -prune -exec rm -rf {} + && \
    find /opt/venv -name '*.pyi' -delete && \
    find /opt/venv -name '*.c' -delete && \
    find /opt/venv -name '*.h' -delete

# --------------------------------------------------------------------------
# Stage 2: runtime
# --------------------------------------------------------------------------
FROM python:3.13.3-slim AS runtime

# Stamped by CI so a running container can be traced back to a commit.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    CONFIG_PATH=/config \
    SQLITE_PATH=/data/artbot.db \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY . /app

# Doubles as the syntax gate: compileall exits non-zero on a SyntaxError, so a
# broken cog fails the build instead of being swallowed into a log line at
# extension-load time. It also pre-populates __pycache__, which PYTHONDONTWRITE-
# BYTECODE would otherwise prevent at runtime, so startup does no compilation.
RUN python -m compileall -q cogs db services utils web \
        main.py config.py exception.py view.py

# Both directories are volume mount points. Create them owned by the app user
# first: Docker seeds a fresh named volume from the image, ownership included,
# and the bot writes char_map.json into /config and the SQLite WAL into /data.
RUN groupadd --system --gid 1001 artbot && \
    useradd --system --uid 1001 --gid artbot --no-create-home artbot && \
    mkdir -p /config /data && \
    chown -R artbot:artbot /config /data /app

USER artbot

EXPOSE 8000

CMD ["python", "main.py"]
