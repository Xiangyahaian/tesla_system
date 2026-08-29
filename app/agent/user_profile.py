# -*- coding: utf-8 -*-
"""用户画像：三份自由 Markdown（人设 / 身份记忆 / 偏好），跨会话共享。

不再用固定 JSON 坑位。模型轮末读整篇 md，改一两处或末尾加一行。
代码只约束：Markdown、别太长、别写成流水账。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ALL_SEATS = ["front_left", "front_right", "rear_left", "rear_middle", "rear_right"]

SEAT_CN = {
    "front_left": "主驾",
    "front_right": "副驾",
    "rear_left": "左后",
    "rear_middle": "中后",
    "rear_right": "右后",
}

LIMITS = {
    "persona": {"max_chars": 800, "max_lines": 24},
    "memories": {"max_chars": 2500, "max_lines": 48},
    "preferences": {"max_chars": 1500, "max_lines": 36},
}

TEMPLATES = {
    "persona": """# 人设

目前没有额外约定，用默认的温暖口语。
""",
    "memories": """# 身份记忆

目前没有条目。用短列表记下用户长期有效的事实，不限于住址或家人。
""",
    "preferences": """# 偏好

目前没有条目。用短列表记下用户希望默认怎么做，不限于座位或温度。
""",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def is_placeholder(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    body = re.sub(r"^#.*$", "", t, flags=re.M).strip()
    if not body:
        return True
    return bool(re.match(r"^目前没有", body))


def clamp_markdown(text: str, kind: str) -> str:
    lim = LIMITS[kind]
    raw = (text or "").replace("\r\n", "\n").strip()
    raw = re.sub(r"^```(?:markdown|md)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    lines = [ln.rstrip() for ln in raw.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    # 压缩连续空行
    tight: List[str] = []
    blank = 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        tight.append(ln)
    titles = {"persona": "# 人设", "memories": "# 身份记忆", "preferences": "# 偏好"}
    if tight and not tight[0].lstrip().startswith("#"):
        tight = [titles[kind], ""] + tight
    if len(tight) > lim["max_lines"]:
        head = tight[:2]
        tail = tight[-(lim["max_lines"] - 2) :]
        tight = head + ["…"] + tail
    out = "\n".join(tight).strip() + "\n"
    if len(out) > lim["max_chars"]:
        out = out[: lim["max_chars"]].rstrip() + "\n"
    return out


def md_preview(text: str, n: int = 240) -> str:
    body = re.sub(r"^#.*$", "", text or "", flags=re.M).strip()
    if not body or body.startswith("目前没有"):
        return ""
    return body[:n]


def looks_unchanged(text: str) -> bool:
    t = (text or "").strip().strip("`").strip()
    if not t:
        return True
    key = re.sub(r"\s+", "", t).lower()
    return key in {
        "unchanged",
        "不变",
        "无需更新",
        "不更新",
        "none",
        "null",
        "same",
    }


@dataclass
class PersonaDelta:
    tone: Optional[str] = None
    style_notes: List[str] = field(default_factory=list)
    replace_style_notes: bool = False
    reset: bool = False


@dataclass
class MemoryItemDelta:
    action: str
    category: str
    key: str
    value: str = ""


@dataclass
class PreferencesDelta:
    preferred_seat: Optional[str] = None
    climate_temps: Dict[str, float] = field(default_factory=dict)
    climate_apply_all: Optional[bool] = None
    display_name: Optional[str] = None
    music_pref: Optional[str] = None
    reset: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.reset
            or self.preferred_seat
            or self.climate_temps
            or self.climate_apply_all is not None
            or self.display_name
            or self.music_pref
        )


@dataclass
class ProfileExtractReport:
    persona_updated: bool = False
    memories_updated: bool = False
    preferences_updated: bool = False
    llm_calls: int = 0
    triage: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    intent_decision: Dict[str, Any] = field(default_factory=dict)
    update_steps: List[Dict[str, Any]] = field(default_factory=list)


class UserProfileStore:
    """user_root/memory/ 下三份 md：persona.md · memories.md · preferences.md。"""

    def __init__(self, session_dir: Path):
        self.session_dir = Path(session_dir)
        self.memory_dir = self.session_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.persona_path = self.memory_dir / "persona.md"
        self.memories_path = self.memory_dir / "memories.md"
        self.prefs_path = self.memory_dir / "preferences.md"
        self._ensure_files()

    def _ensure_files(self) -> None:
        self._ingest_legacy_json()
        for kind, path in (
            ("persona", self.persona_path),
            ("memories", self.memories_path),
            ("preferences", self.prefs_path),
        ):
            if not path.exists():
                _write_text(path, TEMPLATES[kind])
        self._purge_legacy_json()

    def _ingest_legacy_json(self) -> None:
        """只读旧 json 一次，转成 md。新用户不会走到这里。"""
        pairs = (
            (self.persona_path, self.memory_dir / "persona.json", _persona_json_to_md),
            (self.memories_path, self.memory_dir / "memories.json", _memories_json_to_md),
            (self.prefs_path, self.memory_dir / "preferences.json", _prefs_json_to_md),
        )
        for md_path, json_path, to_md in pairs:
            if json_path.exists() and not md_path.exists():
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    _write_text(md_path, to_md(data))
                except Exception:
                    pass

    def _purge_legacy_json(self) -> None:
        """画像只落 md；这些文件名以后一律删掉，不再保留。"""
        for name in ("persona.json", "memories.json", "preferences.json", "MEMORY.md"):
            path = self.memory_dir / name
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass

    def read_md(self, kind: str) -> str:
        path = {
            "persona": self.persona_path,
            "memories": self.memories_path,
            "preferences": self.prefs_path,
        }[kind]
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = TEMPLATES[kind]
        return text if text.strip() else TEMPLATES[kind]

    def write_md(self, kind: str, text: str) -> bool:
        new = clamp_markdown(text, kind)
        if looks_unchanged(new) or not new.strip():
            return False
        old = self.read_md(kind)
        if new.strip() == old.strip():
            return False
        if is_placeholder(new) and is_placeholder(old):
            return False
        path = {
            "persona": self.persona_path,
            "memories": self.memories_path,
            "preferences": self.prefs_path,
        }[kind]
        _write_text(path, new)
        return True

    def read_persona_md(self) -> str:
        return self.read_md("persona")

    def read_memories_md(self) -> str:
        return self.read_md("memories")

    def read_preferences_md(self) -> str:
        return self.read_md("preferences")

    def load_persona(self) -> Dict[str, Any]:
        text = self.read_persona_md()
        return {"text": text, "tone": _guess_tone(text), "style_notes": _bullet_values(text)}

    def load_memories(self) -> Dict[str, Any]:
        text = self.read_memories_md()
        items = []
        for i, val in enumerate(_bullet_values(text)):
            items.append(
                {
                    "id": f"md{i}",
                    "category": "other",
                    "key": f"note_{i}",
                    "value": val,
                    "updated_at": None,
                }
            )
        return {"text": text, "items": items}

    def load_preferences(self) -> Dict[str, Any]:
        text = self.read_preferences_md()
        seat, temps, name, music = _parse_pref_hints(text)
        return {
            "text": text,
            "preferred_seat": seat,
            "climate_temp_c": temps,
            "climate_apply_all": "全车" in text or "全部座位" in text,
            "display_name": name,
            "music_pref": music,
        }

    def clear_persona(self) -> None:
        _write_text(self.persona_path, TEMPLATES["persona"])

    def clear_memories(self) -> None:
        _write_text(self.memories_path, TEMPLATES["memories"])

    def clear_preferences(self) -> None:
        _write_text(self.prefs_path, TEMPLATES["preferences"])

    def clear_all(self) -> None:
        self.clear_persona()
        self.clear_memories()
        self.clear_preferences()

    def apply_persona_delta(self, delta: PersonaDelta) -> bool:
        if delta.reset:
            self.clear_persona()
            return True
        notes = [n.strip() for n in (delta.style_notes or []) if n.strip()]
        if not delta.tone and not notes:
            return False
        lines = ["# 人设", ""]
        if delta.tone and delta.tone != "default":
            lines.append(f"- 语气：{delta.tone}")
        for n in notes:
            lines.append(f"- {n}")
        return self.write_md("persona", "\n".join(lines) + "\n")

    def apply_memory_deltas(self, deltas: List[MemoryItemDelta]) -> bool:
        if not deltas:
            return False
        text = self.read_memories_md()
        lines = text.rstrip().split("\n")
        changed = False
        for d in deltas:
            val = (d.value or "").strip()
            if d.action == "delete":
                key = (d.key or "").strip()
                new_lines = [ln for ln in lines if key not in ln and val not in ln]
                if new_lines != lines:
                    lines = new_lines
                    changed = True
                continue
            if not val:
                continue
            if any(val in ln for ln in lines):
                continue
            lines.append(f"- {val}")
            changed = True
        if not changed:
            return False
        return self.write_md("memories", "\n".join(lines) + "\n")

    def apply_preferences_delta(self, delta: PreferencesDelta) -> bool:
        if delta.reset:
            self.clear_preferences()
            return True
        if not delta.changed:
            return False
        text = self.read_preferences_md()
        if is_placeholder(text):
            lines = ["# 偏好", ""]
        else:
            lines = text.rstrip().split("\n")
        if delta.display_name:
            lines = _upsert_line(lines, r"(称呼|昵称|叫我)", f"- 称呼：{delta.display_name}")
        if delta.preferred_seat:
            cn = SEAT_CN.get(delta.preferred_seat, delta.preferred_seat)
            lines = _upsert_line(lines, r"(常坐|座位|主驾|副驾)", f"- 常坐{cn}")
        if delta.climate_temps:
            if delta.climate_apply_all or len(delta.climate_temps) >= 5:
                t = next(iter(delta.climate_temps.values()))
                lines = _upsert_line(lines, r"(温度|度)", f"- 全车默认 {float(t):.0f} 度")
            else:
                bits = []
                for z, t in delta.climate_temps.items():
                    bits.append(f"{SEAT_CN.get(z, z)} {float(t):.0f} 度")
                lines = _upsert_line(lines, r"(温度|度)", f"- 温度习惯：{'，'.join(bits)}")
        if delta.music_pref:
            lines = _upsert_line(lines, r"(音乐|歌)", f"- 音乐：{delta.music_pref}")
        return self.write_md("preferences", "\n".join(lines) + "\n")

    def snapshot_for_extract(self) -> Dict[str, Any]:
        return {
            "persona": self.read_persona_md(),
            "memories": self.read_memories_md(),
            "preferences": self.read_preferences_md(),
        }


def _bullet_values(text: str) -> List[str]:
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s.startswith(("- ", "* ", "• ")):
            out.append(s[2:].strip())
    return out


def _guess_tone(text: str) -> str:
    t = text or ""
    if re.search(r"专业|严谨|干练", t):
        return "professional"
    if re.search(r"简洁|少说话|别啰嗦", t):
        return "concise"
    if re.search(r"活泼|俏皮|轻松", t):
        return "playful"
    if re.search(r"温柔|柔和|陪伴", t):
        return "gentle"
    return "default"


def _parse_pref_hints(text: str) -> tuple[Optional[str], Dict[str, float], Optional[str], Optional[str]]:
    seat = None
    if re.search(r"副驾", text):
        seat = "front_right"
    elif re.search(r"主驾|驾驶位", text):
        seat = "front_left"
    elif re.search(r"左后", text):
        seat = "rear_left"
    elif re.search(r"右后", text):
        seat = "rear_right"
    elif re.search(r"中后|后排中", text):
        seat = "rear_middle"
    temps: Dict[str, float] = {}
    m = re.search(r"(\d{2})\s*度", text)
    if m:
        t = float(m.group(1))
        if 16 <= t <= 30:
            if "全车" in text or "全部" in text:
                for z in ALL_SEATS:
                    temps[z] = t
            elif seat:
                temps[seat] = t
            else:
                temps["front_left"] = t
    name = None
    nm = re.search(r"(?:称呼|昵称)[：:]\s*(\S{1,12})", text)
    if nm:
        name = nm.group(1).strip("，。；")
    else:
        nm = re.search(r"叫我\s*(\S{1,12})", text)
        if nm:
            name = nm.group(1).strip("，。；")
    music = None
    mm = re.search(r"(?:音乐|爱听|喜欢听)[：:]\s*(.+)$", text, re.M)
    if mm:
        music = mm.group(1).strip()[:40]
    return seat, temps, name, music


def _upsert_line(lines: List[str], pattern: str, new_line: str) -> List[str]:
    rx = re.compile(pattern)
    out = []
    replaced = False
    for ln in lines:
        if (ln.strip().startswith("-") or ln.strip().startswith("*")) and rx.search(ln):
            out.append(new_line)
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        if out and out[-1].strip():
            out.append(new_line)
        else:
            out.append(new_line)
    return out


def _persona_json_to_md(data: Dict[str, Any]) -> str:
    lines = ["# 人设", ""]
    tone = str((data or {}).get("tone") or "default")
    if tone and tone != "default":
        lines.append(f"- 语气：{tone}")
    for n in data.get("style_notes") or []:
        if str(n).strip():
            lines.append(f"- {str(n).strip()}")
    if len(lines) == 2:
        return TEMPLATES["persona"]
    return "\n".join(lines) + "\n"


def _memories_json_to_md(data: Dict[str, Any]) -> str:
    items = (data or {}).get("items") or []
    if not items:
        return TEMPLATES["memories"]
    lines = ["# 身份记忆", ""]
    for it in items:
        val = str(it.get("value") or "").strip()
        if val:
            lines.append(f"- {val}")
    return "\n".join(lines) + "\n"


def _prefs_json_to_md(data: Dict[str, Any]) -> str:
    data = data or {}
    lines = ["# 偏好", ""]
    if data.get("display_name"):
        lines.append(f"- 称呼：{data['display_name']}")
    seat = data.get("preferred_seat")
    if seat:
        lines.append(f"- 常坐{SEAT_CN.get(seat, seat)}")
    temps = data.get("climate_temp_c") or {}
    if data.get("climate_apply_all") and temps:
        t = next(iter(temps.values()))
        lines.append(f"- 全车默认 {float(t):.0f} 度")
    elif temps:
        bits = [f"{SEAT_CN.get(z, z)} {float(t):.0f} 度" for z, t in temps.items()]
        lines.append(f"- 温度习惯：{'，'.join(bits)}")
    if data.get("music_pref"):
        lines.append(f"- 音乐：{data['music_pref']}")
    if len(lines) == 2:
        return TEMPLATES["preferences"]
    return "\n".join(lines) + "\n"
