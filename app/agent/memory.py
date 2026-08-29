# -*- coding: utf-8 -*-
"""用户画像门面：人设 / 身份记忆 / 行为偏好（三文件，无 CABIN.md）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.agent.persona import build_persona_overlay, build_system_prompt, build_style_overlay
from app.agent.profile_extract import extract_after_turn
from app.agent.user_profile import PreferencesDelta, UserProfileStore, is_placeholder

SEAT_ALIAS = {
    "主驾": "front_left",
    "驾驶位": "front_left",
    "司机": "front_left",
    "左边": "front_left",
    "左座": "front_left",
    "副驾": "front_right",
    "副驾驶": "front_right",
    "右边": "front_right",
    "右座": "front_right",
    "左后": "rear_left",
    "后排左": "rear_left",
    "中后": "rear_middle",
    "后排中间": "rear_middle",
    "右后": "rear_right",
    "后排右": "rear_right",
}

SEAT_CN = {
    "front_left": "主驾",
    "front_right": "副驾",
    "rear_left": "左后",
    "rear_middle": "中后",
    "rear_right": "右后",
}


@dataclass
class PreferenceDelta:
    """兼容旧调用：偏好变更摘要。"""

    preferred_seat: Optional[str] = None
    climate_temps: Dict[str, float] = field(default_factory=dict)
    climate_apply_all: Optional[bool] = None
    display_name: Optional[str] = None
    music_pref: Optional[str] = None
    applied: bool = False


class MemoryStore:
    """每用户目录下的画像存储（跨会话共享；委托 UserProfileStore）。"""

    def __init__(self, session_dir: Path, global_cabin: Optional[Path] = None):
        self.session_dir = Path(session_dir)
        self._profile = UserProfileStore(self.session_dir)

    @property
    def memory_dir(self) -> Path:
        return self._profile.memory_dir

    def load_persona(self) -> Dict[str, Any]:
        return self._profile.load_persona()

    def load_memories(self) -> Dict[str, Any]:
        return self._profile.load_memories()

    def load_preferences(self) -> Dict[str, Any]:
        return self._profile.load_preferences()

    def clear_all(self) -> None:
        self._profile.clear_all()

    def format_persona_block(self) -> str:
        text = self._profile.read_persona_md()
        overlay = build_persona_overlay({"text": text})
        if overlay:
            return overlay
        return "(默认温暖陪伴)"

    def format_memories_block(self, max_items: int = 20) -> str:
        text = self._profile.read_memories_md().strip()
        if is_placeholder(text):
            return "(暂无身份记忆)"
        head: List[str] = []
        bullets: List[str] = []
        for ln in text.splitlines():
            if ln.strip().startswith(("- ", "* ", "• ")):
                bullets.append(ln)
            elif not bullets:
                head.append(ln)
        shown = bullets[-max_items:] if max_items and len(bullets) > max_items else bullets
        return "\n".join([*head, *shown]).strip() or "(暂无身份记忆)"

    def format_preferences_block(self) -> str:
        text = self._profile.read_preferences_md().strip()
        if is_placeholder(text):
            return "(暂无偏好)"
        return text

    def build_system_prompt(self) -> str:
        return build_system_prompt(self.load_persona())

    def build_style_overlay(self) -> str:
        return build_style_overlay(self.load_persona())

    def extract_after_turn(self, llm, user_query: str, assistant_text: str = "", profile_plan=None):
        if not config.AGENT_ENABLE_AUTO_MEMORY:
            from app.agent.user_profile import ProfileExtractReport

            return ProfileExtractReport()
        return extract_after_turn(llm, self._profile, user_query, assistant_text, profile_plan=profile_plan)

    def upsert_preferences(self, delta: PreferenceDelta) -> Dict[str, Any]:
        pd = PreferencesDelta(
            preferred_seat=delta.preferred_seat,
            climate_temps=dict(delta.climate_temps),
            climate_apply_all=delta.climate_apply_all,
            display_name=delta.display_name,
            music_pref=delta.music_pref,
        )
        self._profile.apply_preferences_delta(pd)
        return self.load_preferences()

    def preferred_temp_for(self, seat: str) -> Optional[float]:
        v = (self.load_preferences().get("climate_temp_c") or {}).get(seat)
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def detect_seat_mention(self, text: str) -> Optional[str]:
        t = text or ""
        for cn in sorted(SEAT_ALIAS.keys(), key=len, reverse=True):
            if cn in t:
                return SEAT_ALIAS[cn]
        return None

    def resolve_active_seat(
        self,
        ui_seat: Optional[str],
        utterance: str,
        *,
        honor_memory: bool = True,
    ) -> Tuple[str, str]:
        from app.nlu.seat_context import normalize_active_seat

        explicit = self.detect_seat_mention(utterance or "")
        if explicit and re.search(
            r"(副驾|主驾|左后|右后|中后|后排|驾驶|打开|关掉|调|温度|空调|座椅|加热|通风|车窗|吹)",
            utterance or "",
        ):
            if not re.search(r"^我坐|^坐在|^我在副|^我在主", (utterance or "").strip()):
                return explicit, "utterance"

        prefs = self.load_preferences()
        mem_seat = prefs.get("preferred_seat") if honor_memory else None
        if mem_seat and _looks_self_cabin(utterance or ""):
            if not explicit or explicit == mem_seat:
                return normalize_active_seat(mem_seat), "memory"

        if mem_seat and honor_memory and not explicit:
            if re.search(r"(空调|温度|风量|座椅|加热|通风|按摩|车窗)", utterance or ""):
                return normalize_active_seat(mem_seat), "memory"

        if ui_seat:
            return normalize_active_seat(ui_seat), "ui"
        if mem_seat:
            return normalize_active_seat(mem_seat), "memory"
        return "front_left", "default"


def _looks_self_cabin(text: str) -> bool:
    if re.search(r"(我|给我|帮我|我这边|我这)", text):
        return True
    return bool(re.search(r"(打开空调|调温|温度|风量|座椅加热)", text))


def build_preference_tool_calls(delta: PreferenceDelta):
    from app.models import ToolCall

    calls: List[ToolCall] = []
    zones = list(delta.climate_temps.keys())
    if not zones:
        return calls

    if len(zones) >= 5 or delta.climate_apply_all:
        calls.append(
            ToolCall(name="climate.set_power", arguments={"enable": True}, reason="按偏好开启全车空调")
        )
        for z, t in delta.climate_temps.items():
            calls.append(
                ToolCall(
                    name="climate.set_temperature",
                    arguments={"temperature": float(t), "zones": [z]},
                    reason=f"应用偏好温度 {t:.0f}°C",
                )
            )
        return calls

    for z, t in delta.climate_temps.items():
        calls.append(
            ToolCall(name="climate.set_power", arguments={"enable": True, "zones": [z]}, reason="按偏好开空调")
        )
        calls.append(
            ToolCall(
                name="climate.set_temperature",
                arguments={"temperature": float(t), "zones": [z]},
                reason=f"应用偏好温度 {t:.0f}°C",
            )
        )
    return calls
