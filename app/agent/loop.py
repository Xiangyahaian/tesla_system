# -*- coding: utf-8 -*-
"""Agentic loop：逐步 gather → act → observe → 再规划。

- 每步 tool_calls：无依赖可并行执行
- 有依赖：本步 done=false，观察后再规划
- 取消「整句工具一次性并行打完」
- 失败可纠参重规划；同工具校验失败限次，避免空转烧满迭代
- 已成功且无后续依赖（如设温度）即使模型 done=false 也结束，禁止同参连打
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Generator, List, Optional, Tuple

from app import config
from app.llm.client import LLMClient
from app.models import IntentType, PendingAction, ProfileUpdatePlan, RouteResult, ToolCall, ToolResult
from app.nlu.destination_guard import (
    is_relative_or_category_destination,
    relative_destination_block_message,
)
from app.nlu.react_guard import (
    FOLLOWUP_TOOLS,
    coerce_step_done,
    is_followup_tool,
    should_continue_after_success,
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
    profile_update: ProfileUpdatePlan = field(default_factory=ProfileUpdatePlan)


def _is_validation_fail(r: ToolResult) -> bool:
    return (not r.success) and isinstance(r.data, dict) and r.data.get("error_kind") == "validation"


def _call_fingerprint(c: ToolCall) -> str:
    try:
        args = json.dumps(c.arguments or {}, sort_keys=True, ensure_ascii=False)
    except Exception:
        args = str(c.arguments)
    return f"{c.name}::{args}"


def _same_bad_args(a: ToolCall, b: ToolCall) -> bool:
    return _call_fingerprint(a) == _call_fingerprint(b)


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
        if initial_route is not None:
            result.profile_update = initial_route.profile_update
        exec_fn = execute or (lambda c: self.registry.execute(gateway, c))
        all_calls: List[ToolCall] = []
        all_results: List[ToolResult] = []
        validation_strikes: Counter[str] = Counter()

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
                if i == 1:
                    result.profile_update = route.profile_update

            result.route = route
            if route.tool_calls:
                route.done = coerce_step_done(route.tool_calls, route.done)

            if route.intent not in {IntentType.TOOL, IntentType.MULTI_TOOL} or not route.tool_calls:
                if all_results:
                    result.residual_route = route
                    result.results = all_results
                    # 若只剩失败结果，提示上层口语说明，避免像「卡住要重置」
                    if all_results and not any(r.success for r in all_results):
                        result.await_user = True
                    yield LoopEvent("log", f"工具阶段结束，后续意图={route.intent.value}")
                    yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                    return result
                yield LoopEvent("log", f"loop 退出：意图={route.intent.value}")
                return result

            raw_calls = sanitize_tool_calls(
                list(route.tool_calls)[: config.MAX_TOOL_CALLS],
                query,
            )
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
                            data={
                                "blocked_relative_destination": True,
                                "destination": dest,
                                "retryable": True,
                                "error_kind": "relative_destination",
                                "correction_hint": "不要再用相对/类别 destination 调 navigate；改为 maps.search_nearby 后再选具体店名导航",
                            },
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
            success_keys = {
                _call_fingerprint(c) for c, r in result.call_trace if r.success
            }
            succeeded_names = {c.name for c, r in result.call_trace if r.success}
            if calls and (success_keys or succeeded_names):
                novel = []
                dropped = 0
                for c in calls:
                    if _call_fingerprint(c) in success_keys:
                        dropped += 1
                        continue
                    # 调小音量：4B 会 40→35→30 同工具换参连打，也要丢掉
                    if not is_followup_tool(c.name) and c.name in succeeded_names:
                        dropped += 1
                        continue
                    novel.append(c)
                if dropped:
                    yield LoopEvent(
                        "log",
                        f"verify: 丢弃 {dropped} 个已成功工具（同参或同执行器），避免空转",
                    )
                calls = novel
            route.tool_calls = calls
            route.done = coerce_step_done(calls, route.done)
            result.route = route

            if not calls and not step_results:
                result.results = all_results
                if all_results:
                    yield LoopEvent("log", "verify: 规划结果均已成功执行过，结束工具循环")
                    yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                return result

            if calls:
                yield LoopEvent(
                    "log",
                    "act: "
                    + ", ".join(f"{c.name}{json.dumps(c.arguments, ensure_ascii=False)}" for c in calls),
                )

                # 同工具同参校验失败已超过限额 → 不再执行，改问用户
                skip_repeat = False
                for c in calls:
                    if validation_strikes[c.name] >= 2:
                        # 看最近一次是否同参
                        for prev_c, prev_r in reversed(result.call_trace):
                            if prev_c.name == c.name and _is_validation_fail(prev_r) and _same_bad_args(prev_c, c):
                                skip_repeat = True
                                break
                        if skip_repeat:
                            break
                if skip_repeat:
                    result.await_user = True
                    result.results = all_results
                    yield LoopEvent("log", "verify: 同参校验连续失败，停止空转，交还用户")
                    yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                    return result

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

                # 同一步内遇失败即停后续，避免半完成后再叠副作用
                for call in calls:
                    tr = exec_fn(call)
                    step_calls.append(call)
                    step_results.append(tr)
                    yield LoopEvent(
                        "log",
                        f"tool_result: {call.name} → {'OK' if tr.success else 'FAIL'} {tr.message}",
                    )
                    if _is_validation_fail(tr):
                        validation_strikes[call.name] += 1
                    if not tr.success:
                        yield LoopEvent("log", "verify: 本步遇失败，跳过同批后续工具")
                        break

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

            exec_ok = [
                r
                for r in step_results
                if not (isinstance(r.data, dict) and r.data.get("blocked_relative_destination"))
            ]

            if any(isinstance(r.data, dict) and r.data.get("need_clarify") for r in step_results if r.success):
                result.await_user = True
                yield LoopEvent("log", "verify: 目的地待用户确认，结束工具循环")
                yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                return result

            # 周边检索成功且 done=false → 继续下一步（读 POI 后决定导航/询问）
            # done=true → 结束本轮工具，由回复层基于过程资料组织口语（不念原文）
            if exec_ok and not all(r.success for r in exec_ok):
                # 不可重试失败：直接交还用户，避免烧满迭代
                hard = [
                    r
                    for r in exec_ok
                    if (not r.success)
                    and isinstance(r.data, dict)
                    and r.data.get("retryable") is False
                ]
                if hard:
                    result.await_user = True
                    yield LoopEvent("log", "verify: 不可重试失败，结束并交还用户")
                    yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                    return result
                route = None
                yield LoopEvent("log", "verify: 存在失败，准备纠参/换策略重规划")
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

            if exec_ok and all(r.success for r in exec_ok) and not should_continue_after_success(
                step_calls, route.done
            ):
                yield LoopEvent("log", "verify: 本步已成功且无需后续依赖，结束工具循环")
                yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
                return result

            try:
                vehicle_state = gateway.snapshot()
            except Exception:
                yield LoopEvent("log", "warn: snapshot 失败，沿用上一帧车况")
            route = None
            yield LoopEvent("log", "verify: done=false，继续下一步（读观察再决策）")

        result.results = all_results
        result.await_user = True
        yield LoopEvent("log", "loop 达到最大迭代，停止并交还用户（会话保持，无需重置）")
        yield LoopEvent("final_tools", [r.model_dump() for r in all_results])
        return result
