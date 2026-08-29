# -*- coding: utf-8 -*-
"""共享数据模型。"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    KNOWLEDGE = "knowledge"
    TOOL = "tool"
    MULTI_TOOL = "multi_tool"
    SEARCH = "search"
    CHAT = "chat"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Zone(str, Enum):
    FRONT_LEFT = "front_left"
    FRONT_RIGHT = "front_right"
    REAR_LEFT = "rear_left"
    REAR_RIGHT = "rear_right"
    REAR_MIDDLE = "rear_middle"


ALL_ZONES = [z.value for z in Zone]
FRONT_ZONES = [Zone.FRONT_LEFT.value, Zone.FRONT_RIGHT.value]
REAR_ZONES = [Zone.REAR_LEFT.value, Zone.REAR_MIDDLE.value, Zone.REAR_RIGHT.value]
WINDOW_POSITIONS = [
    Zone.FRONT_LEFT.value,
    Zone.FRONT_RIGHT.value,
    Zone.REAR_LEFT.value,
    Zone.REAR_RIGHT.value,
]


class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ProfileUpdatePlan(BaseModel):
    """首轮语义判断：本轮有没有长期信息可记。三个篮子只是分类，不是字段清单。"""

    persona: bool = False
    memory: bool = False
    preferences: bool = False
    clear_persona: bool = False
    clear_memory: bool = False
    clear_preferences: bool = False

    @classmethod
    def from_nlu_dict(cls, raw: Any) -> "ProfileUpdatePlan":
        if not isinstance(raw, dict):
            return cls()
        clear = raw.get("clear") if isinstance(raw.get("clear"), dict) else {}
        return cls(
            persona=bool(raw.get("persona")),
            memory=bool(raw.get("memory")),
            preferences=bool(raw.get("preferences")),
            clear_persona=bool(clear.get("persona")),
            clear_memory=bool(clear.get("memory")),
            clear_preferences=bool(clear.get("preferences")),
        )

    def needs_work(self) -> bool:
        return any(
            (
                self.persona,
                self.memory,
                self.preferences,
                self.clear_persona,
                self.clear_memory,
                self.clear_preferences,
            )
        )

    def to_triage_dict(self) -> Dict[str, Any]:
        return {
            "persona": self.persona,
            "memory": self.memory,
            "preferences": self.preferences,
            "clear": {
                "persona": self.clear_persona,
                "memory": self.clear_memory,
                "preferences": self.clear_preferences,
            },
            "source": "intent_first_pass",
        }


class RouteResult(BaseModel):
    intent: IntentType
    confidence: float = 0.5
    reason: str = ""
    tool_calls: List[ToolCall] = Field(default_factory=list)
    needs_llm_plan: bool = False
    # 本步执行完后，用户整句请求是否已处理完（需等用户选点 / 还有后续能力时为 False）
    done: bool = True
    # 仅首轮 StructuredNLU（step_index=1）填充；Agent Loop 后续步不覆盖
    profile_update: ProfileUpdatePlan = Field(default_factory=ProfileUpdatePlan)


class PolicyDecision(BaseModel):
    allowed: bool = True
    require_confirm: bool = False
    risk: RiskLevel = RiskLevel.LOW
    message: str = ""
    blocked_reason: str = ""
    # safety=车控高风险；privacy=读消息等隐私确认（非车辆安全）
    confirm_kind: str = "safety"


class PendingAction(BaseModel):
    tool_calls: List[ToolCall]
    summary: str
    risk: RiskLevel = RiskLevel.HIGH
    confirm_kind: str = "safety"
    message: str = ""


class ToolResult(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    tool: str = ""


class ChatRequest(BaseModel):
    query: str
    session_id: str = "default"
    model: str = "remote"  # remote | local
    confirm: Optional[bool] = None  # True/False 用于确认门控
    active_seat: Optional[str] = None  # front_left / front_right / ...


class ControlRequest(BaseModel):
    """中控屏直接控车（绕过对话，写 canonical state）。"""
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    session_id: str = "default"


class ModelStatus(BaseModel):
    remote_available: bool
    local_available: bool
    local_model_name: str
    runtime_version: str = "2.1.0-agent"
