# -*- coding: utf-8 -*-
"""轻量 Hooks：pre/post tool。"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.models import ToolCall, ToolResult


HookFn = Callable[[Dict[str, Any]], Optional[str]]


class HookBus:
    def __init__(self):
        self.pre_tool: List[HookFn] = []
        self.post_tool: List[HookFn] = []

    def on_pre(self, fn: HookFn) -> None:
        self.pre_tool.append(fn)

    def on_post(self, fn: HookFn) -> None:
        self.post_tool.append(fn)

    def run_pre(self, call: ToolCall, state: dict) -> Optional[str]:
        """返回非空字符串表示拦截。"""
        payload = {"tool": call.name, "arguments": call.arguments, "state": state}
        for fn in self.pre_tool:
            msg = fn(payload)
            if msg:
                return msg
        return None

    def run_post(self, call: ToolCall, result: ToolResult, state: dict) -> None:
        payload = {
            "tool": call.name,
            "arguments": call.arguments,
            "result": result.model_dump(),
            "state": state,
        }
        for fn in self.post_tool:
            try:
                fn(payload)
            except Exception:
                pass
