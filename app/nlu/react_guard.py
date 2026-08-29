# -*- coding: utf-8 -*-
"""ReAct 收束：本地小模型常把 done 写成 false，控车会连打满迭代。

done=false 只表示「本步结果决定下一步」。设温度、调音量、开关空调没有后续依赖，
即使模型说还没完，这一步也必须结束。
"""
from __future__ import annotations

from typing import Iterable, Optional

# 成功后仍可能要再规划：本步观察结果决定下一步（搜完周边再导航）
FOLLOWUP_TOOLS = frozenset({"maps.search_nearby"})


def is_followup_tool(name: Optional[str]) -> bool:
    return (name or "") in FOLLOWUP_TOOLS


def _names(calls: Iterable) -> list:
    return [getattr(c, "name", "") or "" for c in (calls or [])]


def coerce_step_done(calls: Iterable, done: bool) -> bool:
    """没有观察类工具时，强制本步结束。"""
    names = _names(calls)
    if not names:
        return True
    if any(is_followup_tool(n) for n in names):
        return bool(done)
    return True


def should_continue_after_success(calls: Iterable, done: bool) -> bool:
    """仅当模型明确还要下一步、且本步含观察类工具时才继续规划。"""
    if done:
        return False
    return any(is_followup_tool(n) for n in _names(calls))
