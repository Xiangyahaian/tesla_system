# -*- coding: utf-8 -*-
"""Append-only JSONL transcript + SQLite 双写。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, List, Optional

from app.agent.types import MessageRole, TranscriptMessage
from app.session.db import SessionDatabase


class TranscriptStore:
    def __init__(self, path: Path, *, db: Optional[SessionDatabase] = None, session_id: Optional[str] = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[List[TranscriptMessage]] = None
        self._db = db
        self._session_id = session_id

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self._cache = []
        if self._db and self._session_id:
            # 仅清消息，turns 由 TraceStore.clear / SessionStore.reset 处理
            with self._db._lock:
                self._db._conn.execute(
                    "DELETE FROM messages WHERE session_id = ?", (self._session_id,)
                )
                self._db._conn.execute(
                    """
                    UPDATE sessions SET message_count = 0, transcript_chars = 0, preview = '',
                      updated_at = ?, last_active = ? WHERE id = ?
                    """,
                    (time.time(), time.time(), self._session_id),
                )
                self._db._conn.commit()

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
        if self._db and self._session_id:
            self._db.append_message(
                self._session_id,
                msg.role.value,
                msg.content,
                msg.ts,
                msg.meta,
            )
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
        # 文件空时尝试从 SQLite 恢复
        if not msgs and self._db and self._session_id:
            for row in self._db.list_messages(self._session_id, limit=5000):
                try:
                    msgs.append(
                        TranscriptMessage(
                            role=MessageRole(row["role"]),
                            content=row["content"],
                            ts=float(row["ts"] or 0),
                            meta=row.get("meta") or {},
                        )
                    )
                except Exception:
                    continue
            if msgs:
                self.rewrite(msgs)
                return list(msgs)
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
        if self._db and self._session_id:
            self._db.replace_messages(self._session_id, msgs)

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
