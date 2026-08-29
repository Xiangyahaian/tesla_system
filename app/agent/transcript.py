# -*- coding: utf-8 -*-
"""会话对话日志：JSONL 落盘（session.jsonl）+ SQLite 双写。

追加式写入；压缩只 append compaction，不覆盖历史。
读模型上下文用 load_for_context()：最新摘要 + 最近 N 轮。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, List, Optional

from app.agent.compact import select_context_window
from app.agent.types import MessageRole, TranscriptMessage
from app.session.db import SessionDatabase

# 对话日志（JSON Lines）
SESSION_LOG_NAME = "session.jsonl"
LEGACY_SESSION_JSON = "session.json"  # 曾误用 .json 扩展名的 JSONL，或旧元数据
LEGACY_TRANSCRIPT_NAME = "transcript.jsonl"
LEGACY_META_NAME = "session.meta.json"


def resolve_session_log_path(session_dir: Path) -> Path:
    """解析并迁移到 session.jsonl。

    优先级：
    1) 已有 session.jsonl → 直接用
    2) session.json 若是 JSONL → 改名为 session.jsonl
    3) transcript.jsonl → 改名为 session.jsonl
    4) session.json 若是旧元数据 → 删掉（元数据在 SQLite）
    """
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / SESSION_LOG_NAME
    legacy_json = session_dir / LEGACY_SESSION_JSON
    legacy_tr = session_dir / LEGACY_TRANSCRIPT_NAME

    if log_path.exists() and _looks_like_jsonl_transcript(log_path):
        _cleanup_legacy_siblings(session_dir, keep=log_path)
        return log_path

    # session.json 实为 JSONL 对话
    if legacy_json.exists() and _looks_like_jsonl_transcript(legacy_json):
        _safe_rename(legacy_json, log_path)
        _cleanup_legacy_siblings(session_dir, keep=log_path)
        return log_path

    # 旧 transcript.jsonl
    if legacy_tr.exists() and _looks_like_jsonl_transcript(legacy_tr):
        if log_path.exists() and not _looks_like_jsonl_transcript(log_path):
            try:
                log_path.unlink()
            except Exception:
                pass
        if not log_path.exists():
            _safe_rename(legacy_tr, log_path)
        else:
            try:
                legacy_tr.unlink()
            except Exception:
                pass
        _cleanup_legacy_siblings(session_dir, keep=log_path)
        return log_path

    # 仅剩旧元数据 session.json
    if legacy_json.exists() and _looks_like_metadata_session(legacy_json):
        _discard_metadata_file(legacy_json, session_dir)

    return log_path


def _cleanup_legacy_siblings(session_dir: Path, keep: Path) -> None:
    for name in (LEGACY_TRANSCRIPT_NAME, LEGACY_SESSION_JSON, LEGACY_META_NAME):
        p = session_dir / name
        if p.exists() and p.resolve() != keep.resolve():
            if name == LEGACY_SESSION_JSON and _looks_like_metadata_session(p):
                _discard_metadata_file(p, session_dir)
            elif name in (LEGACY_TRANSCRIPT_NAME, LEGACY_SESSION_JSON) and _looks_like_jsonl_transcript(p):
                # 已有正式 jsonl，丢掉重复旧文件
                try:
                    p.unlink()
                except Exception:
                    pass
            elif name == LEGACY_META_NAME:
                try:
                    p.unlink()
                except Exception:
                    pass


def _discard_metadata_file(path: Path, session_dir: Path) -> None:
    bak = session_dir / LEGACY_META_NAME
    try:
        if bak.exists():
            bak.unlink()
        path.replace(bak)
        try:
            bak.unlink()
        except Exception:
            pass
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass


def _safe_rename(src: Path, dst: Path) -> None:
    try:
        src.replace(dst)
    except Exception:
        try:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            src.unlink()
        except Exception:
            pass


def _looks_like_metadata_session(path: Path) -> bool:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw.startswith("{"):
            return False
        if "\n{" in raw[:2000] and '"role"' in raw[:500]:
            return False
        data = json.loads(raw)
        return isinstance(data, dict) and ("slots" in data or "session_id" in data) and "role" not in data
    except Exception:
        return False


def _looks_like_jsonl_transcript(path: Path) -> bool:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            return isinstance(obj, dict) and "role" in obj
    except Exception:
        return False
    return False


class TranscriptStore:
    def __init__(self, path: Path, *, db: Optional[SessionDatabase] = None, session_id: Optional[str] = None):
        raw = Path(path)
        if raw.suffix == "" or raw.is_dir():
            self.path = resolve_session_log_path(raw)
        elif raw.name in (LEGACY_TRANSCRIPT_NAME, LEGACY_SESSION_JSON, SESSION_LOG_NAME):
            self.path = resolve_session_log_path(raw.parent)
        else:
            self.path = raw
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[List[TranscriptMessage]] = None
        self._db = db
        self._session_id = session_id

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self._cache = []
        if self._db and self._session_id:
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
        role_e = MessageRole(role) if not isinstance(role, MessageRole) else role
        text = content or ""
        if role_e == MessageRole.ASSISTANT:
            from app.agent.speech_guard import looks_like_raw_error, sanitize_spoken

            if looks_like_raw_error(text):
                text = sanitize_spoken(text)
        msg = TranscriptMessage(
            role=role_e,
            content=text,
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
        """全量历史（含所有 compaction），用于落盘审计与压缩输入。"""
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

    def load_for_context(self, keep_turns: int = 5) -> List[TranscriptMessage]:
        """模型可见窗口：最新 compaction + 最近 keep_turns 轮。"""
        return select_context_window(self.load(), keep_turns=keep_turns)

    def rewrite(self, messages: Iterable[TranscriptMessage]) -> None:
        """仅用于损坏恢复/测试重建；正常压缩路径禁止调用。"""
        msgs = list(messages)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for m in msgs:
                f.write(m.model_dump_json(ensure_ascii=False) + "\n")
        tmp.replace(self.path)
        self._cache = msgs
        if self._db and self._session_id:
            self._db.replace_messages(self._session_id, msgs)

    def total_chars(self) -> int:
        return sum(m.approx_chars() for m in self.load())

    def context_chars(self, keep_turns: int = 5) -> int:
        return sum(m.approx_chars() for m in self.load_for_context(keep_turns=keep_turns))

    def hint(self, limit: int = 8) -> str:
        msgs = self.load_for_context(keep_turns=max(1, (limit + 1) // 2))
        parts = []
        for m in msgs[-limit:]:
            if m.role == MessageRole.COMPACTION:
                parts.append(f"[compact]{m.content[:180]}")
            else:
                parts.append(f"{m.role.value}:{m.content[:120]}")
        return " | ".join(parts)
