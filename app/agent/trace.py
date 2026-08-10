# -*- coding: utf-8 -*-
"""规范 Agent 轨迹：每轮 Turn + 有序 Step，持久化 JSONL，可供 UI/API 查询。"""
from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepType(str, Enum):
    SESSION = "session"
    COMPACT = "compact"
    CONTEXT = "context"
    INTENT = "intent"
    POLICY = "policy"
    CONFIRM = "confirm"
    LOOP = "loop"
    TOOL = "tool"
    SEARCH = "search"
    KNOWLEDGE = "knowledge"
    CHAT = "chat"
    MEMORY = "memory"
    RESPONSE = "response"
    ERROR = "error"
    STATUS = "status"


class TraceStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    ts: float = Field(default_factory=time.time)
    type: StepType
    title: str
    detail: Dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"  # ok | warn | error | running


class TurnTrace(BaseModel):
    turn_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str
    query: str
    model: str = "remote"
    started_at: float = Field(default_factory=time.time)
    ended_at: Optional[float] = None
    intent: str = ""
    status: str = "running"  # running | ok | error | cancelled | need_confirm | blocked
    steps: List[TraceStep] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    answer_preview: str = ""
    tool_names: List[str] = Field(default_factory=list)

    def add(
        self,
        step_type: StepType | str,
        title: str,
        detail: Optional[Dict[str, Any]] = None,
        status: str = "ok",
    ) -> TraceStep:
        step = TraceStep(
            type=StepType(step_type) if not isinstance(step_type, StepType) else step_type,
            title=title,
            detail=detail or {},
            status=status,
        )
        self.steps.append(step)
        return step

    def finish(
        self,
        status: str = "ok",
        intent: str = "",
        metrics: Optional[Dict[str, Any]] = None,
        answer_preview: str = "",
        tool_names: Optional[List[str]] = None,
    ) -> None:
        self.ended_at = time.time()
        self.status = status
        if intent:
            self.intent = intent
        if metrics:
            self.metrics = metrics
        if answer_preview:
            self.answer_preview = answer_preview[:300]
        if tool_names is not None:
            self.tool_names = tool_names

    def summary(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "query": self.query,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": int(((self.ended_at or time.time()) - self.started_at) * 1000),
            "intent": self.intent,
            "status": self.status,
            "step_count": len(self.steps),
            "tool_names": self.tool_names,
            "answer_preview": self.answer_preview,
            "metrics": self.metrics,
        }


class TraceStore:
    """turns.jsonl：每行一个完整 TurnTrace。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def append_turn(self, turn: TurnTrace) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(turn.model_dump_json(ensure_ascii=False) + "\n")

    def list_turns(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        turns = self._load_all()
        turns.reverse()  # 新在前
        slice_ = turns[offset : offset + limit]
        return [t.summary() for t in slice_]

    def get_turn(self, turn_id: str) -> Optional[TurnTrace]:
        for t in reversed(self._load_all()):
            if t.turn_id == turn_id:
                return t
        return None

    def latest(self) -> Optional[TurnTrace]:
        all_t = self._load_all()
        return all_t[-1] if all_t else None

    def _load_all(self) -> List[TurnTrace]:
        if not self.path.exists():
            return []
        out: List[TurnTrace] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(TurnTrace.model_validate_json(line))
            except Exception:
                continue
        return out
