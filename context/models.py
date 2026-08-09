# -*- coding: utf-8 -*-
"""
意图识别与技能管理的数据模型
"""
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, List


class IntentType(Enum):
    """意图类型枚举"""
    KNOWLEDGE = "knowledge"
    TOOL = "tool"
    MULTI_TOOL = "multi_tool"
    SEARCH = "search"
    CHAT = "chat"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    """意图识别结果"""
    intent: IntentType
    confidence: float
    reason: str
    is_multi: bool = False


@dataclass
class SkillMeta:
    """技能元数据（用于路由）"""
    name: str
    description: str
    functions: List[Dict[str, str]]


@dataclass
class FunctionCall:
    """函数调用定义"""
    skill: str
    script: str
    parameters: Dict[str, Any]
    reason: str
