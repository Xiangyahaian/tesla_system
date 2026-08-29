# -*- coding: utf-8 -*-
"""AgentLoop：控车成功后不得连打；周边检索仍可再规划。"""
from __future__ import annotations

import json
import unittest

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
    """模拟 4B：每次规划都再调低一档音量。"""

    def __init__(self, volumes):
        self.volumes = list(volumes)
        self.calls = 0

    def chat(self, *_args, **_kwargs) -> str:
        vol = self.volumes[min(self.calls, len(self.volumes) - 1)]
        self.calls += 1
        return json.dumps(
            {
                "intent": "tool",
                "done": False,
                "reason": f"再调小到{vol}",
                "tool_calls": [{"name": "media.set_volume", "arguments": {"volume": vol}}],
            },
            ensure_ascii=False,
        )


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _run(loop, query, route, execute, llm=None):
    return _drain(
        loop.run_tools(
            query=query,
            llm=llm or MockLLM({"intent": "done", "done": True, "tool_calls": []}),
            gateway=_GW(),
            vehicle_state={},
            memory_hint="",
            initial_route=route,
            execute=execute,
        )
    )


class TestAgentLoopStopOnSuccess(unittest.TestCase):
    def test_climate_success_does_not_repeat_when_done_false(self):
        loop = AgentLoop(ToolRegistry(), _AllowAll(), max_iterations=5)
        llm = MockLLM(
            {
                "intent": "tool",
                "done": False,
                "reason": "再设一次",
                "tool_calls": [
                    {
                        "name": "climate.set_temperature",
                        "arguments": {"temperature": 21, "zones": ["front_left"]},
                    }
                ],
            }
        )
        executed = []

        def execute(call: ToolCall) -> ToolResult:
            executed.append(dict(call.arguments))
            return ToolResult(success=True, message="主驾温度已设为21°C", tool=call.name)

        route = RouteResult(
            intent=IntentType.TOOL,
            done=False,
            tool_calls=[
                ToolCall(
                    name="climate.set_temperature",
                    arguments={"temperature": 21, "zones": ["front_left"]},
                )
            ],
        )
        result = _run(loop, "把温度调到21度", route, execute, llm)
        self.assertEqual(len(executed), 1)
        self.assertEqual(len(result.results), 1)
        self.assertTrue(result.results[0].success)
        self.assertEqual(llm.calls, 0)

    def test_volume_step_down_stops_after_first(self):
        """用户原话「我希望减少音量」：4B 会 40→35→30→25→20，循环必须只执行第一次。"""
        loop = AgentLoop(ToolRegistry(), _AllowAll(), max_iterations=5)
        llm = SequenceLLM([35, 30, 25, 20, 15])
        executed = []

        def execute(call: ToolCall) -> ToolResult:
            executed.append(int((call.arguments or {}).get("volume")))
            return ToolResult(success=True, message=f"音量已设为{executed[-1]}", tool=call.name)

        route = RouteResult(
            intent=IntentType.TOOL,
            done=False,
            tool_calls=[ToolCall(name="media.set_volume", arguments={"volume": 40})],
        )
        result = _run(loop, "我希望减少音量", route, execute, llm)
        self.assertEqual(executed, [40])
        self.assertEqual(len(result.results), 1)
        self.assertEqual(llm.calls, 0)

    def test_multi_tool_same_step_runs_both(self):
        loop = AgentLoop(ToolRegistry(), _AllowAll(), max_iterations=5)
        executed = []

        def execute(call: ToolCall) -> ToolResult:
            executed.append(call.name)
            return ToolResult(success=True, message="ok", tool=call.name)

        route = RouteResult(
            intent=IntentType.MULTI_TOOL,
            done=False,
            tool_calls=[
                ToolCall(name="media.set_volume", arguments={"volume": 30}),
                ToolCall(name="climate.set_temperature", arguments={"temperature": 21}),
            ],
        )
        result = _run(loop, "音量调小并把温度调到21度", route, execute)
        self.assertEqual(executed, ["media.set_volume", "climate.set_temperature"])
        self.assertEqual(len(result.results), 2)

    def test_search_nearby_can_continue_when_done_false(self):
        loop = AgentLoop(ToolRegistry(), _AllowAll(), max_iterations=5)
        llm = MockLLM(
            {
                "intent": "done",
                "done": True,
                "reason": "已有候选，等人选",
                "tool_calls": [],
            }
        )
        executed = []

        def execute(call: ToolCall) -> ToolResult:
            executed.append(call)
            return ToolResult(
                success=True,
                message="附近有3家",
                tool=call.name,
                data={"pois": [{"name": "星巴克(国贸)", "distance": 120}]},
            )

        route = RouteResult(
            intent=IntentType.TOOL,
            done=False,
            tool_calls=[ToolCall(name="maps.search_nearby", arguments={"keywords": "咖啡"})],
        )
        result = _run(loop, "附近有咖啡吗", route, execute, llm)
        self.assertEqual(len(executed), 1)
        self.assertGreaterEqual(llm.calls, 1)
        self.assertTrue(result.results[0].success)


if __name__ == "__main__":
    unittest.main()
