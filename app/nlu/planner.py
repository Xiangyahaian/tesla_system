# -*- coding: utf-8 -*-
"""结构化 NLU：用 LLM 做意图分类 + 工具规划（不用关键词分类）。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from app.llm.client import LLMClient
from app.models import IntentType, RouteResult, ToolCall
from app.tools.registry import ToolRegistry, get_registry


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


INTENT_SYSTEM = """你是 Tesla 车载语音系统的意图与工具规划器。
不要用关键词死板匹配，要理解用户语义；必须结合「历史摘要」消解指代。

## 意图定义（必须严格区分）

1) search —— 查询**本车当前状态**（读实时 state）
   - 问现在播什么、音量多少、空调开了没、温度多少、座椅加热开了没/怎么样、车窗开了多少
   - 典型：「我现在座椅加热是怎么样的」「音量多少」「空调开了吗」

2) tool —— 执行**一个**车控/媒体/导航等操作
   - 「打开空调」「打开座椅加热」「音量小一点」
   - 指代补全：历史在谈座椅加热，用户说「帮我打开吧」「开一下」「那就开着」→ tool（seat.set），不要 chat

3) multi_tool —— **多个不同类型**操作（最多3个）

4) knowledge —— 问**手册知识/用法/原理**（查文档）
   - 「座椅加热怎么用」若问操作方法 → knowledge；「打开座椅加热」→ tool；「现在座椅加热怎么样」→ search

5) chat —— 纯闲聊问候（与车控/状态/手册无关）
   - 绝不能把含糊但可结合历史推断的控车指令判成 chat

## 关键易错点
- 「我现在座椅加热是怎么样的」→ search（不是 chat）
- 历史提到座椅加热 + 「帮我打开吧」→ tool: seat.set(feature=heat, enable=true)
- 「帮我打开吧」若历史无法推断对象 → chat，并应在 reason 说明需追问（tool_calls=[]）
- 闲聊禁止伪装成已控车；控车必须走 tool

## 工具
只能使用下面列出的工具名与参数；相对调节用 adjust_* 工具。
同一功能多位置仍是 tool（zones/positions 数组），不要拆成 multi_tool。
座椅加热: seat.set，arguments 示例 {{"feature":"heat","enable":true,"level":2,"positions":["front_left"]}}

{catalog}

## 输出（只返回JSON）
{{
  "intent": "search|tool|multi_tool|knowledge|chat",
  "confidence": 0.0到1.0,
  "reason": "简短原因",
  "tool_calls": [
    {{"name": "seat.set", "arguments": {{"feature": "heat", "enable": true, "level": 2}}, "reason": "..."}}
  ]
}}
search/knowledge/chat 时 tool_calls 必须为 []。
"""


class StructuredNLU:
    def __init__(self, llm: LLMClient, registry: ToolRegistry | None = None):
        self.llm = llm
        self.registry = registry or get_registry()

    def plan(self, query: str, vehicle_state: dict, memory_hint: str = "") -> RouteResult:
        catalog = self.registry.prompt_catalog()
        seats = vehicle_state.get("seats", {})
        slim = {
            "dynamics": vehicle_state.get("dynamics"),
            "climate": {
                "power": vehicle_state.get("climate", {}).get("power"),
                "front_left": vehicle_state.get("climate", {}).get("zones", {}).get("front_left"),
            },
            "media": vehicle_state.get("media"),
            "seats": {
                "heat_front_left": (seats.get("heat") or {}).get("front_left"),
                "steering_wheel_heat": seats.get("steering_wheel_heat"),
            },
            "cabin": {
                "windows_front_left": vehicle_state.get("cabin", {}).get("windows", {}).get("front_left"),
                "doors_front_left": vehicle_state.get("cabin", {}).get("doors", {}).get("front_left"),
            },
            "navigation": vehicle_state.get("navigation"),
        }
        system = INTENT_SYSTEM.format(catalog=catalog)
        user = (
            f"当前车况摘要:\n{json.dumps(slim, ensure_ascii=False)}\n\n"
            f"历史摘要（用于消解「打开吧/关了吧」等指代）:\n{memory_hint or '无'}\n\n"
            f"用户输入: {query}\n"
            f"请结合历史理解语义后分类；能推断控车对象就走 tool，问当前状态就走 search。"
        )
        try:
            raw = self.llm.chat(system, user, temperature=0.0)
            data = _extract_json(raw)
        except Exception as e:
            return RouteResult(intent=IntentType.CHAT, confidence=0.2, reason=f"NLU失败:{e}")

        intent_str = str(data.get("intent", "chat")).lower().strip()
        intent_map = {
            "knowledge": IntentType.KNOWLEDGE,
            "tool": IntentType.TOOL,
            "multi_tool": IntentType.MULTI_TOOL,
            "search": IntentType.SEARCH,
            "chat": IntentType.CHAT,
        }
        intent = intent_map.get(intent_str, IntentType.CHAT)

        calls: List[ToolCall] = []
        if intent in {IntentType.TOOL, IntentType.MULTI_TOOL}:
            for item in data.get("tool_calls") or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if not name or not self.registry.get(name):
                    continue
                calls.append(
                    ToolCall(
                        name=name,
                        arguments=item.get("arguments") or {},
                        reason=item.get("reason") or "",
                    )
                )
                if len(calls) >= 3:
                    break
            if not calls:
                intent = IntentType.CHAT
            elif len(calls) > 1:
                intent = IntentType.MULTI_TOOL
            else:
                intent = IntentType.TOOL
        else:
            calls = []

        return RouteResult(
            intent=intent,
            confidence=float(data.get("confidence", 0.7) or 0.7),
            reason=str(data.get("reason", "llm-semantic")),
            tool_calls=calls,
        )
