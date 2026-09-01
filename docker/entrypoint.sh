#!/usr/bin/env bash
# Tesla System container entrypoint — wait for dependencies, then start API.
set -euo pipefail

APP_HOME="${APP_HOME:-/app}"
cd "${APP_HOME}"

MONGO_HOST="${MONGO_HOST:-mongodb}"
MONGO_PORT="${MONGO_PORT:-27017}"
WAIT_TIMEOUT="${DOCKER_WAIT_TIMEOUT_SEC:-120}"

log() {
  printf '[entrypoint] %s\n' "$*"
}

wait_for_tcp() {
  local host="$1"
  local port="$2"
  local deadline=$((SECONDS + WAIT_TIMEOUT))

  log "waiting for ${host}:${port} (timeout ${WAIT_TIMEOUT}s)..."
  while ! python - <<PY
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(("${host}", int("${port}")))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
  do
    if (( SECONDS >= deadline )); then
      log "ERROR: timed out waiting for ${host}:${port}"
      exit 1
    fi
    sleep 2
  done
  log "${host}:${port} is reachable"
}

preflight() {
  local missing=0
  for path in \
    "data/saved_index/bm25retriever.pkl" \
    "data/saved_index/milvus.db" \
    "models/BAAI/bge-m3" \
    "RAG-Retrieval/rag_retrieval/train/reranker/output/bert/runs/checkpoints/checkpoint_0"
  do
    if [[ ! -e "${path}" ]]; then
      log "WARN: missing runtime artifact: ${path}"
      missing=1
    fi
  done
  if [[ "${missing}" -eq 1 ]]; then
    log "See docs/docker.md — mount models/, saved_index/, reranker checkpoint, and MongoDB data."
  fi

  if [[ "${RAG_ENABLE:-1}" != "0" ]]; then
    if ! python - <<'PY' 2>/dev/null; then
import torch
raise SystemExit(0 if torch.cuda.is_available() else 1)
PY
      log "WARN: CUDA not visible; handbook RAG (embedding/reranker) requires GPU. Set RAG_ENABLE=0 for demo without RAG."
    fi
  fi
}

wait_for_tcp "${MONGO_HOST}" "${MONGO_PORT}"
preflight

log "starting: $*"
exec "$@"
