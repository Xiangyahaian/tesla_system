# -*- coding: utf-8 -*-
"""会话包。请从子模块导入，避免循环依赖：
- app.session.store
- app.session.db
"""

__all__ = ["SessionStore", "SessionData", "get_session_store", "get_session_db"]


def __getattr__(name: str):
    if name in {"SessionStore", "SessionData", "get_session_store"}:
        from app.session import store as _store

        return getattr(_store, name)
    if name == "get_session_db":
        from app.session.db import get_session_db

        return get_session_db
    raise AttributeError(name)
