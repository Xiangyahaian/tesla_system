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

# Speech（百炼：千问 ASR + CosyVoice TTS）
ASR_MODEL = os.getenv("ASR_MODEL", "qwen3-asr-flash")
TTS_MODEL = os.getenv("TTS_MODEL", "cosyvoice-v3-flash")
# 龙安欢：欢脱元气女，支持情感 Instruct
TTS_VOICE = os.getenv("TTS_VOICE", "longanhuan")
TTS_RATE = float(os.getenv("TTS_RATE", "1.12"))

# 高德地图（MCP / Web 服务共用 Key；JS Key 可与之相同或单独申请）
AMAP_MAPS_API_KEY = os.getenv("AMAP_MAPS_API_KEY", "") or os.getenv("AMAP_KEY", "")
AMAP_JS_KEY = os.getenv("AMAP_JS_KEY", "") or AMAP_MAPS_API_KEY
AMAP_JS_SECURITY_CODE = os.getenv("AMAP_JS_SECURITY_CODE", "")  # 可选：安全密钥

# 网页搜索（web.search）。auto：百炼联网（已有 BAILIAN_API_KEY）> Tavily/博查/Brave > Bing HTML
WEB_SEARCH_PROVIDER = (os.getenv("WEB_SEARCH_PROVIDER", "auto") or "auto").strip().lower()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "") or os.getenv("BOCHAAI_API_KEY", "")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
WEB_SEARCH_TIMEOUT_SEC = float(os.getenv("WEB_SEARCH_TIMEOUT_SEC", "8"))
# 百炼官方联网搜索用文本模型（不要用 qwen3.5-flash，那是多模态接口）
WEB_SEARCH_DASHSCOPE_MODEL = (os.getenv("WEB_SEARCH_DASHSCOPE_MODEL", "qwen-flash") or "qwen-flash").strip()
WEB_SEARCH_DASHSCOPE_TIMEOUT_SEC = float(os.getenv("WEB_SEARCH_DASHSCOPE_TIMEOUT_SEC", "25"))


# RAG
RAG_BM25_TOPK = int(os.getenv("RAG_BM25_TOPK", "8"))
RAG_MILVUS_TOPK = int(os.getenv("RAG_MILVUS_TOPK", "8"))
RAG_RERANK_TOPK = int(os.getenv("RAG_RERANK_TOPK", "4"))
RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.15"))
RAG_ENABLE = os.getenv("RAG_ENABLE", "1") != "0"
# 启动时预热 RAG，避免第一次提问卡很久
RAG_WARMUP_ON_STARTUP = os.getenv("RAG_WARMUP_ON_STARTUP", "1") != "0"

# Runtime
RESET_ON_STARTUP = os.getenv("RESET_ON_STARTUP", "0") == "1"
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "3"))
SESSION_TTL_SEC = int(os.getenv("SESSION_TTL_SEC", str(6 * 3600)))

# Agent 上下文预算（按字符近似 token）
AGENT_SOFT_CONTEXT_CHARS = int(os.getenv("AGENT_SOFT_CONTEXT_CHARS", "24000"))
AGENT_HARD_CONTEXT_CHARS = int(os.getenv("AGENT_HARD_CONTEXT_CHARS", "40000"))
# 压缩后模型可见的最近对话轮数（一轮 = 一条 user 及其后续 assistant/tool）
AGENT_KEEP_RECENT_TURNS = int(os.getenv("AGENT_KEEP_RECENT_TURNS", "5"))
# 兼容旧名：按约 2 条消息/轮折算
AGENT_KEEP_RECENT_MESSAGES = int(
    os.getenv("AGENT_KEEP_RECENT_MESSAGES", str(AGENT_KEEP_RECENT_TURNS * 2))
)
AGENT_MAX_LOOP_ITERS = int(os.getenv("AGENT_MAX_LOOP_ITERS", "5"))
AGENT_ENABLE_AUTO_MEMORY = os.getenv("AGENT_ENABLE_AUTO_MEMORY", "1") != "0"

STATE_DIR = BASE_DIR / "state"
SESSIONS_DIR = STATE_DIR / "sessions"
# 每次大模型输入输出：独立 JSON，与会话目录无关
LLM_LOG_DIR = Path(os.getenv("LLM_LOG_DIR", str(BASE_DIR / "log")))
LLM_LOG_ENABLE = os.getenv("LLM_LOG_ENABLE", "1") != "0"
SESSION_DB_PATH = Path(os.getenv("SESSION_DB_PATH", str(STATE_DIR / "cabin_sessions.db")))
ADMIN_NICKNAME = (os.getenv("ADMIN_NICKNAME", "象牙海岸") or "象牙海岸").strip()
# 默认使用用户原有 webui（不要替换用户现有界面）
WEBUI_DIR = BASE_DIR / "webui"
ALT_WEBUI_DIR = BASE_DIR / "app" / "web"
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
# 有构建产物时优先托管 React 座舱 HMI
PREFER_CABIN_HMI = os.getenv("PREFER_CABIN_HMI", "1") != "0"
PDF_PATH = BASE_DIR / "static" / "pdf" / "Tesla_Manual.pdf"
