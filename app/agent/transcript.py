# -*- coding: utf-8 -*-
"""Append-only JSONL transcript（对齐 Claude Code session JSONL）。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, List, Optional

from app.agent.types import MessageRole, TranscriptMessage


class TranscriptStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[List[TranscriptMessage]] = None

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self._cache = []

    def append(self, role: MessageRole | str, content: str, **meta) -> TranscriptMessage:
        msg = TranscriptMessage(
            role=MessageRole(role) if not isinstance(role, MessageRole) else role,
            content=content or "",
            ts=time.time(),
            meta=meta or {},
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(msg.model_dump_json(ensure_ascii=False) + "\n")
        if self._cache is None:
            self._cache = []
        self._cache.append(msg)
        return msg

    def load(self) -> List[TranscriptMessage]:
        if self._cache is not None:
            return list(self._cache)
        msgs: List[TranscriptMessage] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    msgs.append(TranscriptMessage.model_validate_json(line))
                except Exception:
                    continue
        self._cache = msgs
        return list(msgs)

    def rewrite(self, messages: Iterable[TranscriptMessage]) -> None:
        msgs = list(messages)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for m in msgs:
                f.write(m.model_dump_json(ensure_ascii=False) + "\n")
        tmp.replace(self.path)
        self._cache = msgs

    def total_chars(self) -> int:
        return sum(m.approx_chars() for m in self.load())

    def hint(self, limit: int = 8) -> str:
        msgs = self.load()[-limit:]
        parts = []
        for m in msgs:
            if m.role == MessageRole.COMPACTION:
                parts.append(f"[compact]{m.content[:180]}")
            else:
                parts.append(f"{m.role.value}:{m.content[:120]}")
        return " | ".join(parts)
