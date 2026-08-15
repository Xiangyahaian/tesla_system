# -*- coding: utf-8 -*-
"""会话隔离：车况文件 + transcript/turns（JSONL）+ SQLite 索引。

state/sessions/<id>/
  vehicle.json
  transcript.jsonl
  turns.jsonl
  session.json
  CABIN.md
  memory/MEMORY.md

权威会话列表与对话回放：state/cabin_sessions.db（含 users / sessions / messages / turns）
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
from app.session.db import SessionDatabase, get_session_db


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
    memory_compat: List[Dict[str, str]] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    compact_failures: int = 0
    title: str = "新会话"

    def touch(self) -> None:
        self.last_active = time.time()

    def add_memory(self, role: str, text: str, limit: int = 12) -> None:
        """兼容旧 orchestrator 调用；同时写入 transcript。"""
        self.transcript.append(role, text[:2000])
        self.memory_compat.append({"role": role, "text": text[:200]})
        if len(self.memory_compat) > limit:
            self.memory_compat = self.memory_compat[-limit:]


class SessionStore:
    def __init__(self, root: Optional[Path] = None, db: Optional[SessionDatabase] = None):
        self.root = Path(root or config.SESSIONS_DIR)
        self.root.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, SessionData] = {}
        self._lock = threading.RLock()
        self.db = db or get_session_db()
        self.assembler = ContextAssembler()
        self.compactor = ContextCompactor(
            soft_limit_chars=config.AGENT_SOFT_CONTEXT_CHARS,
            hard_limit_chars=config.AGENT_HARD_CONTEXT_CHARS,
            keep_recent=config.AGENT_KEEP_RECENT_MESSAGES,
        )
        self.db.ensure_session("default", title="默认会话")
        try:
            self.db.migrate_users_from_sessions()
        except Exception:
            pass

    def _safe_id(self, session_id: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:64] or "default"

    def _session_dir(self, session_id: str) -> Path:
        d = self.root / self._safe_id(session_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _migrate_legacy_flat_json(self, session_id: str, session_dir: Path) -> None:
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
            sid = self._safe_id(session_id)
            if sid not in self._sessions:
                sdir = self._session_dir(sid)
                self._migrate_legacy_flat_json(sid, sdir)
                meta = self.db.ensure_session(sid)
                gw = StubVehicleGateway(sdir / "vehicle.json")
                tr = TranscriptStore(sdir / "transcript.jsonl", db=self.db, session_id=sid)
                mem = MemoryStore(sdir)
                traces = TraceStore(sdir / "turns.jsonl", db=self.db, session_id=sid)
                sess = SessionData(
                    session_id=sid,
                    root=sdir,
                    gateway=gw,
                    transcript=tr,
                    memory=mem,
                    traces=traces,
                    title=str(meta.get("title") or ("默认会话" if sid == "default" else "新会话")),
                )
                self._load_session_meta(sess)
                self._sessions[sid] = sess
            sess = self._sessions[sid]
            sess.touch()
            self.db.touch(sid)
            return sess

    def _session_json_path(self, sess: SessionData) -> Path:
        return sess.root / "session.json"

    def _load_session_meta(self, sess: SessionData) -> None:
        # 优先 SQLite
        try:
            data = self.db.load_meta(sess.session_id)
            sess.slots = data.get("slots") or {}
            sess.last_active = float(data.get("last_active") or time.time())
            sess.compact_failures = int(data.get("compact_failures") or 0)
            sess.memory_compat = data.get("memory") or []
            sess.title = str(data.get("title") or sess.title)
            pending = data.get("pending")
            if pending:
                try:
                    sess.pending = PendingAction.model_validate(pending)
                except Exception:
                    sess.pending = None
            return
        except Exception:
            pass

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
        sess.memory_compat = data.get("memory") or []

    def save(self, sess: SessionData) -> None:
        path = self._session_json_path(sess)
        payload = {
            "session_id": sess.session_id,
            "title": sess.title,
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
        self.db.upsert_meta(
            sess.session_id,
            slots=sess.slots,
            pending=sess.pending,
            memory_compat=sess.memory_compat[-20:],
            compact_failures=sess.compact_failures,
            transcript_chars=payload["transcript_chars"],
            title=sess.title,
        )

    def reset(self, session_id: str = "default") -> Dict[str, Any]:
        sess = self.get(session_id)
        state = sess.gateway.reset()
        sess.slots.clear()
        sess.pending = None
        sess.memory_compat.clear()
        sess.compact_failures = 0
        sess.transcript.clear()
        sess.traces.clear()
        # Claude Code 同款：重置话题/车况时保留 Auto Memory（preferences.json + MEMORY.md）
        prefs = sess.memory.load_preferences()
        sess.memory.rewrite_memory_md(prefs)
        self.db.clear_session_content(sess.session_id)
        if sess.session_id == "default":
            sess.title = "默认会话"
            self.db.rename_session(sess.session_id, "默认会话")
        else:
            sess.title = "新会话"
            self.db.rename_session(sess.session_id, "新会话")
        self.save(sess)
        return state

    def nickname_to_session_id(self, nickname: str) -> str:
        import hashlib
        import re

        nick = (nickname or "").strip()[:24]
        if not nick:
            raise ValueError("昵称不能为空")
        digest = hashlib.sha1(nick.encode("utf-8")).hexdigest()[:10]
        ascii_part = re.sub(r"[^a-zA-Z0-9]+", "", nick)[:12] or "user"
        return self._safe_id(f"u_{ascii_part}_{digest}")

    def ensure_user(self, nickname: str) -> SessionData:
        """按昵称得到稳定 session（独立记忆目录），同昵称复用；登录写入 SQLite users。"""
        nick = (nickname or "").strip()[:24]
        if not nick:
            raise ValueError("昵称不能为空")
        # 优先读库中已登记用户，保证昵称大小写变体仍落到同一账号
        existing = self.db.get_user_by_nickname(nick)
        sid = existing["session_id"] if existing else self.nickname_to_session_id(nick)
        with self._lock:
            user = self.db.upsert_user_login(nick, sid)
            sess = self.get(user["session_id"])
            sess.title = user["nickname"]
            sess.slots["nickname"] = user["nickname"]
            sess.slots["user_id"] = user["id"]
            try:
                from app.agent.memory import PreferenceDelta

                prefs = sess.memory.load_preferences()
                if prefs.get("display_name") != user["nickname"]:
                    sess.memory.upsert_preferences(
                        PreferenceDelta(display_name=user["nickname"], notes=[f"用户昵称：{user['nickname']}"])
                    )
            except Exception:
                pass
            self.save(sess)
            return sess

    def list_users(self) -> List[Dict[str, Any]]:
        """列出 SQLite users 表中的昵称用户。"""
        out: List[Dict[str, Any]] = []
        for u in self.db.list_users():
            out.append(
                {
                    "id": u.get("id"),
                    "session_id": u["session_id"],
                    "nickname": u["nickname"],
                    "title": u.get("title") or u["nickname"],
                    "created_at": u.get("created_at"),
                    "last_login_at": u.get("last_login_at"),
                    "login_count": u.get("login_count", 0),
                    "updated_at": u.get("updated_at") or u.get("last_login_at"),
                }
            )
        return out

    def create_session(self, title: Optional[str] = None) -> SessionData:
        with self._lock:
            sid = self.db.create_session(title=title or "新会话")
            # 预创建目录与空车况
            sess = self.get(sid)
            sess.title = title or "新会话"
            self.save(sess)
            return sess

    def rename_session(self, session_id: str, title: str) -> bool:
        ok = self.db.rename_session(self._safe_id(session_id), title)
        if ok:
            sid = self._safe_id(session_id)
            if sid in self._sessions:
                self._sessions[sid].title = title.strip()[:80]
                self.save(self._sessions[sid])
        return ok

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        sid = self._safe_id(session_id)
        if sid == "default":
            return {"ok": False, "error": "默认会话不可删除，可使用重置"}
        with self._lock:
            if sid in self._sessions:
                try:
                    self.save(self._sessions[sid])
                except Exception:
                    pass
                self._sessions.pop(sid, None)
            self.db.delete_session(sid, hard=True)
            sdir = self.root / sid
            if sdir.exists() and sdir.is_dir():
                shutil.rmtree(sdir, ignore_errors=True)
            return {"ok": True, "session_id": sid}

    def purge_all_sessions(self) -> Dict[str, Any]:
        """删除全部用户会话与用户记录，仅保留并重置 default。"""
        with self._lock:
            items = self.db.list_sessions(include_deleted=True)
            deleted: List[str] = []
            for it in items:
                sid = str(it.get("session_id") or "")
                if not sid or sid == "default":
                    continue
                self._sessions.pop(sid, None)
                self.db.delete_session(sid, hard=True)
                sdir = self.root / sid
                if sdir.exists() and sdir.is_dir():
                    shutil.rmtree(sdir, ignore_errors=True)
                deleted.append(sid)
            users_n = self.db.delete_all_users()
            if self.root.exists():
                for d in list(self.root.iterdir()):
                    if d.is_dir() and d.name != "default":
                        shutil.rmtree(d, ignore_errors=True)
                        if d.name not in deleted:
                            deleted.append(d.name)
            # 清空内存缓存后重置默认会话
            self._sessions.clear()
            self.reset("default")
            return {
                "ok": True,
                "deleted": deleted,
                "count": len(deleted),
                "users_cleared": users_n,
            }

    def list_sessions(self) -> List[Dict[str, Any]]:
        items = self.db.list_sessions()
        # 补齐磁盘存在但偶发未入 DB 的目录
        if self.root.exists():
            known = {i["session_id"] for i in items}
            for d in self.root.iterdir():
                if d.is_dir() and d.name not in known:
                    self.db.ensure_session(d.name)
            items = self.db.list_sessions()
        for it in items:
            sid = it["session_id"]
            sdir = self.root / sid
            it["path"] = str(sdir)
            it["has_vehicle"] = (sdir / "vehicle.json").exists()
            it["has_transcript"] = (sdir / "transcript.jsonl").exists() or int(it.get("message_count") or 0) > 0
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
