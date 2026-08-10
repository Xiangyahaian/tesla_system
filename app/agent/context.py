# -*- coding: utf-8 -*-
"""上下文组装：有序 source 拼装（对齐 Claude Code context assembly）。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.agent.memory import MemoryStore
from app.agent.transcript import TranscriptStore
from app.agent.types import ContextBundle, MessageRole, TranscriptMessage


SYSTEM_CORE = """你是车载助手「小特」。
工作方式：结合上下文理解 → 决策（正常聊天/控车/查状态/查手册）→ 给出自然回复。
禁止编造已执行的车控；工具结果以 transcript 中的 tool 消息为准。
闲聊时像正常人聊天，不要主动说教或反复提「专注驾驶」。
"""


class ContextAssembler:
    def assemble(
        self,
        memory: MemoryStore,
        transcript: TranscriptStore,
        vehicle_state: Dict[str, Any],
        extra_user: str = "",
        recent_limit: int = 12,
    ) -> ContextBundle:
        sources: List[str] = []
        cabin = memory.load_cabin()
        sources.append("cabin_md")
        auto_mem = memory.load_auto_memory()
        sources.append("auto_memory")

        slim = _slim_vehicle(vehicle_state)
        vehicle_txt = json.dumps(slim, ensure_ascii=False)
        sources.append("vehicle_state")

        msgs = transcript.load()
        compact_bits = [m.content for m in msgs if m.role == MessageRole.COMPACTION]
        compact_txt = "\n---\n".join(compact_bits[-2:]) if compact_bits else ""
        if compact_txt:
            sources.append("compaction")

        recent = [m for m in msgs if m.role != MessageRole.COMPACTION][-recent_limit:]
        dialog = _format_dialog(recent)
        sources.append("transcript_recent")

        user_context_parts = [
            "### Persistent Instructions (CABIN.md)",
            cabin,
            "### Auto Memory (MEMORY.md)",
            auto_mem or "(空)",
            "### Vehicle State Snapshot",
            vehicle_txt,
        ]
        if compact_txt:
            user_context_parts += ["### Compaction Summary", compact_txt]
        if extra_user:
            user_context_parts += ["### Extra", extra_user]
            sources.append("extra")

        user_context = "\n\n".join(user_context_parts)
        total = len(SYSTEM_CORE) + len(user_context) + len(dialog)
        return ContextBundle(
            system=SYSTEM_CORE,
            user_context=user_context,
            recent_dialog=dialog,
            total_chars=total,
            sources=sources,
        )

    def memory_hint(self, bundle: ContextBundle, transcript: TranscriptStore, limit: int = 8) -> str:
        """给 StructuredNLU 用的短历史。"""
        base = transcript.hint(limit=limit)
        # 附带 compaction 尾句
        if "Compaction Summary" in bundle.user_context:
            return (bundle.user_context.split("### Compaction Summary")[-1][:200] + " || " + base)[:800]
        return base


def _format_dialog(msgs: List[TranscriptMessage]) -> str:
    lines = []
    for m in msgs:
        lines.append(f"{m.role.value}: {m.content}")
    return "\n".join(lines)


def _slim_vehicle(st: Dict[str, Any]) -> Dict[str, Any]:
    seats = st.get("seats") or {}
    climate = st.get("climate") or {}
    return {
        "dynamics": st.get("dynamics"),
        "climate": {
            "power": climate.get("power"),
            "mode": climate.get("mode"),
            "front_left": (climate.get("zones") or {}).get("front_left"),
        },
        "media": st.get("media"),
        "seats": {
            "heat_front_left": (seats.get("heat") or {}).get("front_left"),
            "steering_wheel_heat": seats.get("steering_wheel_heat"),
        },
        "navigation": st.get("navigation"),
        "cabin": {
            "windows_fl": ((st.get("cabin") or {}).get("windows") or {}).get("front_left"),
            "trunk": ((st.get("cabin") or {}).get("trunk")),
        },
        "driving": st.get("driving"),
    }
