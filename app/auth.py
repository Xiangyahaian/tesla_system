# -*- coding: utf-8 -*-
"""座舱身份：昵称登录。历史记录人人只管自己的会话；管理员另有用户管理。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from app import config
from app.session.db import SessionDatabase


def admin_nickname() -> str:
    return (getattr(config, "ADMIN_NICKNAME", None) or "象牙海岸").strip() or "象牙海岸"


def is_admin_nickname(nickname: str) -> bool:
    nick = (nickname or "").strip()
    if not nick:
        return False
    return SessionDatabase.nickname_key(nick) == SessionDatabase.nickname_key(admin_nickname())


def read_actor_session(request: Request, actor: Optional[str] = None) -> str:
    if actor and str(actor).strip():
        return str(actor).strip()
    header = request.headers.get("x-cabin-session") or request.headers.get("X-Cabin-Session") or ""
    return header.strip()


def inspect_actor(session_id: str, store=None) -> Dict[str, Any]:
    sid = (session_id or "").strip()
    empty = {
        "ok": False,
        "nickname": "",
        "session_id": sid,
        "is_admin": False,
        "role": "guest",
        "user": {},
    }
    if not sid:
        return empty
    if store is None:
        from app.session.store import get_session_store

        store = get_session_store()
    user = store.db.get_user_by_session(sid) or store.db.get_user_by_id(store.db.session_owner_id(sid)) or {}
    nick = str(user.get("nickname") or "").strip()
    if not nick:
        return empty
    admin = is_admin_nickname(nick)
    return {
        "ok": True,
        "nickname": nick,
        "session_id": str(user.get("session_id") or sid),
        "is_admin": admin,
        "role": "admin" if admin else "user",
        "user": user,
    }


def visible_sessions(actor_sid: str, store=None) -> List[Dict[str, Any]]:
    """历史记录：登录用户只看到自己的会话（管理员也一样）。"""
    if store is None:
        from app.session.store import get_session_store

        store = get_session_store()
    info = inspect_actor(actor_sid, store=store)
    if not info["ok"]:
        return []
    uid = str((info.get("user") or {}).get("id") or "")
    if not uid:
        return []
    return store.list_sessions(owner_id=uid)


def can_manage_session(actor_sid: str, target_sid: str, store=None) -> bool:
    if store is None:
        from app.session.store import get_session_store

        store = get_session_store()
    info = inspect_actor(actor_sid, store=store)
    if not info["ok"]:
        return False
    if info["is_admin"]:
        return True
    target = (target_sid or "").strip()
    uid = str((info.get("user") or {}).get("id") or "")
    if not target or not uid:
        return False
    if target == info["session_id"]:
        return True
    return store.db.session_owner_id(target) == uid


def deny_unless_logged_in(actor_sid: str, store=None) -> Optional[JSONResponse]:
    info = inspect_actor(actor_sid, store=store)
    if info["ok"]:
        return None
    return JSONResponse({"ok": False, "error": "请先登录"}, status_code=401)


def deny_unless_admin(actor_sid: str, store=None) -> Optional[JSONResponse]:
    info = inspect_actor(actor_sid, store=store)
    if info["is_admin"]:
        return None
    return JSONResponse(
        {"ok": False, "error": "仅管理员可进行此操作", "role": info["role"]},
        status_code=403,
    )


def deny_unless_can_manage(actor_sid: str, target_sid: str, store=None) -> Optional[JSONResponse]:
    if can_manage_session(actor_sid, target_sid, store=store):
        return None
    return JSONResponse({"ok": False, "error": "无权操作该会话"}, status_code=403)


def deny_unless_session_access(actor_sid: str, target_sid: str, store=None) -> Optional[JSONResponse]:
    """登录且有权访问目标会话（同一用户的主会话或其子会话）。"""
    denied = deny_unless_logged_in(actor_sid, store=store)
    if denied:
        return denied
    target = (target_sid or "").strip()
    if not target or target == "default":
        return JSONResponse(
            {"ok": False, "error": "请登录并使用您自己的会话，不能使用共享 default"},
            status_code=403,
        )
    return deny_unless_can_manage(actor_sid, target, store=store)
