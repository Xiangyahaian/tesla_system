# -*- coding: utf-8 -*-
"""Agentic loop：gather → act → verify（Claude Code 风格）。

车载场景下工具集是封闭的 Vehicle Tools；循环用于：
- 权限门控后执行
- 失败时带着 tool 结果再规划（有限次）
- 把每步写入 transcript
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Generator, List, Optional

from app import config
from app.agent.types import MessageRole
from app.llm.client import LLMClient
from app.models import IntentType, PendingAction, RouteResult, ToolCall, ToolResult
from app.nlu.planner import StructuredNLU
from app.policy.engine import PolicyEngine
from app.tools.registry import ToolRegistry


@dataclass
class LoopEvent:
    type: str  # log | token | confirm | final_tools | blocked
    data: object = None


@dataclass
class LoopResult:
    route: Optional[RouteResult] = None
    results: List[ToolResult] = field(default_factory=list)
    pending: Optional[PendingAction] = None
    blocked_message: str = ""
    iterations: int = 0
    llm_calls: int = 0


class AgentLoop:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        max_iterations: int = 3,
    ):
        self.registry = registry
        self.policy = policy
        self.max_iterations = max_iterations

    def run_tools(
        self,
        *,
        query: str,
        llm: LLMClient,
        gateway,
        vehicle_state: dict,
        memory_hint: str,
        initial_route: Optional[RouteResult] = None,
        execute: Optional[Callable[[ToolCall], ToolResult]] = None,
        on_persist_pending: Optional[Callable[[PendingAction], None]] = None,
    ) -> Generator[LoopEvent, None, LoopResult]:
        """工具向 agent loop。initial_route 可来自外层已完成的 NLU。"""
        result = LoopResult()
        nlu = StructuredNLU(llm, self.registry)
        route = initial_route
        exec_fn = execute or (lambda c: self.registry.execute(gateway, c))
        feedback = ""

        for i in range(1, self.max_iterations + 1):
            result.iterations = i
            yield LoopEvent("log", f"agent_loop 迭代 {i}/{self.max_iterations}")

            if route is None or (feedback and i > 1):
                hint = memory_hint
                if feedback:
                    hint = f"{memory_hint}\n上次工具反馈:{feedback}"
                yield LoopEvent("log", "gather: StructuredNLU 规划")
                route = nlu.plan(query if not feedback else f"{query}\n(纠正/重试依据:{feedback})", vehicle_state, hint)
                result.llm_calls += 1
                result.route = route
                if route.intent not in {IntentType.TOOL, IntentType.MULTI_TOOL} or not route.tool_calls:
                    yield LoopEvent("log", f"loop 退出：意图={route.intent.value}")
                    return result

            result.route = route
            calls = route.tool_calls[: config.MAX_TOOL_CALLS]
            yield LoopEvent(
                "log",
                "act: " + ", ".join(f"{c.name}{json.dumps(c.arguments, ensure_ascii=False)}" for c in calls),
            )

            decision = self.policy.evaluate(calls, vehicle_state)
            yield LoopEvent(
                "log",
                f"permission: allowed={decision.allowed} confirm={decision.require_confirm} risk={decision.risk.value}",
            )
            if not decision.allowed:
                result.blocked_message = decision.message or decision.blocked_reason
                yield LoopEvent("blocked", decision.model_dump())
                return result

            if decision.require_confirm:
                summary = "；".join(
                    f"{c.name}({json.dumps(c.arguments, ensure_ascii=False)})" for c in calls
                )
                pending = PendingAction(tool_calls=calls, summary=summary, risk=decision.risk)
                result.pending = pending
                if on_persist_pending:
                    on_persist_pending(pending)
                yield LoopEvent(
                    "confirm",
                    {
                        "message": decision.message or "该操作涉及车辆安全，请确认后执行。",
                        "summary": summary,
                        "risk": decision.risk.value,
                        "tool_calls": [c.model_dump() for c in calls],
                    },
                )
                return result

            results: List[ToolResult] = []
            for call in calls:
                tr = exec_fn(call)
                results.append(tr)
                yield LoopEvent(
                    "log",
                    f"tool_result: {call.name} → {'OK' if tr.success else 'FAIL'} {tr.message}",
                )

            result.results = results
            # verify
            if all(r.success for r in results):
                yield LoopEvent("final_tools", [r.model_dump() for r in results])
                return result

            feedback = "；".join(f"{r.tool or '?'}:{r.message}" for r in results)
            route = None  # 触发下一轮重规划
            yield LoopEvent("log", "verify: 存在失败，准备重规划")

        yield LoopEvent("log", "loop 达到最大迭代，停止")
        return result
