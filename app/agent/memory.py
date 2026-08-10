# -*- coding: utf-8 -*-
"""文件型记忆：CABIN.md（持久指令）+ MEMORY.md（auto memory）。

对齐 Claude Code 的 CLAUDE.md / auto memory 思路：可检查、可编辑、跨会话加载。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app import config

DEFAULT_CABIN_MD = """# Cabin Agent 指令（类似 CLAUDE.md）

## 人设
你是车载助手「小特」：自然、口语、好说话，像靠谱朋友，不要像安全宣讲师。

## 硬规则
- 控车必须走工具，禁止口头假装已执行。
- 问当前状态 → 读车辆 state；问手册用法 → 知识检索。
- 高风险操作（解锁/后备箱/ADAS）需用户确认。
- 避免政治/医疗/法律专业意见。

## 闲聊
- 正常聊天即可：吃什么、天气、心情、玩笑都可以直接答。
- **禁止**每轮都提醒「专注驾驶 / 先停车再… / 注意安全」；除非用户明确在问行车安全或危险操作。
- 回答简洁自然，1–3 句，不要说教。

## Compact Instructions
压缩上下文时优先保留：未完成任务、用户偏好、最近车控结果、待确认动作。
"""

DEFAULT_MEMORY_MD = """# Auto Memory

（助手自动写入的偏好与长期事实，跨会话加载前 200 行 / 25KB）
"""


class MemoryStore:
    def __init__(self, session_dir: Path, global_cabin: Optional[Path] = None):
        self.session_dir = Path(session_dir)
        self.memory_dir = self.session_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.session_cabin = self.session_dir / "CABIN.md"
        self.memory_md = self.memory_dir / "MEMORY.md"
        self.global_cabin = Path(global_cabin or (config.STATE_DIR / "CABIN.md"))
        self._ensure_files()

    def _ensure_files(self) -> None:
        if not self.global_cabin.exists():
            self.global_cabin.parent.mkdir(parents=True, exist_ok=True)
            self.global_cabin.write_text(DEFAULT_CABIN_MD, encoding="utf-8")
        if not self.session_cabin.exists():
            # 会话级可覆盖；默认指向说明即可精简
            self.session_cabin.write_text(
                "# Session CABIN\n\n（会话级补充指令；全局规则见 state/CABIN.md）\n",
                encoding="utf-8",
            )
        if not self.memory_md.exists():
            self.memory_md.write_text(DEFAULT_MEMORY_MD, encoding="utf-8")

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

    def append_memory(self, note: str) -> None:
        note = (note or "").strip()
        if not note:
            return
        with self.memory_md.open("a", encoding="utf-8") as f:
            f.write(f"\n- {note}\n")

    def maybe_extract(self, llm, user_query: str, assistant_text: str) -> Optional[str]:
        """轻量 auto-memory：让模型判断是否值得写入长期偏好。"""
        if not user_query or not assistant_text:
            return None
        # 启发式：偏好类短句才尝试，避免每轮都多一次 LLM
        keys = ("喜欢", "不要", "习惯", "以后", "偏好", "默认", "总是", "别再")
        if not any(k in user_query for k in keys):
            return None
        try:
            raw = llm.chat(
                "从对话提取是否值得写入长期记忆的一条短事实。"
                "若无需记忆，只返回 NONE。否则只返回一条中文短句，不要解释。",
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
