# -*- coding: utf-8 -*-
"""对照：4B 在 done=false 时会连打；当前循环应在第一次成功后停。"""
from __future__ import annotations

import json

from app.agent.loop import AgentLoop
from app.models import IntentType, PolicyDecision, RiskLevel, RouteResult, ToolCall, ToolResult
from app.tools.registry import ToolRegistry
from tests.mock_llm import MockLLM


class _AllowAll:
    def evaluate(self, calls, vehicle_state):
        return PolicyDecision(allowed=True, require_confirm=False, risk=RiskLevel.LOW)


class _GW:
    def snapshot(self):
        return {"dynamics": {"speed_kmh": 0, "gear": "P"}}


class SequenceLLM:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def chat(self, *_args, **_kwargs) -> str:
        i = min(self.calls, len(self.payloads) - 1)
        self.calls += 1
        return json.dumps(self.payloads[i], ensure_ascii=False)


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _run(query, route, payloads, execute):
    llm = SequenceLLM(payloads)
    loop = AgentLoop(ToolRegistry(), _AllowAll(), max_iterations=5)
    executed = []

    def wrapped(call: ToolCall) -> ToolResult:
        executed.append({"name": call.name, "arguments": dict(call.arguments or {})})
        return execute(call)

    result = _drain(
        loop.run_tools(
            query=query,
            llm=llm,
            gateway=_GW(),
            vehicle_state={},
            memory_hint="",
            initial_route=route,
            execute=wrapped,
        )
    )
    return executed, llm.calls, result.iterations


def main():
    vol_payloads = [
        {
            "intent": "tool",
            "done": False,
            "tool_calls": [{"name": "media.set_volume", "arguments": {"volume": v}}],
        }
        for v in (35, 30, 25, 20, 15)
    ]
    cases = [
        (
            "减少音量（4B 会 40→35→30…）",
            "我希望减少音量",
            RouteResult(
                intent=IntentType.TOOL,
                done=False,
                tool_calls=[ToolCall(name="media.set_volume", arguments={"volume": 40})],
            ),
            vol_payloads,
            lambda c: ToolResult(success=True, message="ok", tool=c.name),
        ),
        (
            "设温度 21（4B 同参连打）",
            "把温度调到21度",
            RouteResult(
                intent=IntentType.TOOL,
                done=False,
                tool_calls=[
                    ToolCall(
                        name="climate.set_temperature",
                        arguments={"temperature": 21, "zones": ["front_left"]},
                    )
                ],
            ),
            [
                {
                    "intent": "tool",
                    "done": False,
                    "tool_calls": [
                        {
                            "name": "climate.set_temperature",
                            "arguments": {"temperature": 21, "zones": ["front_left"]},
                        }
                    ],
                }
            ]
            * 5,
            lambda c: ToolResult(success=True, message="ok", tool=c.name),
        ),
        (
            "同步音量+温度",
            "音量调小并把温度调到21度",
            RouteResult(
                intent=IntentType.MULTI_TOOL,
                done=False,
                tool_calls=[
                    ToolCall(name="media.set_volume", arguments={"volume": 30}),
                    ToolCall(name="climate.set_temperature", arguments={"temperature": 21}),
                ],
            ),
            [{"intent": "done", "done": True, "tool_calls": []}],
            lambda c: ToolResult(success=True, message="ok", tool=c.name),
        ),
        (
            "搜附近咖啡（应再规划一次）",
            "附近有咖啡吗",
            RouteResult(
                intent=IntentType.TOOL,
                done=False,
                tool_calls=[ToolCall(name="maps.search_nearby", arguments={"keywords": "咖啡"})],
            ),
            [{"intent": "done", "done": True, "reason": "等人选", "tool_calls": []}],
            lambda c: ToolResult(
                success=True,
                message="附近有3家",
                tool=c.name,
                data={"pois": [{"name": "星巴克(国贸)", "distance": 120}]},
            ),
        ),
    ]
    print(f"{'场景':<28} {'执行次数':>8} {'再规划':>8} {'迭代':>6}  工具")
    print("-" * 80)
    for title, query, route, payloads, execute in cases:
        executed, llm_calls, iters = _run(query, route, payloads, execute)
        tools = ",".join(
            f"{x['name']}{x['arguments']}" for x in executed
        )
        print(f"{title:<28} {len(executed):>8} {llm_calls:>8} {iters:>6}  {tools}")


if __name__ == "__main__":
    main()
