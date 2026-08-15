# -*- coding: utf-8 -*-
"""文件型记忆：CABIN.md（持久指令）+ MEMORY.md / preferences.json（Auto Memory）。

对齐 Claude Code：
- CABIN.md ≈ CLAUDE.md：可检查、可编辑的项目级指令
- MEMORY.md：人类可读的自动记忆（分区标题、可手工改）
- preferences.json：机器可读偏好，真正驱动座位/温度等默认行为
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.agent.persona import CABIN_MD

DEFAULT_CABIN_MD = CABIN_MD

DEFAULT_MEMORY_MD = """# Auto Memory

> Claude Code 同款：助手自动维护；可手工编辑。跨会话加载。
> 机器可读副本：`preferences.json`（改偏好请两边同步或走助手「记住…」）。

## Preferences

（座位、温度、音乐、称呼等）

## Facts

（长期事实）

## Notes

（其它备注）
"""

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
    """一次话语解析出的偏好变更。"""

    preferred_seat: Optional[str] = None
    climate_temps: Dict[str, float] = field(default_factory=dict)
    display_name: Optional[str] = None
    music_pref: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    applied: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.preferred_seat
            or self.climate_temps
            or self.display_name
            or self.music_pref
            or self.notes
        )


class MemoryStore:
    def __init__(self, session_dir: Path, global_cabin: Optional[Path] = None):
        self.session_dir = Path(session_dir)
        self.memory_dir = self.session_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.session_cabin = self.session_dir / "CABIN.md"
        self.memory_md = self.memory_dir / "MEMORY.md"
        self.prefs_path = self.memory_dir / "preferences.json"
        self.global_cabin = Path(global_cabin or (config.STATE_DIR / "CABIN.md"))
        self._ensure_files()

    def _ensure_files(self) -> None:
        if not self.global_cabin.exists():
            self.global_cabin.parent.mkdir(parents=True, exist_ok=True)
            self.global_cabin.write_text(DEFAULT_CABIN_MD, encoding="utf-8")
        if not self.session_cabin.exists():
            self.session_cabin.write_text(
                "# Session CABIN\n\n（会话级补充指令；全局规则见 state/CABIN.md）\n",
                encoding="utf-8",
            )
        if not self.memory_md.exists():
            self.memory_md.write_text(DEFAULT_MEMORY_MD, encoding="utf-8")
        if not self.prefs_path.exists():
            self._write_preferences(self._empty_prefs())

    @staticmethod
    def _empty_prefs() -> Dict[str, Any]:
        return {
            "version": 1,
            "preferred_seat": None,
            "climate_temp_c": {},  # seat -> float
            "display_name": None,
            "music_pref": None,
            "facts": [],
            "updated_at": None,
        }

    def load_preferences(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.prefs_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return self._empty_prefs()
            base = self._empty_prefs()
            base.update(data)
            if not isinstance(base.get("climate_temp_c"), dict):
                base["climate_temp_c"] = {}
            if not isinstance(base.get("facts"), list):
                base["facts"] = []
            return base
        except Exception:
            return self._empty_prefs()

    def _write_preferences(self, prefs: Dict[str, Any]) -> None:
        prefs = dict(prefs)
        prefs["updated_at"] = datetime.now().isoformat(timespec="seconds")
        tmp = self.prefs_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.prefs_path)

    def rewrite_memory_md(self, prefs: Optional[Dict[str, Any]] = None) -> None:
        """从 preferences.json 重写 MEMORY.md（Claude Code 可读层）。"""
        prefs = prefs or self.load_preferences()
        pref_lines: List[str] = []
        seat = prefs.get("preferred_seat")
        if seat:
            pref_lines.append(f"- preferred_seat: {SEAT_CN.get(seat, seat)} ({seat})")
        for z, t in (prefs.get("climate_temp_c") or {}).items():
            pref_lines.append(f"- climate.{SEAT_CN.get(z, z)}: {float(t):.0f}°C")
        if prefs.get("display_name"):
            pref_lines.append(
                f"- display_name: {prefs['display_name']} "
                "（尽量少喊；寒暄或用户要求称呼时可偶尔用）"
            )
        if prefs.get("music_pref"):
            pref_lines.append(f"- music_pref: {prefs['music_pref']}")
        if not pref_lines:
            pref_lines.append("- （暂无结构化偏好）")

        facts = prefs.get("facts") or []
        fact_lines = [f"- {x}" for x in facts[-30:]] or ["- （暂无）"]

        body = "\n".join(
            [
                "# Auto Memory",
                "",
                "> Claude Code 同款：助手自动维护；可手工编辑。跨会话加载。",
                "> 机器可读副本：`preferences.json`。",
                "",
                "## Preferences",
                "",
                *pref_lines,
                "",
                "## Facts",
                "",
                *fact_lines,
                "",
                "## Notes",
                "",
                f"- updated_at: {prefs.get('updated_at') or '—'}",
                "",
            ]
        )
        self.memory_md.write_text(body, encoding="utf-8")

    def upsert_preferences(self, delta: PreferenceDelta) -> Dict[str, Any]:
        prefs = self.load_preferences()
        if delta.preferred_seat:
            prefs["preferred_seat"] = delta.preferred_seat
        climate = dict(prefs.get("climate_temp_c") or {})
        for z, t in delta.climate_temps.items():
            climate[z] = float(t)
        prefs["climate_temp_c"] = climate
        if delta.display_name:
            prefs["display_name"] = delta.display_name
        if delta.music_pref:
            prefs["music_pref"] = delta.music_pref
        facts = list(prefs.get("facts") or [])
        for n in delta.notes:
            n = (n or "").strip()
            if n and n not in facts:
                facts.append(n)
        prefs["facts"] = facts[-40:]
        self._write_preferences(prefs)
        self.rewrite_memory_md(prefs)
        return prefs

    def clear_preferences(self) -> None:
        self._write_preferences(self._empty_prefs())
        self.rewrite_memory_md()

    def load_cabin(self, max_chars: int = 8000) -> str:
        parts = []
        g = self.global_cabin.read_text(encoding="utf-8")[:max_chars]
        parts.append(f"## Global CABIN.md\n{g}")
        s = self.session_cabin.read_text(encoding="utf-8")[: max_chars // 2]
        if s.strip():
            parts.append(f"## Session CABIN.md\n{s}")
        return "\n\n".join(parts)

    def load_auto_memory(self, max_lines: int = 200, max_bytes: int = 25_000) -> str:
        raw = self.memory_md.read_bytes()[:max_bytes]
        text = raw.decode("utf-8", errors="ignore")
        lines = text.splitlines()[:max_lines]
        return "\n".join(lines)

    def format_preferences_block(self) -> str:
        """注入 NLU / Agent 的短偏好块。"""
        prefs = self.load_preferences()
        lines = ["[User Preferences — must honor when user omits seat/temp]"]
        seat = prefs.get("preferred_seat")
        if seat:
            lines.append(f"- preferred_seat: {SEAT_CN.get(seat, seat)} ({seat})")
        for z, t in (prefs.get("climate_temp_c") or {}).items():
            lines.append(f"- preferred_temp[{SEAT_CN.get(z, z)}]={float(t):.0f}")
        if prefs.get("display_name"):
            lines.append(
                f"- user_nickname: {prefs['display_name']} "
                "（尽量少用；办事/报状态优先直说，寒暄或用户要求时可偶尔称呼）"
            )
        if prefs.get("music_pref"):
            lines.append(f"- music: {prefs['music_pref']}")
        if len(lines) == 1:
            lines.append("- (none yet)")
        return "\n".join(lines)

    def append_memory(self, note: str) -> None:
        """兼容旧调用：写入 facts + 刷新 md。"""
        note = (note or "").strip()
        if not note:
            return
        delta = PreferenceDelta(notes=[note])
        self.upsert_preferences(delta)

    def detect_seat_mention(self, text: str) -> Optional[str]:
        t = text or ""
        # 长词优先
        for cn in sorted(SEAT_ALIAS.keys(), key=len, reverse=True):
            if cn in t:
                return SEAT_ALIAS[cn]
        return None

    def ingest_utterance(self, user_query: str) -> PreferenceDelta:
        """确定性抽取偏好（不依赖 LLM），可现场复现。"""
        text = (user_query or "").strip()
        delta = PreferenceDelta()
        if not text:
            return delta

        seat = self.detect_seat_mention(text)
        # 声明常用座位
        if seat and re.search(
            r"(我坐|坐在|我在|换到|默认|以后坐|坐副驾|坐主驾|我是副驾|我是主驾)",
            text,
        ):
            delta.preferred_seat = seat

        temp_vals: List[float] = []
        for x in re.findall(r"(?:喜欢|偏好|默认|调到|设为|设置为?)?\s*(\d{2})\s*度", text):
            try:
                v = float(x)
                if 16 <= v <= 30:
                    temp_vals.append(v)
            except Exception:
                pass
        if temp_vals:
            t = temp_vals[-1]
            prefs = self.load_preferences()
            target = delta.preferred_seat or seat or prefs.get("preferred_seat") or "front_left"
            delta.climate_temps[str(target)] = t
            cn = SEAT_CN.get(str(target), str(target))
            delta.notes.append(f"用户偏好 {cn} 温度 {t:.0f}°C")

        if delta.preferred_seat:
            cn = SEAT_CN.get(delta.preferred_seat, delta.preferred_seat)
            delta.notes.append(f"用户常用座位：{cn}")

        m = re.search(r"(?:叫我|我叫|我姓)\s*([^\s，。！？,]{1,12})", text)
        if m:
            delta.display_name = m.group(1).strip()
            delta.notes.append(f"称呼：{delta.display_name}")

        if re.search(r"(喜欢听|常听|偏好).*(歌|音乐|周杰伦|林俊杰|纯音乐)", text):
            mm = re.search(r"(周杰伦|林俊杰|纯音乐|流行|古典)", text)
            if mm:
                delta.music_pref = mm.group(1)
                delta.notes.append(f"音乐偏好：{delta.music_pref}")

        if delta.changed:
            self.upsert_preferences(delta)
            delta.applied = True
        return delta

    def maybe_extract(self, llm, user_query: str, assistant_text: str) -> Optional[str]:
        """先跑确定性抽取；不足时再 LLM 补一条 Fact（Claude Code auto-memory）。"""
        delta = self.ingest_utterance(user_query)
        if delta.changed:
            bits = []
            if delta.preferred_seat:
                bits.append(f"座位={SEAT_CN.get(delta.preferred_seat)}")
            for z, t in delta.climate_temps.items():
                bits.append(f"{SEAT_CN.get(z, z)}={t:.0f}°C")
            return "已写入偏好：" + "，".join(bits) if bits else "已更新 Auto Memory"

        if not user_query or not assistant_text:
            return None
        keys = ("喜欢", "不要", "习惯", "以后", "偏好", "默认", "总是", "别再", "叫我", "我姓", "我是", "记住")
        if not any(k in user_query for k in keys):
            return None
        try:
            raw = llm.chat(
                "从对话提取是否值得写入长期记忆的一条短事实（偏好、称呼、习惯）。"
                "若无需记忆，只返回 NONE。否则只返回一条中文短句事实，不要解释。",
                f"用户: {user_query}\n助手: {assistant_text[:300]}",
                temperature=0.0,
            )
            raw = (raw or "").strip()
            if not raw or raw.upper() == "NONE" or len(raw) > 80:
                return None
            self.append_memory(raw)
            return raw
        except Exception:
            return None

    def preferred_temp_for(self, seat: str) -> Optional[float]:
        prefs = self.load_preferences()
        v = (prefs.get("climate_temp_c") or {}).get(seat)
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def resolve_active_seat(
        self,
        ui_seat: Optional[str],
        utterance: str,
        *,
        honor_memory: bool = True,
    ) -> Tuple[str, str]:
        """返回 (seat_id, source)。source: utterance|memory|ui|default"""
        from app.nlu.seat_context import normalize_active_seat

        explicit = self.detect_seat_mention(utterance or "")
        # 用户明确点名座位（控车/询问）
        if explicit and re.search(
            r"(副驾|主驾|左后|右后|中后|后排|驾驶|打开|关掉|调|温度|空调|座椅|加热|通风|车窗|吹)",
            utterance or "",
        ):
            # 「我坐副驾」类已在 ingest 写入；控车句若点名座位用点名
            if not re.search(r"^我坐|^坐在|^我在副|^我在主", (utterance or "").strip()):
                return explicit, "utterance"

        prefs = self.load_preferences()
        mem_seat = prefs.get("preferred_seat") if honor_memory else None
        # 第一人称控车且未另点座位 → 记忆座位
        if mem_seat and _looks_self_cabin(utterance or ""):
            if not explicit or explicit == mem_seat:
                return normalize_active_seat(mem_seat), "memory"

        if mem_seat and honor_memory and not explicit:
            # 模糊控车：「打开空调」「温度调高」
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
    """偏好话语当场落到车控（端到端可见）。"""
    from app.models import ToolCall

    calls: List[ToolCall] = []
    for z, t in delta.climate_temps.items():
        calls.append(
            ToolCall(
                name="climate.set_power",
                arguments={"enable": True, "zones": [z]},
                reason="按记忆偏好开启分区空调",
            )
        )
        calls.append(
            ToolCall(
                name="climate.set_temperature",
                arguments={"temperature": float(t), "zones": [z]},
                reason=f"应用偏好温度 {t:.0f}°C",
            )
        )
    return calls
