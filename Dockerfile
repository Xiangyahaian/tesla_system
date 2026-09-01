# syntax=docker/dockerfile:1.7

# -----------------------------------------------------------------------------
# Stage 1: Build React cabin HMI (Vite)
# -----------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2: Python runtime with CUDA (handbook RAG embedding/reranker)
# -----------------------------------------------------------------------------
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime AS runtime

LABEL org.opencontainers.image.title="Tesla System"
LABEL org.opencontainers.image.description="Tesla intelligent cabin agent (FastAPI + RAG + React HMI)"
LABEL org.opencontainers.image.source="https://github.com/Xiangyahaian/tesla_system"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOME=/app \
    APP_HOST=0.0.0.0 \
    APP_PORT=6006 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

WORKDIR ${APP_HOME}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tini \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for runtime
RUN groupadd --gid 1000 tesla \
    && useradd --uid 1000 --gid tesla --create-home --shell /usr/sbin/nologin tesla

COPY requirements.txt ./
# PyPI 无 4.51.1d；构建镜像时归一化为可用版本
RUN sed -i 's/transformers==4.51.1d/transformers==4.51.1/' requirements.txt \
    && python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

RUN chmod +x docker/entrypoint.sh \
    && mkdir -p state/sessions log data/saved_index \
    && chown -R tesla:tesla ${APP_HOME}

USER tesla

EXPOSE 6006

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${APP_PORT}/api/model-status" >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "docker/entrypoint.sh"]
CMD ["python", "run.py"]
