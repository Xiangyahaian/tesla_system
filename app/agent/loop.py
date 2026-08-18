# -*- coding: utf-8 -*-
"""Agentic loop：逐步 gather → act → observe → 再规划。

- 每步 tool_calls：无依赖可并行执行
- 有依赖：本步 done=false，观察后再规划
- 取消「整句工具一次性并行打完」
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Generator, List, Optional, Tuple

from app import config
from app.llm.client import LLMClient
from app.models import IntentType, PendingAction, RouteResult, ToolCall, ToolResult
from app.nlu.destination_guard import (
    is_relative_or_category_destination,
    relative_destination_block_message,
)
from app.nlu.planner import StructuredNLU, sanitize_tool_calls
from app.policy.engine import PolicyEngine
from app.tools.registry import ToolRegistry


@dataclass
class LoopEvent:
    type: str  # log | confirm | final_tools | blocked | step
    data: object = None


@dataclass
class LoopStep:
    calls: List[ToolCall]
    results: List[ToolResult]


@dataclass
class LoopResult:
    route: Optional[RouteResult] = None
    results: List[ToolResult] = field(default_factory=list)
    steps: List[LoopStep] = field(default_factory=list)
    call_trace: List[Tuple[ToolCall, ToolResult]] = field(default_factory=list)
    pending: Optional[PendingAction] = None
    blocked_message: str = ""
    iterations: int = 0
    llm_calls: int = 0
    residual_route: Optional[RouteResult] = None
    await_user: bool = False


class AgentLoop:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        max_iterations: int = 5,
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
        active_seat: str = "front_left",
    ) -> Generator[LoopEvent, None, LoopResult]:
        result = LoopResult()
        nlu = StructuredNLU(llm, self.registry)
        route = initial_route
        exec_fn = execute or (lambda c: self.registry.execute(gateway, c))
        all_calls: List[ToolCall] = []
        all_results: List[ToolResult] = []

        for i in range(1, self.max_iterations + 1):
            result.iterations = i
            yield LoopEvent("log", f"agent_loop 第 {i}/{self.max_iterations} 步")

            if route is None:
                yield LoopEvent("log", "gather: StructuredNLU 逐步规划")
                route = nlu.plan(
                    query,
                    vehicle_state,
                    memory_hint,
                    active_seat=active_seat,
                    prior_results=all_results,
                    prior_calls=all_calls,
                    step_index=i,
                )
                result.llm_calls += 1

            result.route = route

            if route.intent not in {IntentType.TOOL, IntentType.MULTI_TOOL} or not route.tool_calls:
                if all_results:
                    result.residual_route = route
                    result.results = all_results
                    yield LoopEvent("log", f"工具阶段结束，后续意图={route.intent.value}")
                    yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                    return result
                yield LoopEvent("log", f"loop 退出：意图={route.intent.value}")
                return result

            raw_calls = sanitize_tool_calls(list(route.tool_calls)[: config.MAX_TOOL_CALLS])
            runnable: List[ToolCall] = []
            step_calls: List[ToolCall] = []
            step_results: List[ToolResult] = []

            for c in raw_calls:
                if c.name in {"navigation.navigate_to", "navigation.start"}:
                    dest = str((c.arguments or {}).get("destination") or "")
                    if is_relative_or_category_destination(dest):
                        blocked = ToolResult(
                            success=False,
                            message=relative_destination_block_message(dest),
                            tool=c.name,
                            data={"blocked_relative_destination": True, "destination": dest},
                        )
                        step_calls.append(c)
                        step_results.append(blocked)
                        yield LoopEvent("log", f"tool_result: {c.name} → FAIL {blocked.message}")
                        continue
                runnable.append(c)

            if step_results and not runnable:
                # 相对导航被挡且无其它工具 → 记入观察后重规划
                result.steps.append(LoopStep(calls=step_calls, results=step_results))
                for c, r in zip(step_calls, step_results):
                    result.call_trace.append((c, r))
                all_calls.extend(step_calls)
                all_results.extend(step_results)
                result.results = all_results
                route = None
                yield LoopEvent("log", "verify: 相对目的地已拦截，准备重规划为周边搜索")
                continue

            calls = runnable
            route.tool_calls = calls
            result.route = route

            if not calls and not step_results:
                result.results = all_results
                yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                return result

            if calls:
                yield LoopEvent(
                    "log",
                    "act: "
                    + ", ".join(f"{c.name}{json.dumps(c.arguments, ensure_ascii=False)}" for c in calls),
                )

                decision = self.policy.evaluate(calls, vehicle_state)
                yield LoopEvent(
                    "log",
                    f"permission: allowed={decision.allowed} confirm={decision.require_confirm} risk={decision.risk.value}",
                )
                if not decision.allowed:
                    result.blocked_message = decision.message or decision.blocked_reason
                    result.results = all_results
                    yield LoopEvent("blocked", decision.model_dump())
                    return result

                if decision.require_confirm:
                    summary = "；".join(
                        f"{c.name}({json.dumps(c.arguments, ensure_ascii=False)})" for c in calls
                    )
                    pending = PendingAction(
                        tool_calls=calls,
                        summary=summary,
                        risk=decision.risk,
                        confirm_kind=decision.confirm_kind or "safety",
                        message=decision.message or "",
                    )
                    result.pending = pending
                    result.results = all_results
                    if on_persist_pending:
                        on_persist_pending(pending)
                    yield LoopEvent(
                        "confirm",
                        {
                            "message": decision.message
                            or (
                                "读取消息前需要你确认一下。"
                                if decision.confirm_kind == "privacy"
                                else "该操作涉及车辆安全，请确认后执行。"
                            ),
                            "summary": summary,
                            "risk": decision.risk.value,
                            "confirm_kind": decision.confirm_kind or "safety",
                            "tool_calls": [c.model_dump() for c in calls],
                        },
                    )
                    return result

                for call in calls:
                    tr = exec_fn(call)
                    step_calls.append(call)
                    step_results.append(tr)
                    yield LoopEvent(
                        "log",
                        f"tool_result: {call.name} → {'OK' if tr.success else 'FAIL'} {tr.message}",
                    )

            result.steps.append(LoopStep(calls=list(step_calls), results=list(step_results)))
            for c, r in zip(step_calls, step_results):
                result.call_trace.append((c, r))
            all_calls.extend(step_calls)
            all_results.extend(step_results)
            result.results = all_results

            yield LoopEvent(
                "step",
                {"index": i, "done": route.done, "tools": [c.name for c in step_calls]},
            )

            exec_ok = [r for r in step_results if not (isinstance(r.data, dict) and r.data.get("blocked_relative_destination"))]

            if any(isinstance(r.data, dict) and r.data.get("need_clarify") for r in step_results if r.success):
                result.await_user = True
                yield LoopEvent("log", "verify: 目的地待用户确认，结束工具循环")
                yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                return result

            # 周边检索成功且 done=false → 继续下一步（读 POI 后决定导航/询问）
            # done=true → 结束本轮工具，由回复层基于过程资料组织口语（不念原文）
            if exec_ok and not all(r.success for r in exec_ok):
                route = None
                yield LoopEvent("log", "verify: 存在失败，准备重规划")
                continue

            if route.done:
                if any(
                    (r.tool or "") == "maps.search_nearby"
                    and r.success
                    and isinstance(r.data, dict)
                    and (r.data.get("pois") or [])
                    for r in step_results
                ):
                    result.await_user = True
                yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                return result

            try:
                vehicle_state = gateway.snapshot()
            except Exception:
                pass
            route = None
            yield LoopEvent("log", "verify: done=false，继续下一步（读观察再决策）")

        result.results = all_results
        yield LoopEvent("log", "loop 达到最大迭代，停止")
        yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
        return result
