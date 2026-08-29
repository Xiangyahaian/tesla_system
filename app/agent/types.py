# -*- coding: utf-8 -*-
"""Agent 消息与会话元数据（transcript）。"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    COMPACTION = "compaction"


class TranscriptMessage(BaseModel):
    role: MessageRole
    content: str
    ts: float = 0.0
    meta: Dict[str, Any] = Field(default_factory=dict)

    def approx_chars(self) -> int:
        return len(self.content or "") + len(json_dumps_meta(self.meta))


def json_dumps_meta(meta: Dict[str, Any]) -> str:
    try:
        import json

        return json.dumps(meta, ensure_ascii=False)
    except Exception:
        return str(meta)


class CompactReport(BaseModel):
    layers: List[str] = Field(default_factory=list)
    before_chars: int = 0
    after_chars: int = 0
    summary: str = ""
    thrash_count: int = 0


class ContextBundle(BaseModel):
    """一次模型调用前组装好的上下文。"""
    system: str
    user_context: str  # persona / memories / preferences / vehicle / compact summary
    recent_dialog: str
    total_chars: int = 0
    sources: List[str] = Field(default_factory=list)
