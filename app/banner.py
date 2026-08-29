# -*- coding: utf-8 -*-
"""Startup log line for Cabin Runtime."""
from __future__ import annotations


def print_banner() -> None:
    from app import __version__, config

    dist = config.FRONTEND_DIST
    hmi_ok = dist.exists() and (dist / "index.html").exists()
    host = "127.0.0.1" if config.HOST in {"0.0.0.0", "::"} else config.HOST
    url = f"http://{host}:{config.PORT}"
    hmi = "ok" if hmi_ok else "missing (run: cd frontend && npm run build)"

    print(
        f"Tesla System v{__version__}  listening on {config.HOST}:{config.PORT}  "
        f"({url})  hmi={hmi}",
        flush=True,
    )
