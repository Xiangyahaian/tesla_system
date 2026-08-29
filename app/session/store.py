# -*- coding: utf-8 -*-
"""用户目录 + 多会话隔离。

每个登录用户 = 独立目录 + 独立 vehicle.json（一辆车）+ 独立 memory/画像。
同一用户下的多个对话会话共享这辆车，但 transcript/turns 各自隔离。

state/sessions/<user_id>/
  vehicle.json                 # 用户级车况（与其它用户完全隔离）
  memory/ ...
  sessions/<session_id>/       # 每段对话单独落盘
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
from app.agent.transcript import SESSION_LOG_NAME, TranscriptStore, resolve_session_log_path
from app.agent.types import MessageRole
from app.gateway.stub import StubVehicleGateway
from app.models import PendingAction
from app.session.db import SessionDatabase, default_session_title, get_session_db


@dataclass
class SessionData:
    session_id: str
    user_id: str
    root: Path
    user_root: Path
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
        self._user_gateways: Dict[str, StubVehicleGateway] = {}
        self._user_memories: Dict[str, MemoryStore] = {}
        self._lock = threading.RLock()
        self.db = db or get_session_db()
        self.assembler = ContextAssembler()
        self.compactor = ContextCompactor(
            soft_limit_chars=config.AGENT_SOFT_CONTEXT_CHARS,
            hard_limit_chars=config.AGENT_HARD_CONTEXT_CHARS,
            keep_recent_turns=config.AGENT_KEEP_RECENT_TURNS,
            keep_recent=config.AGENT_KEEP_RECENT_MESSAGES,
        )
        self.db.ensure_session("default", title="默认会话")
        try:
            self.db.migrate_users_from_sessions()
        except Exception:
            pass
        try:
            self._migrate_all_legacy_dirs()
        except Exception:
            pass

    def _safe_id(self, session_id: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:64] or "default"

    def _user_id_for(self, session_id: str) -> str:
        sid = self._safe_id(session_id)
        try:
            owner = (self.db.session_owner_id(sid) or "").strip()
            if owner:
                return self._safe_id(owner)
        except Exception:
            pass
        try:
            user = self.db.get_user_by_session(sid)
            if user:
                return self._safe_id(str(user.get("id") or user.get("session_id") or sid))
        except Exception:
            pass
        return sid

    def _user_root(self, user_id: str) -> Path:
        d = self.root / self._safe_id(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _session_dir(self, session_id: str, user_id: Optional[str] = None) -> Path:
        uid = self._safe_id(user_id or self._user_id_for(session_id))
        sid = self._safe_id(session_id)
        d = self._user_root(uid) / "sessions" / sid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _user_gateway(self, user_id: str) -> StubVehicleGateway:
        uid = self._safe_id(user_id)
        gw = self._user_gateways.get(uid)
        if gw is None:
            path = self._user_root(uid) / "vehicle.json"
            is_new = not path.exists()
            gw = StubVehicleGateway(path)
            if is_new:
                gw.reset()
            self._user_gateways[uid] = gw
        return gw

    def _user_memory(self, user_id: str) -> MemoryStore:
        uid = self._safe_id(user_id)
        mem = self._user_memories.get(uid)
        if mem is None:
            mem = MemoryStore(self._user_root(uid))
            self._user_memories[uid] = mem
        return mem

    def _move_file(self, src: Path, dst: Path) -> None:
        if not src.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dst.exists() and src.resolve() == dst.resolve():
                return
        except Exception:
            pass
        if dst.exists():
            return
        try:
            shutil.move(str(src), str(dst))
        except Exception:
            try:
                if src.is_file():
                    dst.write_bytes(src.read_bytes())
                    src.unlink(missing_ok=True)
            except Exception:
                pass

    def _migrate_legacy_flat_json(self, session_id: str, user_root: Path) -> None:
        legacy = self.root / f"{self._safe_id(session_id)}.json"
        vehicle = user_root / "vehicle.json"
        if legacy.exists() and not vehicle.exists():
            self._move_file(legacy, vehicle)

    def _migrate_session_layout(self, session_id: str, user_id: str) -> None:
        """把旧的平铺 state/sessions/<id>/ 迁到用户目录/sessions/<id>/。"""
        sid = self._safe_id(session_id)
        uid = self._safe_id(user_id)
        user_root = self._user_root(uid)
        sess_dir = self._session_dir(sid, uid)
        self._migrate_legacy_flat_json(sid, user_root)

        conversation_names = (
            "transcript.jsonl",
            "turns.jsonl",
            "session.jsonl",
            "session.json",
            "session.meta.json",
        )

        # 主会话：对话文件曾和车况/画像挤在用户根目录
        if uid == sid:
            for name in conversation_names:
                self._move_file(user_root / name, sess_dir / name)
            return

        legacy = self.root / sid
        if not legacy.exists() or not legacy.is_dir():
            return
        try:
            if legacy.resolve() == user_root.resolve():
                for name in conversation_names:
                    self._move_file(user_root / name, sess_dir / name)
                return
        except Exception:
            pass

        extra_vehicle = legacy / "vehicle.json"
        user_vehicle = user_root / "vehicle.json"
        if extra_vehicle.exists():
            take_extra = not user_vehicle.exists()
            if not take_extra:
                try:
                    take_extra = extra_vehicle.stat().st_mtime > user_vehicle.stat().st_mtime
                except Exception:
                    take_extra = False
            if take_extra:
                if user_vehicle.exists():
                    bak = user_root / "vehicle.json.bak"
                    try:
                        if bak.exists():
                            bak.unlink()
                        user_vehicle.replace(bak)
                    except Exception:
                        pass
                try:
                    shutil.move(str(extra_vehicle), str(user_vehicle))
                except Exception:
                    self._move_file(extra_vehicle, user_vehicle)
        if not (user_root / "memory").exists() and (legacy / "memory").is_dir():
            try:
                shutil.move(str(legacy / "memory"), str(user_root / "memory"))
            except Exception:
                pass
        for name in conversation_names:
            self._move_file(legacy / name, sess_dir / name)
        nested = legacy / "sessions" / sid
        if nested.is_dir():
            for name in conversation_names:
                self._move_file(nested / name, sess_dir / name)
        shutil.rmtree(legacy, ignore_errors=True)

    def _migrate_all_legacy_dirs(self) -> None:
        if not self.root.exists():
            return
        seen: set[str] = set()
        for u in self.db.list_users(limit=200):
            uid = str(u.get("id") or u.get("session_id") or "").strip()
            if uid:
                self._migrate_session_layout(uid, uid)
                seen.add(uid)
        for it in self.db.list_sessions(include_deleted=True):
            sid = str(it.get("session_id") or "").strip()
            if not sid:
                continue
            uid = str(it.get("owner_id") or "").strip() or self._user_id_for(sid)
            self._migrate_session_layout(sid, uid)
            seen.add(sid)
        for d in list(self.root.iterdir()):
            if not d.is_dir() or d.name in seen:
                continue
            if (d / "sessions").is_dir() and not (d / "transcript.jsonl").exists():
                continue
            if (
                (d / "transcript.jsonl").exists()
                or (d / "session.jsonl").exists()
                or (d / "vehicle.json").exists()
                or (d / "session.json").exists()
            ):
                self._migrate_session_layout(d.name, d.name)

    def _bind_user_runtime(self, sess: SessionData) -> None:
        """每用户独立车况/画像；同一用户的多个会话共享一辆车。"""
        uid = self._safe_id(self._user_id_for(sess.session_id))
        sess.user_id = uid
        sess.user_root = self._user_root(uid)
        gw = self._user_gateway(uid)
        mem = self._user_memory(uid)
        if sess.gateway is not gw:
            sess.gateway = gw
        if sess.memory is not mem:
            sess.memory = mem

    def get(self, session_id: str = "default", *, touch: bool = True) -> SessionData:
        with self._lock:
            self._purge_expired()
            sid = self._safe_id(session_id)
            if sid not in self._sessions:
                uid = self._user_id_for(sid)
                self._migrate_session_layout(sid, uid)
                sdir = self._session_dir(sid, uid)
                meta = self.db.ensure_session(sid, owner_id=uid if uid != sid else None)
                owner = str(meta.get("owner_id") or uid or "").strip()
                if owner:
                    uid = self._safe_id(owner)
                    sdir = self._session_dir(sid, uid)
                user_root = self._user_root(uid)
                gw = self._user_gateway(uid)
                mem = self._user_memory(uid)
                resolve_session_log_path(sdir)
                tr = TranscriptStore(sdir / SESSION_LOG_NAME, db=self.db, session_id=sid)
                traces = TraceStore(sdir / "turns.jsonl", db=self.db, session_id=sid)
                sess = SessionData(
                    session_id=sid,
                    user_id=uid,
                    root=sdir,
                    user_root=user_root,
                    gateway=gw,
                    transcript=tr,
                    memory=mem,
                    traces=traces,
                    title=str(meta.get("title") or ("默认会话" if sid == "default" else "新会话")),
                )
                self._load_session_meta(sess)
                if uid and not sess.slots.get("user_id"):
                    sess.slots["user_id"] = uid
                self._sessions[sid] = sess
            sess = self._sessions[sid]
            self._bind_user_runtime(sess)
            if touch:
                sess.touch()
                self.db.touch(sid)
            return sess

    def _session_log_path(self, sess: SessionData) -> Path:
        """对话 JSONL：session.jsonl。"""
        return sess.root / SESSION_LOG_NAME

    def _load_session_meta(self, sess: SessionData) -> None:
        """元数据只从 SQLite 读；兼容旧整文件元数据。"""
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
            # 若 SQLite 已有实质数据则返回
            if sess.slots or data.get("title") or data.get("pending") is not None:
                return
        except Exception:
            pass

        # 兼容：旧元数据文件（非 JSONL）
        for name in ("session.meta.json",):
            path = sess.root / name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict) or "role" in data:
                continue
            sess.slots = data.get("slots") or sess.slots
            sess.last_active = float(data.get("last_active") or sess.last_active or time.time())
            sess.compact_failures = int(data.get("compact_failures") or sess.compact_failures)
            pending = data.get("pending")
            if pending:
                try:
                    sess.pending = PendingAction.model_validate(pending)
                except Exception:
                    pass
            sess.memory_compat = data.get("memory") or sess.memory_compat

    def save(self, sess: SessionData) -> None:
        """会话元数据只写 SQLite；对话内容在 transcript.append / compaction 追加。"""
        self.db.upsert_meta(
            sess.session_id,
            slots=sess.slots,
            pending=sess.pending,
            memory_compat=sess.memory_compat[-20:],
            compact_failures=sess.compact_failures,
            transcript_chars=sess.transcript.total_chars(),
            title=sess.title,
        )
        if sess.user_id:
            try:
                self.db.set_session_owner(sess.session_id, sess.user_id)
            except Exception:
                pass

    def reset(self, session_id: str = "default") -> Dict[str, Any]:
        sess = self.get(session_id)
        state = sess.gateway.reset()
        sess.slots.clear()
        if sess.user_id:
            sess.slots["user_id"] = sess.user_id
        sess.pending = None
        sess.memory_compat.clear()
        sess.compact_failures = 0
        sess.transcript.clear()
        sess.traces.clear()
        # 重置话题/车况时保留用户画像（三份 md）
        self.db.clear_session_content(sess.session_id)
        if sess.session_id == "default":
            sess.title = "默认会话"
            self.db.rename_session(sess.session_id, "默认会话")
        elif self.is_home_session(sess.session_id):
            nick = str((sess.slots or {}).get("nickname") or sess.title or "主会话")
            sess.title = nick
            self.db.rename_session(sess.session_id, nick)
        else:
            sess.title = "新会话"
            self.db.rename_session(sess.session_id, "新会话")
        self.save(sess)
        return state

    def nickname_to_session_id(self, nickname: str) -> str:
        """用户主会话 ID：可读拼音/英文 slug，避免纯中文变成 u_user_<hash>。"""
        import hashlib
        import re

        from pypinyin import lazy_pinyin

        nick = (nickname or "").strip()[:24]
        if not nick:
            raise ValueError("昵称不能为空")

        parts: list[str] = []
        for ch in nick:
            if ch.isascii() and ch.isalnum():
                parts.append(ch.lower())
            elif "\u4e00" <= ch <= "\u9fff":
                parts.extend(lazy_pinyin(ch))
        slug = re.sub(r"[^a-z0-9]+", "", "".join(parts))[:28] or "user"
        candidate = self._safe_id(f"u_{slug}")

        # 同拼音不同昵称：短后缀消歧，仍可读
        existing = self.db.get_user_by_session(candidate)
        if existing:
            other = str(existing.get("nickname") or "")
            if SessionDatabase.nickname_key(other) != SessionDatabase.nickname_key(nick):
                digest = hashlib.sha1(nick.encode("utf-8")).hexdigest()[:4]
                candidate = self._safe_id(f"u_{slug}_{digest}")
        return candidate

    def ensure_user(self, nickname: str) -> SessionData:
        """按昵称得到稳定用户目录；同昵称复用。登录写入 SQLite users。"""
        nick = (nickname or "").strip()[:24]
        if not nick:
            raise ValueError("昵称不能为空")
        existing = self.db.get_user_by_nickname(nick)
        sid = existing["session_id"] if existing else self.nickname_to_session_id(nick)
        with self._lock:
            user = self.db.upsert_user_login(nick, sid)
            uid = str(user["id"] or sid)
            try:
                self.db.set_session_owner(user["session_id"], uid)
            except Exception:
                pass
            sess = self.get(user["session_id"])
            self._bind_user_runtime(sess)
            sess.title = user["nickname"]
            sess.slots["nickname"] = user["nickname"]
            sess.slots["user_id"] = uid
            try:
                from app.agent.memory import PreferenceDelta

                prefs = sess.memory.load_preferences()
                if prefs.get("display_name") != user["nickname"]:
                    sess.memory.upsert_preferences(
                        PreferenceDelta(display_name=user["nickname"])
                    )
            except Exception:
                pass
            self.save(sess)
            return sess

    def list_users(self) -> List[Dict[str, Any]]:
        """列出 SQLite users 表中的昵称用户。"""
        from app.auth import is_admin_nickname

        out: List[Dict[str, Any]] = []
        for u in self.db.list_users(limit=200):
            uid = str(u.get("id") or "")
            owned = self.db.list_sessions(owner_id=uid) if uid else []
            nick = str(u.get("nickname") or "")
            out.append(
                {
                    "id": uid,
                    "session_id": u["session_id"],
                    "nickname": nick,
                    "title": u.get("title") or nick,
                    "created_at": u.get("created_at"),
                    "last_login_at": u.get("last_login_at"),
                    "login_count": u.get("login_count", 0),
                    "updated_at": u.get("updated_at") or u.get("last_login_at"),
                    "session_count": len(owned),
                    "is_admin": is_admin_nickname(nick),
                    "user_dir": str(self.root / uid) if uid else "",
                }
            )
        return out

    def delete_user_account(self, user_id: str) -> Dict[str, Any]:
        """管理员删除一个普通用户：用户记录 + 其全部会话目录。管理员自己不可删。"""
        from app.auth import is_admin_nickname

        uid = (user_id or "").strip()
        if not uid:
            return {"ok": False, "error": "用户不存在"}
        user = self.db.get_user_by_id(uid) or self.db.get_user_by_session(uid)
        if not user:
            return {"ok": False, "error": "用户不存在"}
        nick = str(user.get("nickname") or "")
        if is_admin_nickname(nick):
            return {"ok": False, "error": "管理员账号不可删除"}
        home = str(user.get("session_id") or uid)
        owner = str(user.get("id") or uid)
        sids = {home, owner}
        for it in self.db.list_sessions(owner_id=owner):
            sid = str(it.get("session_id") or "")
            if sid:
                sids.add(sid)
        deleted: List[str] = []
        with self._lock:
            self.db.delete_user(nick)
            for sid in sids:
                if not sid or sid == "default":
                    continue
                self._hard_delete_session(sid)
                deleted.append(sid)
            user_root = self.root / self._safe_id(owner)
            if user_root.exists() and user_root.is_dir():
                shutil.rmtree(user_root, ignore_errors=True)
            self._user_gateways.pop(self._safe_id(owner), None)
            self._user_memories.pop(self._safe_id(owner), None)
        return {"ok": True, "nickname": nick, "user_id": owner, "deleted": deleted, "count": len(deleted)}

    def _maybe_evict_user_runtime(self, user_id: str) -> None:
        uid = self._safe_id(user_id)
        if any(s.user_id == uid for s in self._sessions.values()):
            return
        self._user_gateways.pop(uid, None)
        self._user_memories.pop(uid, None)

    def _hard_delete_session(self, sid: str) -> None:
        sid = self._safe_id(sid)
        cached = self._sessions.pop(sid, None)
        uid = cached.user_id if cached else self._user_id_for(sid)
        self.db.delete_session(sid, hard=True)
        sess_dir = self.root / self._safe_id(uid) / "sessions" / sid
        if sess_dir.exists() and sess_dir.is_dir():
            shutil.rmtree(sess_dir, ignore_errors=True)
        legacy = self.root / sid
        user_root = self.root / self._safe_id(uid)
        try:
            same = legacy.exists() and legacy.resolve() == user_root.resolve()
        except Exception:
            same = False
        if legacy.exists() and legacy.is_dir() and not same:
            shutil.rmtree(legacy, ignore_errors=True)
        self._maybe_evict_user_runtime(uid)

    def create_session(self, title: Optional[str] = None, owner_id: Optional[str] = None) -> SessionData:
        with self._lock:
            name = (title or "").strip() or default_session_title()
            sid = self.db.create_session(title=name, owner_id=owner_id)
            if owner_id:
                try:
                    self.db.set_session_owner(sid, owner_id)
                except Exception:
                    pass
            sess = self.get(sid)
            sess.title = name
            if owner_id:
                sess.user_id = self._safe_id(owner_id)
                sess.slots["user_id"] = owner_id
            self._bind_user_runtime(sess)
            # 新建会话 = 从北理南门、车速 0 重新起步（车况与用户绑定，多会话共享同一 gateway）
            sess.gateway.reset()
            sess.slots.pop("nav_candidates", None)
            sess.slots.pop("nav_clarify_query", None)
            sess.pending = None
            self.save(sess)
            return sess

    def is_home_session(self, session_id: str) -> bool:
        return bool(self.db.get_user_by_session(self._safe_id(session_id)))

    def list_sessions(self, owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        items = self.db.list_sessions(owner_id=owner_id)
        home_ids = {u["session_id"] for u in self.db.list_users(limit=200)}
        for it in items:
            sid = it["session_id"]
            uid = str(it.get("owner_id") or "").strip() or self._user_id_for(sid)
            it["path"] = str(self.root / uid / "sessions" / sid)
            it["user_dir"] = str(self.root / uid)
            it["has_vehicle"] = True
            it["has_transcript"] = int(it.get("message_count") or 0) > 0
            it["is_home"] = sid in home_ids
        return items

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
        if self.is_home_session(sid):
            return {"ok": False, "error": "登录主会话不可删除，可新建其它会话或重置当前"}
        with self._lock:
            if sid in self._sessions:
                try:
                    self.save(self._sessions[sid])
                except Exception:
                    pass
            self._hard_delete_session(sid)
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
                deleted.append(sid)
            users_n = self.db.delete_all_users()
            if self.root.exists():
                for d in list(self.root.iterdir()):
                    if d.is_dir() and d.name != "default":
                        shutil.rmtree(d, ignore_errors=True)
                        if d.name not in deleted:
                            deleted.append(d.name)
            self._sessions.clear()
            self._user_gateways.clear()
            self._user_memories.clear()
            self.reset("default")
            return {
                "ok": True,
                "deleted": deleted,
                "count": len(deleted),
                "users_cleared": users_n,
            }

    def maybe_compact(self, sess: SessionData, llm=None, force: bool = False):
        """追加式压缩：不覆盖 session.jsonl，只在末尾 append 一条 compaction。"""
        msgs = sess.transcript.load()
        if not force and not self.compactor.should_compact(msgs, force=False):
            return None
        compact_msg, report = self.compactor.build_append_compaction(
            msgs, llm=llm, force=force
        )
        if compact_msg is None:
            if report.thrash_count:
                sess.compact_failures = report.thrash_count
                self.save(sess)
            return report if report.layers else None
        sess.transcript.append(
            MessageRole.COMPACTION,
            compact_msg.content,
            **(compact_msg.meta or {}),
        )
        if report.thrash_count:
            sess.compact_failures = report.thrash_count
        else:
            sess.compact_failures = 0
        self.save(sess)
        return report

    def assemble_context(self, sess: SessionData, extra_user: str = ""):
        return self.assembler.assemble(
            sess.memory,
            sess.transcript,
            sess.gateway.snapshot(),
            extra_user=extra_user,
            keep_turns=config.AGENT_KEEP_RECENT_TURNS,
        )

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_active > config.SESSION_TTL_SEC]
        for sid in expired:
            try:
                self.save(self._sessions[sid])
            except Exception:
                pass
            sess = self._sessions.pop(sid, None)
            if sess is not None:
                self._maybe_evict_user_runtime(sess.user_id)


_STORE: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _STORE
    if _STORE is None:
        _STORE = SessionStore()
    return _STORE
