# -*- coding: utf-8 -*-
"""助手口语兜底：原始异常只进轨迹/日志，绝不进对话框或 TTS。"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Union

DEFAULT_SPOKEN = "【听】这步没做成。你可以换个说法再试，或先切到本地模型。"

_RAW_MARKERS = (
    "Error code:",
    "error code:",
    "Traceback (most recent call last)",
    "Arrearage",
    "invalid_request_error",
    "overdue-payment",
    "openai.",
    "httpx.",
    "APIStatusError",
    "APIConnectionError",
    "BadRequestError",
    "RateLimitError",
    "AuthenticationError",
    "request_id",
    "{'error'",
    '{"error"',
    "TAVILY_API_KEY",
    "BOCHA_API_KEY",
    "BAILIAN_API_KEY",
    "BRAVE_API_KEY",
    "DASHSCOPE_API_KEY",
    "Access denied, please make sure your account",
)

_RAW_RE = re.compile(
    r"(Error code:\s*\d+"
    r"|Traceback \(most recent call last\)"
    r"|File \"[^\"]+\", line \d+"
    r"|openai\.\w+Error"
    r"|httpx\.\w+"
    r"|\b[A-Z][A-Za-z]+(?:Error|Exception|Timeout|Refused)\s*\("
    r"|ConnectTimeout|ReadTimeout|ConnectError)",
    re.I,
)


def looks_like_raw_error(text: str) -> bool:
    t = text or ""
    if not t.strip():
        return False
    if any(m in t for m in _RAW_MARKERS):
        return True
    return bool(_RAW_RE.search(t))


def sanitize_spoken(text: str, *, fallback: Optional[str] = None) -> str:
    """用户可见口语：一旦夹带堆栈/接口原文，整句换成兜底。"""
    t = (text or "").strip()
    fb = (fallback if fallback is not None else DEFAULT_SPOKEN).strip()
    if not t:
        return fb
    if looks_like_raw_error(t):
        return fb or DEFAULT_SPOKEN
    return t


def classify_and_speak(
    exc: Union[BaseException, str],
    *,
    mode: str = "remote",
    fact: str = "",
) -> Dict[str, str]:
    from app.llm.client import classify_llm_error, compose_llm_fail_reply

    info = classify_llm_error(exc, mode=mode if mode in {"remote", "local"} else "remote")
    spoken = compose_llm_fail_reply(info, fact=fact)
    info = dict(info)
    info["spoken"] = sanitize_spoken(spoken, fallback=DEFAULT_SPOKEN)
    return info


def public_error_text(exc: Union[BaseException, str], *, mode: str = "remote") -> str:
    """给前端状态条 / SSE error 事件：短人话，不含原文。"""
    info = classify_and_speak(exc, mode=mode)
    return (info.get("spoken") or DEFAULT_SPOKEN).replace("【听】", "").strip()


def error_trace_detail(exc: Union[BaseException, str], *, mode: str = "remote") -> Dict[str, Any]:
    from app.llm.client import classify_llm_error

    return dict(classify_llm_error(exc, mode=mode if mode in {"remote", "local"} else "remote"))
