# -*- coding: utf-8 -*-
"""Startup console banner for Cabin Runtime."""
from __future__ import annotations


def print_banner() -> None:
    from app import __version__, config

    dist = config.FRONTEND_DIST
    hmi_ok = dist.exists() and (dist / "index.html").exists()
    browse_host = "127.0.0.1" if config.HOST in {"0.0.0.0", "::"} else config.HOST
    url = f"http://{browse_host}:{config.PORT}"
    hmi = "ready (frontend/dist)" if hmi_ok else "missing — cd frontend && npm run build"

    bar = "─" * 56
    print(
        f"\n"
        f"  {bar}\n"
        f"  Tesla System · Cabin Runtime  v{__version__}\n"
        f"  {bar}\n"
        f"  listen   {config.HOST}:{config.PORT}\n"
        f"  open     {url}\n"
        f"  hmi      {hmi}\n"
        f"  routes   /  ·  /apps  ·  /agent  ·  /settings\n"
        f"  {bar}\n",
        flush=True,
    )
