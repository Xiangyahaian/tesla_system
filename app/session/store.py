# -*- coding: utf-8 -*-
"""会话隔离：车况 + transcript + 记忆 + pending（Claude Code 风格目录布局）。

state/sessions/<id>/
  vehicle.json
  transcript.jsonl
  turns.jsonl           # 每轮 Agent 轨迹
  session.json
  CABIN.md
  memory/MEMORY.md
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import config
from app.agent.compact import ContextCompactor
from app.agent.context import ContextAssembler
from app.agent.memory import MemoryStore
from app.agent.trace import TraceStore
from app.agent.transcript import TranscriptStore
from app.agent.types import MessageRole
from app.gateway.stub import StubVehicleGateway
from app.models import PendingAction


@dataclass
class SessionData:
    session_id: str
    root: Path
    gateway: StubVehicleGateway
    transcript: TranscriptStore
    memory: MemoryStore
    traces: TraceStore
    slots: Dict[str, Any] = field(default_factory=dict)
    pending: Optional[PendingAction] = None
    # 兼容旧字段：派生自 transcript，勿再当作唯一真相
    memory_compat: List[Dict[str, str]] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    compact_failures: int = 0

    def touch(self) -> None:
        self.last_active = time.time()

    def add_memory(self, role: str, text: str, limit: int = 12) -> None:
        """兼容旧 orchestrator 调用；同时写入 transcript。"""
        self.transcript.append(role, text[:2000])
        self.memory_compat.append({"role": role, "text": text[:200]})
        if len(self.memory_compat) > limit:
            self.memory_compat = self.memory_compat[-limit:]


class SessionStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root or config.SESSIONS_DIR)
        self.root.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, SessionData] = {}
        self._lock = threading.RLock()
        self.assembler = ContextAssembler()
        self.compactor = ContextCompactor(
            soft_limit_chars=config.AGENT_SOFT_CONTEXT_CHARS,
            hard_limit_chars=config.AGENT_HARD_CONTEXT_CHARS,
            keep_recent=config.AGENT_KEEP_RECENT_MESSAGES,
        )

    def _safe_id(self, session_id: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:64] or "default"

    def _session_dir(self, session_id: str) -> Path:
        d = self.root / self._safe_id(session_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _migrate_legacy_flat_json(self, session_id: str, session_dir: Path) -> None:
        """旧布局 state/sessions/default.json → default/vehicle.json"""
        legacy = self.root / f"{self._safe_id(session_id)}.json"
        vehicle = session_dir / "vehicle.json"
        if legacy.exists() and not vehicle.exists():
            try:
                shutil.move(str(legacy), str(vehicle))
            except Exception:
                try:
                    vehicle.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass

    def get(self, session_id: str = "default") -> SessionData:
        with self._lock:
            self._purge_expired()
            if session_id not in self._sessions:
                sdir = self._session_dir(session_id)
                self._migrate_legacy_flat_json(session_id, sdir)
                gw = StubVehicleGateway(sdir / "vehicle.json")
                tr = TranscriptStore(sdir / "transcript.jsonl")
                mem = MemoryStore(sdir)
                traces = TraceStore(sdir / "turns.jsonl")
                sess = SessionData(
                    session_id=session_id,
                    root=sdir,
                    gateway=gw,
                    transcript=tr,
                    memory=mem,
                    traces=traces,
                )
                self._load_session_json(sess)
                self._sessions[session_id] = sess
            sess = self._sessions[session_id]
            sess.touch()
            return sess

    def _session_json_path(self, sess: SessionData) -> Path:
        return sess.root / "session.json"

    def _load_session_json(self, sess: SessionData) -> None:
        path = self._session_json_path(sess)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        sess.slots = data.get("slots") or {}
        sess.last_active = float(data.get("last_active") or time.time())
        sess.compact_failures = int(data.get("compact_failures") or 0)
        pending = data.get("pending")
        if pending:
            try:
                sess.pending = PendingAction.model_validate(pending)
            except Exception:
                sess.pending = None
        # 兼容旧 memory 列表
        sess.memory_compat = data.get("memory") or []

    def save(self, sess: SessionData) -> None:
        path = self._session_json_path(sess)
        payload = {
            "session_id": sess.session_id,
            "slots": sess.slots,
            "pending": sess.pending.model_dump() if sess.pending else None,
            "memory": sess.memory_compat[-20:],
            "last_active": sess.last_active,
            "compact_failures": sess.compact_failures,
            "transcript_chars": sess.transcript.total_chars(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def reset(self, session_id: str = "default") -> Dict[str, Any]:
        sess = self.get(session_id)
        state = sess.gateway.reset()
        sess.slots.clear()
        sess.pending = None
        sess.memory_compat.clear()
        sess.compact_failures = 0
        sess.transcript.clear()
        sess.traces.clear()
        # 保留 CABIN.md，清空 auto memory 内容但保留文件头
        from app.agent.memory import DEFAULT_MEMORY_MD

        sess.memory.memory_md.write_text(DEFAULT_MEMORY_MD, encoding="utf-8")
        self.save(sess)
        return state

    def list_sessions(self) -> List[Dict[str, Any]]:
        items = []
        for d in sorted(self.root.iterdir() if self.root.exists() else []):
            if not d.is_dir():
                continue
            sid = d.name
            turns_path = d / "turns.jsonl"
            tr_path = d / "transcript.jsonl"
            turn_n = 0
            if turns_path.exists():
                turn_n = sum(1 for line in turns_path.read_text(encoding="utf-8").splitlines() if line.strip())
            items.append(
                {
                    "session_id": sid,
                    "path": str(d),
                    "turn_count": turn_n,
                    "has_vehicle": (d / "vehicle.json").exists(),
                    "has_transcript": tr_path.exists(),
                }
            )
        return items

    def maybe_compact(self, sess: SessionData, llm=None, force: bool = False):
        msgs = sess.transcript.load()
        if not force and self.compactor.total_chars(msgs) < config.AGENT_SOFT_CONTEXT_CHARS:
            return None
        new_msgs, report = self.compactor.compact(msgs, llm=llm, force_auto=force)
        if report.layers:
            sess.transcript.rewrite(new_msgs)
            if report.thrash_count:
                sess.compact_failures = report.thrash_count
            self.save(sess)
        return report

    def assemble_context(self, sess: SessionData, extra_user: str = ""):
        return self.assembler.assemble(
            sess.memory,
            sess.transcript,
            sess.gateway.snapshot(),
            extra_user=extra_user,
        )

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_active > config.SESSION_TTL_SEC]
        for sid in expired:
            try:
                self.save(self._sessions[sid])
            except Exception:
                pass
            self._sessions.pop(sid, None)


_STORE: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _STORE
    if _STORE is None:
        _STORE = SessionStore()
    return _STORE
