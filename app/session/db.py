# -*- coding: utf-8 -*-
"""SQLite 会话库：用户 / 元数据 / 消息 / 轨迹的权威索引。

文件目录（用户级 vehicle.json / memory，会话级 transcript）仍保留；
SQLite 负责用户登录记录、会话列表、对话回放、跨重启一致性与 CRUD。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app import config


def default_session_title(now: Optional[float] = None) -> str:
    """新建会话的默认标题：会话 YYYY-MM-DD HH:MM。"""
    from datetime import datetime

    return datetime.fromtimestamp(now if now is not None else time.time()).strftime("会话 %Y-%m-%d %H:%M")


def is_placeholder_title(title: str) -> bool:
    t = (title or "").strip()
    if t in {"新会话", "默认会话"}:
        return True
    return t.startswith("会话 ") and len(t) <= 22

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '新会话',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  last_active REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  compact_failures INTEGER NOT NULL DEFAULT 0,
  transcript_chars INTEGER NOT NULL DEFAULT 0,
  message_count INTEGER NOT NULL DEFAULT 0,
  turn_count INTEGER NOT NULL DEFAULT 0,
  preview TEXT NOT NULL DEFAULT '',
  slots_json TEXT NOT NULL DEFAULT '{}',
  pending_json TEXT,
  memory_compat_json TEXT NOT NULL DEFAULT '[]',
  owner_id TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  ts REAL NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS turns (
  turn_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  query TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT 'remote',
  started_at REAL NOT NULL,
  ended_at REAL,
  intent TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'running',
  answer_preview TEXT NOT NULL DEFAULT '',
  tool_names_json TEXT NOT NULL DEFAULT '[]',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  steps_json TEXT NOT NULL DEFAULT '[]',
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  nickname TEXT NOT NULL,
  nickname_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL UNIQUE,
  created_at REAL NOT NULL,
  last_login_at REAL NOT NULL,
  login_count INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session_ts ON messages(session_id, ts, id);
CREATE INDEX IF NOT EXISTS idx_turns_session_started ON turns(session_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_last_login ON users(last_login_at DESC);
"""


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj if obj is not None else {}, ensure_ascii=False)


def _json_loads(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


class SessionDatabase:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or getattr(config, "SESSION_DB_PATH", None) or (config.STATE_DIR / "cabin_sessions.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        with self._conn:
            self._conn.executescript(_SCHEMA)
        self._migrate_owner_column()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _now(self) -> float:
        return time.time()

    def _migrate_owner_column(self) -> None:
        """已有库补 owner_id，并把登录主会话挂到对应用户。"""
        with self._lock:
            cols = [r[1] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()]
            if "owner_id" not in cols:
                self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_id TEXT")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_owner ON sessions(owner_id)"
            )
            self._conn.execute(
                """
                UPDATE sessions
                SET owner_id = (
                  SELECT id FROM users WHERE users.session_id = sessions.id
                )
                WHERE owner_id IS NULL OR owner_id = ''
                """
            )
            self._conn.commit()

    def set_session_owner(self, session_id: str, owner_id: str) -> None:
        sid = (session_id or "").strip()
        oid = (owner_id or "").strip()
        if not sid or not oid:
            return
        with self._lock:
            self.ensure_session(sid)
            self._conn.execute(
                "UPDATE sessions SET owner_id = ? WHERE id = ?",
                (oid, sid),
            )
            self._conn.commit()

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        uid = (user_id or "").strip()
        if not uid:
            return None
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
            return self._row_to_user(row) if row else None

    def session_owner_id(self, session_id: str) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT owner_id FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return ""
            return str(row["owner_id"] or "").strip()

    def ensure_session(
        self,
        session_id: str,
        *,
        title: Optional[str] = None,
        created_at: Optional[float] = None,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row:
                if owner_id and not (row["owner_id"] if "owner_id" in row.keys() else None):
                    self._conn.execute(
                        "UPDATE sessions SET owner_id = ? WHERE id = ?",
                        (owner_id, session_id),
                    )
                    self._conn.commit()
                    row = self._conn.execute(
                        "SELECT * FROM sessions WHERE id = ?", (session_id,)
                    ).fetchone()
                return dict(row)
            now = created_at or self._now()
            self._conn.execute(
                """
                INSERT INTO sessions (
                  id, title, created_at, updated_at, last_active, status, owner_id
                ) VALUES (?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    session_id,
                    title or ("默认会话" if session_id == "default" else "新会话"),
                    now,
                    now,
                    now,
                    owner_id,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return dict(row)

    def touch(self, session_id: str) -> None:
        now = self._now()
        with self._lock:
            self.ensure_session(session_id)
            self._conn.execute(
                "UPDATE sessions SET last_active = ?, updated_at = ? WHERE id = ?",
                (now, now, session_id),
            )
            self._conn.commit()

    def upsert_meta(
        self,
        session_id: str,
        *,
        slots: Optional[dict] = None,
        pending: Any = None,
        memory_compat: Optional[list] = None,
        compact_failures: Optional[int] = None,
        transcript_chars: Optional[int] = None,
        title: Optional[str] = None,
        preview: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.ensure_session(session_id)
            now = self._now()
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            msg_n = self._conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (session_id,)
            ).fetchone()["c"]
            turn_n = self._conn.execute(
                "SELECT COUNT(*) AS c FROM turns WHERE session_id = ?", (session_id,)
            ).fetchone()["c"]

            new_title = title if title is not None else row["title"]
            new_preview = preview if preview is not None else row["preview"]
            new_slots = _json_dumps(slots if slots is not None else _json_loads(row["slots_json"], {}))
            if pending is None and "pending_json" in row.keys():
                pending_json = row["pending_json"]
            else:
                pending_json = None if pending is None else _json_dumps(
                    pending.model_dump() if hasattr(pending, "model_dump") else pending
                )
            mem = memory_compat if memory_compat is not None else _json_loads(row["memory_compat_json"], [])
            cf = compact_failures if compact_failures is not None else row["compact_failures"]
            tc = transcript_chars if transcript_chars is not None else row["transcript_chars"]

            self._conn.execute(
                """
                UPDATE sessions SET
                  title = ?, updated_at = ?, last_active = ?,
                  compact_failures = ?, transcript_chars = ?,
                  message_count = ?, turn_count = ?, preview = ?,
                  slots_json = ?, pending_json = ?, memory_compat_json = ?
                WHERE id = ?
                """,
                (
                    new_title,
                    now,
                    now,
                    int(cf or 0),
                    int(tc or 0),
                    int(msg_n),
                    int(turn_n),
                    new_preview or "",
                    new_slots,
                    pending_json,
                    _json_dumps(mem[-20:] if isinstance(mem, list) else []),
                    session_id,
                ),
            )
            self._conn.commit()

    def load_meta(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            self.ensure_session(session_id)
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            data = dict(row)
            return {
                "session_id": data["id"],
                "title": data["title"],
                "slots": _json_loads(data["slots_json"], {}),
                "pending": _json_loads(data["pending_json"], None),
                "memory": _json_loads(data["memory_compat_json"], []),
                "last_active": data["last_active"],
                "compact_failures": data["compact_failures"],
                "transcript_chars": data["transcript_chars"],
                "created_at": data["created_at"],
                "updated_at": data["updated_at"],
                "preview": data["preview"],
                "message_count": data["message_count"],
                "turn_count": data["turn_count"],
                "status": data["status"],
            }

    def list_sessions(self, include_deleted: bool = False, owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            sql = """
                SELECT s.*, u.nickname AS owner_nickname
                FROM sessions s
                LEFT JOIN users u ON u.id = s.owner_id
                WHERE 1=1
            """
            params: List[Any] = []
            if not include_deleted:
                sql += " AND s.status != 'deleted'"
            if owner_id:
                sql += " AND s.owner_id = ?"
                params.append(owner_id)
            sql += " ORDER BY s.updated_at DESC"
            rows = self._conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                out.append(
                    {
                        "session_id": r["id"],
                        "title": r["title"],
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                        "last_active": r["last_active"],
                        "status": r["status"],
                        "message_count": r["message_count"],
                        "turn_count": r["turn_count"],
                        "transcript_chars": r["transcript_chars"],
                        "preview": r["preview"],
                        "owner_id": r["owner_id"] if "owner_id" in r.keys() else "",
                        "owner_nickname": r["owner_nickname"] if "owner_nickname" in r.keys() else "",
                    }
                )
            return out

    def create_session(self, title: Optional[str] = None, owner_id: Optional[str] = None) -> str:
        sid = f"s{time.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        self.ensure_session(sid, title=title or default_session_title(), owner_id=owner_id)
        return sid

    def rename_session(self, session_id: str, title: str) -> bool:
        title = (title or "").strip()[:80]
        if not title:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ? AND status != 'deleted'",
                (title, self._now(), session_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_session(self, session_id: str, *, hard: bool = True) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                return False
            if hard:
                self._conn.execute("DELETE FROM users WHERE session_id = ?", (session_id,))
                self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                self._conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
                self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            else:
                self._conn.execute(
                    "UPDATE sessions SET status = 'deleted', updated_at = ? WHERE id = ?",
                    (self._now(), session_id),
                )
            self._conn.commit()
            return True

    def delete_all_users(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM users")
            self._conn.commit()
            return int(cur.rowcount or 0)

    def clear_session_content(self, session_id: str) -> None:
        with self._lock:
            self.ensure_session(session_id)
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
            self._conn.execute(
                """
                UPDATE sessions SET
                  message_count = 0, turn_count = 0, transcript_chars = 0,
                  preview = '', pending_json = NULL, memory_compat_json = '[]',
                  compact_failures = 0, updated_at = ?, last_active = ?
                WHERE id = ?
                """,
                (self._now(), self._now(), session_id),
            )
            self._conn.commit()

    def replace_messages(self, session_id: str, messages: Iterable[Any]) -> None:
        with self._lock:
            self.ensure_session(session_id)
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            preview = ""
            total_chars = 0
            n = 0
            for m in messages:
                role = m.role.value if hasattr(m.role, "value") else str(m.role)
                content = m.content or ""
                ts = float(getattr(m, "ts", 0) or self._now())
                meta = getattr(m, "meta", {}) or {}
                self._conn.execute(
                    """
                    INSERT INTO messages (session_id, role, content, ts, meta_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, role, content, ts, _json_dumps(meta)),
                )
                n += 1
                total_chars += len(content)
                if role in {"user", "assistant"} and content.strip():
                    preview = content.strip()[:120]
            self._conn.execute(
                """
                UPDATE sessions SET message_count = ?, transcript_chars = ?, preview = ?,
                  updated_at = ?, last_active = ? WHERE id = ?
                """,
                (n, total_chars, preview, self._now(), self._now(), session_id),
            )
            self._conn.commit()

    def append_message(self, session_id: str, role: str, content: str, ts: float, meta: Optional[dict] = None) -> None:
        with self._lock:
            self.ensure_session(session_id)
            self._conn.execute(
                """
                INSERT INTO messages (session_id, role, content, ts, meta_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content or "", float(ts), _json_dumps(meta or {})),
            )
            preview = content.strip()[:120] if role in {"user", "assistant"} and content.strip() else None
            if preview:
                self._conn.execute(
                    """
                    UPDATE sessions SET
                      message_count = message_count + 1,
                      transcript_chars = transcript_chars + ?,
                      preview = ?, updated_at = ?, last_active = ?
                    WHERE id = ?
                    """,
                    (len(content or ""), preview, self._now(), self._now(), session_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE sessions SET
                      message_count = message_count + 1,
                      transcript_chars = transcript_chars + ?,
                      updated_at = ?, last_active = ?
                    WHERE id = ?
                    """,
                    (len(content or ""), self._now(), self._now(), session_id),
                )
            # 首条用户消息自动命名（跳过主会话：主会话在列表里显示为「主会话」）
            row = self._conn.execute(
                "SELECT title, message_count FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            home = self._conn.execute(
                "SELECT 1 FROM users WHERE session_id = ?", (session_id,)
            ).fetchone()
            if (
                row
                and not home
                and role == "user"
                and content.strip()
                and is_placeholder_title(str(row["title"] or ""))
                and int(row["message_count"] or 0) <= 2
            ):
                auto = content.strip().replace("\n", " ")[:28]
                self._conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?", (auto, session_id)
                )
            self._conn.commit()

    def list_messages(self, session_id: str, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT role, content, ts, meta_json FROM messages
                WHERE session_id = ?
                ORDER BY ts ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()
            total = self._conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (session_id,)
            ).fetchone()["c"]
            msgs = [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "ts": r["ts"],
                    "meta": _json_loads(r["meta_json"], {}),
                }
                for r in rows
            ]
            # attach total via side channel is awkward; caller can count
            for m in msgs:
                m["_total"] = total
            return msgs

    def count_messages(self, session_id: str) -> int:
        with self._lock:
            return int(
                self._conn.execute(
                    "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (session_id,)
                ).fetchone()["c"]
            )

    def append_turn(self, session_id: str, turn: Any) -> None:
        data = turn.model_dump() if hasattr(turn, "model_dump") else dict(turn)
        with self._lock:
            self.ensure_session(session_id)
            self._conn.execute(
                """
                INSERT OR REPLACE INTO turns (
                  turn_id, session_id, query, model, started_at, ended_at,
                  intent, status, answer_preview, tool_names_json, metrics_json, steps_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("turn_id"),
                    session_id,
                    data.get("query") or "",
                    data.get("model") or "remote",
                    float(data.get("started_at") or self._now()),
                    data.get("ended_at"),
                    data.get("intent") or "",
                    data.get("status") or "ok",
                    (data.get("answer_preview") or "")[:300],
                    _json_dumps(data.get("tool_names") or []),
                    _json_dumps(data.get("metrics") or {}),
                    _json_dumps(data.get("steps") or []),
                ),
            )
            self._conn.execute(
                """
                UPDATE sessions SET
                  turn_count = (SELECT COUNT(*) FROM turns WHERE session_id = ?),
                  updated_at = ?, last_active = ?
                WHERE id = ?
                """,
                (session_id, self._now(), self._now(), session_id),
            )
            self._conn.commit()

    def list_turns(self, session_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM turns WHERE session_id = ?
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()
            out = []
            for r in rows:
                started = float(r["started_at"] or 0)
                ended = float(r["ended_at"] or started)
                out.append(
                    {
                        "turn_id": r["turn_id"],
                        "session_id": r["session_id"],
                        "query": r["query"],
                        "model": r["model"],
                        "started_at": started,
                        "ended_at": r["ended_at"],
                        "duration_ms": int((ended - started) * 1000),
                        "intent": r["intent"],
                        "status": r["status"],
                        "step_count": len(_json_loads(r["steps_json"], [])),
                        "tool_names": _json_loads(r["tool_names_json"], []),
                        "answer_preview": r["answer_preview"],
                        "metrics": _json_loads(r["metrics_json"], {}),
                    }
                )
            return out

    def get_turn(self, session_id: str, turn_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM turns WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            if not r:
                return None
            return {
                "turn_id": r["turn_id"],
                "session_id": r["session_id"],
                "query": r["query"],
                "model": r["model"],
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
                "intent": r["intent"],
                "status": r["status"],
                "answer_preview": r["answer_preview"],
                "tool_names": _json_loads(r["tool_names_json"], []),
                "metrics": _json_loads(r["metrics_json"], {}),
                "steps": _json_loads(r["steps_json"], []),
            }

    @staticmethod
    def nickname_key(nickname: str) -> str:
        return (nickname or "").strip().casefold()

    def _row_to_user(self, r: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": r["id"],
            "nickname": r["nickname"],
            "session_id": r["session_id"],
            "created_at": r["created_at"],
            "last_login_at": r["last_login_at"],
            "login_count": int(r["login_count"] or 0),
            "updated_at": r["last_login_at"],
            "title": r["nickname"],
        }

    def get_user_by_nickname(self, nickname: str) -> Optional[Dict[str, Any]]:
        key = self.nickname_key(nickname)
        if not key:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE nickname_key = ?", (key,)
            ).fetchone()
            return self._row_to_user(row) if row else None

    def get_user_by_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE session_id = ?", (session_id,)
            ).fetchone()
            return self._row_to_user(row) if row else None

    def upsert_user_login(self, nickname: str, session_id: str) -> Dict[str, Any]:
        """登录或注册：同昵称复用，更新 last_login / login_count。"""
        nick = (nickname or "").strip()[:24]
        key = self.nickname_key(nick)
        if not key:
            raise ValueError("昵称不能为空")
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id 不能为空")
        now = self._now()
        with self._lock:
            self.ensure_session(sid, title=nick)
            row = self._conn.execute(
                "SELECT * FROM users WHERE nickname_key = ?", (key,)
            ).fetchone()
            if row:
                self._conn.execute(
                    """
                    UPDATE users SET
                      nickname = ?, session_id = ?, last_login_at = ?,
                      login_count = login_count + 1
                    WHERE nickname_key = ?
                    """,
                    (nick, sid, now, key),
                )
            else:
                by_sid = self._conn.execute(
                    "SELECT * FROM users WHERE session_id = ?", (sid,)
                ).fetchone()
                if by_sid:
                    self._conn.execute(
                        """
                        UPDATE users SET
                          nickname = ?, nickname_key = ?, last_login_at = ?,
                          login_count = login_count + 1
                        WHERE session_id = ?
                        """,
                        (nick, key, now, sid),
                    )
                else:
                    self._conn.execute(
                        """
                        INSERT INTO users (
                          id, nickname, nickname_key, session_id,
                          created_at, last_login_at, login_count
                        ) VALUES (?, ?, ?, ?, ?, ?, 1)
                        """,
                        (sid, nick, key, sid, now, now),
                    )
            self._conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ?, last_active = ? WHERE id = ?",
                (nick, now, now, sid),
            )
            self._conn.commit()
            out = self._conn.execute(
                "SELECT * FROM users WHERE nickname_key = ?", (key,)
            ).fetchone()
            return self._row_to_user(out)

    def list_users(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM users
                ORDER BY last_login_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit or 50), 200)),),
            ).fetchall()
            return [self._row_to_user(r) for r in rows]

    def delete_user(self, nickname: str) -> bool:
        key = self.nickname_key(nickname)
        if not key:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id FROM users WHERE nickname_key = ?", (key,)
            ).fetchone()
            if not row:
                return False
            self._conn.execute("DELETE FROM users WHERE nickname_key = ?", (key,))
            self._conn.commit()
            return True

    def migrate_users_from_sessions(self) -> int:
        """把已有 u_* 会话补登记到 users（幂等）。"""
        count = 0
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, title, created_at, last_active FROM sessions
                WHERE id GLOB 'u_*' AND status != 'deleted'
                """
            ).fetchall()
            # 清掉误迁移（旧 LIKE 'u_%' 把 ut_* 等扫进来）
            self._conn.execute(
                "DELETE FROM users WHERE session_id NOT GLOB 'u_*'"
            )
            for r in rows:
                sid = r["id"]
                exists = self._conn.execute(
                    "SELECT 1 FROM users WHERE session_id = ?", (sid,)
                ).fetchone()
                if exists:
                    continue
                nick = (r["title"] or sid).strip()[:24] or sid
                key = self.nickname_key(nick)
                # 昵称冲突时带 session 后缀，避免 UNIQUE 失败
                base_key = key
                n = 0
                while self._conn.execute(
                    "SELECT 1 FROM users WHERE nickname_key = ?", (key,)
                ).fetchone():
                    n += 1
                    key = f"{base_key}_{n}"
                    nick = f"{(r['title'] or sid).strip()[:20]}_{n}"
                created = float(r["created_at"] or self._now())
                last = float(r["last_active"] or created)
                self._conn.execute(
                    """
                    INSERT INTO users (
                      id, nickname, nickname_key, session_id,
                      created_at, last_login_at, login_count
                    ) VALUES (?, ?, ?, ?, ?, ?, 1)
                    """,
                    (sid, nick, key, sid, created, last),
                )
                count += 1
            if count:
                self._conn.commit()
        return count

    def migrate_from_filesystem(self, sessions_root: Path) -> int:
        """把已有目录会话灌入 SQLite（幂等：已有消息则跳过灌入）。

        兼容两种布局：
        - 旧：state/sessions/<sid>/{transcript.jsonl,session.jsonl,session.json,...}
        - 新：state/sessions/<user_id>/sessions/<sid>/...
        """
        from app.agent.trace import TurnTrace
        from app.agent.types import TranscriptMessage

        count = 0
        root = Path(sessions_root)
        if not root.exists():
            return 0

        def ingest(d: Path, sid: str, owner_id: Optional[str] = None) -> None:
            nonlocal count
            with self._lock:
                existing = self._conn.execute(
                    "SELECT message_count FROM sessions WHERE id = ?", (sid,)
                ).fetchone()
                if existing and int(existing["message_count"] or 0) > 0:
                    return
            self.ensure_session(
                sid,
                title="默认会话" if sid == "default" else sid,
                owner_id=owner_id,
            )
            sj = d / "session.json"
            if sj.exists():
                try:
                    data = json.loads(sj.read_text(encoding="utf-8"))
                    self.upsert_meta(
                        sid,
                        slots=data.get("slots") or {},
                        pending=data.get("pending"),
                        memory_compat=data.get("memory") or [],
                        compact_failures=int(data.get("compact_failures") or 0),
                        transcript_chars=int(data.get("transcript_chars") or 0),
                    )
                except Exception:
                    pass
            tr = d / "transcript.jsonl"
            if tr.exists():
                msgs = []
                for line in tr.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msgs.append(TranscriptMessage.model_validate_json(line))
                    except Exception:
                        continue
                if msgs:
                    self.replace_messages(sid, msgs)
            turns_path = d / "turns.jsonl"
            if turns_path.exists():
                for line in turns_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        turn = TurnTrace.model_validate_json(line)
                        self.append_turn(sid, turn)
                    except Exception:
                        continue
            count += 1

        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name == "sessions":
                continue
            nested = d / "sessions"
            if nested.is_dir():
                owner = d.name
                for sd in sorted(nested.iterdir()):
                    if sd.is_dir():
                        ingest(sd, sd.name, owner_id=owner)
                if (d / "transcript.jsonl").exists() or (d / "session.json").exists():
                    ingest(d, d.name, owner_id=owner)
            else:
                ingest(d, d.name)
        return count


_DB: Optional[SessionDatabase] = None
_DB_LOCK = threading.Lock()


def get_session_db() -> SessionDatabase:
    global _DB
    with _DB_LOCK:
        if _DB is None:
            _DB = SessionDatabase()
            try:
                _DB.migrate_from_filesystem(config.SESSIONS_DIR)
            except Exception as e:
                print(f"[SessionDB] migrate warning: {e}")
            try:
                n = _DB.migrate_users_from_sessions()
                if n:
                    print(f"[SessionDB] migrated {n} users from sessions")
            except Exception as e:
                print(f"[SessionDB] user migrate warning: {e}")
            _DB.ensure_session("default", title="默认会话")
        return _DB
