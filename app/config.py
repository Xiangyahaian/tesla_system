# -*- coding: utf-8 -*-
"""应用级配置。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PORT = int(os.getenv("APP_PORT", "6006"))
HOST = os.getenv("APP_HOST", "0.0.0.0")

# LLM
BAILIAN_API_BASE = os.getenv("BAILIAN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
BAILIAN_API_KEY = os.getenv("BAILIAN_API_KEY", "")
BAILIAN_MODEL_NAME = os.getenv("BAILIAN_MODEL_NAME", "qwen3.5-flash")

VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://127.0.0.1:8000/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME", "qwen-4b-tesla")

LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "45"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# RAG
RAG_BM25_TOPK = int(os.getenv("RAG_BM25_TOPK", "8"))
RAG_MILVUS_TOPK = int(os.getenv("RAG_MILVUS_TOPK", "8"))
RAG_RERANK_TOPK = int(os.getenv("RAG_RERANK_TOPK", "4"))
RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.15"))
RAG_ENABLE = os.getenv("RAG_ENABLE", "1") != "0"
# 启动时预热 RAG（与旧 main.py 一致），避免第一次提问卡很久
RAG_WARMUP_ON_STARTUP = os.getenv("RAG_WARMUP_ON_STARTUP", "1") != "0"

# Runtime
RESET_ON_STARTUP = os.getenv("RESET_ON_STARTUP", "0") == "1"
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "3"))
SESSION_TTL_SEC = int(os.getenv("SESSION_TTL_SEC", str(6 * 3600)))

# Agent harness（Claude Code 风格上下文预算，按字符近似 token）
AGENT_SOFT_CONTEXT_CHARS = int(os.getenv("AGENT_SOFT_CONTEXT_CHARS", "24000"))
AGENT_HARD_CONTEXT_CHARS = int(os.getenv("AGENT_HARD_CONTEXT_CHARS", "40000"))
AGENT_KEEP_RECENT_MESSAGES = int(os.getenv("AGENT_KEEP_RECENT_MESSAGES", "16"))
AGENT_MAX_LOOP_ITERS = int(os.getenv("AGENT_MAX_LOOP_ITERS", "3"))
AGENT_ENABLE_AUTO_MEMORY = os.getenv("AGENT_ENABLE_AUTO_MEMORY", "1") != "0"

STATE_DIR = BASE_DIR / "state"
SESSIONS_DIR = STATE_DIR / "sessions"
# 默认使用原有 webui（不要替换用户现有界面）
WEBUI_DIR = BASE_DIR / "webui"
ALT_WEBUI_DIR = BASE_DIR / "app" / "web"
PDF_PATH = BASE_DIR / "static" / "pdf" / "Tesla_Manual.pdf"
