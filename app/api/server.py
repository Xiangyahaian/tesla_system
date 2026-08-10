# -*- coding: utf-8 -*-
"""Cabin Runtime FastAPI 入口。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# 保证项目根在 path 中
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config
from app.llm.client import get_llm
from app.models import ChatRequest, ModelStatus
from app.orchestrator.runtime import get_orchestrator
from app.session.store import get_session_store
from app.tools.registry import get_registry

app = FastAPI(title="Tesla Cabin Runtime", version="3.0.0")
# legacy webui 模板
templates = Jinja2Templates(directory=str(config.WEBUI_DIR))
CABIN_DIST = config.FRONTEND_DIST
HAS_CABIN_HMI = CABIN_DIST.exists() and (CABIN_DIST / "index.html").exists()


@app.on_event("startup")
async def startup():
    config.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    get_registry()
    if config.RESET_ON_STARTUP:
        get_session_store().reset("default")

    if config.RAG_ENABLE and config.RAG_WARMUP_ON_STARTUP:
        try:
            from app.rag.service import get_rag_service

            get_rag_service().warmup()
        except Exception as e:
            print(f"[RAG] 启动预热失败（知识问答可能首问较慢）: {e}")

    print(f"[CabinRuntime] ready on http://{config.HOST}:{config.PORT}")
    if HAS_CABIN_HMI and config.PREFER_CABIN_HMI:
        print(f"[CabinRuntime] HMI: {CABIN_DIST}")
        print(f"[CabinRuntime] Legacy UI: /legacy")
    else:
        print(f"[CabinRuntime] UI: {config.WEBUI_DIR / 'index.html'}")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if HAS_CABIN_HMI and config.PREFER_CABIN_HMI:
        return FileResponse(CABIN_DIST / "index.html")
    index_path = config.WEBUI_DIR / "index.html"
    if index_path.exists():
        return templates.TemplateResponse("index.html", {"request": request})
    return HTMLResponse("<h1>UI missing. Build frontend or restore webui/index.html</h1>", status_code=404)


@app.get("/legacy", response_class=HTMLResponse)
async def legacy_ui(request: Request):
    index_path = config.WEBUI_DIR / "index.html"
    if index_path.exists():
        return templates.TemplateResponse("index.html", {"request": request})
    return HTMLResponse("<h1>legacy webui missing</h1>", status_code=404)


@app.get("/api/model-status", response_class=JSONResponse)
async def model_status():
    remote = get_llm("remote")
    local_ok = False
    try:
        local_ok = get_llm("local").available
    except Exception:
        local_ok = False
    return ModelStatus(
        remote_available=remote.available,
        local_available=local_ok,
        local_model_name=config.VLLM_MODEL_NAME,
    ).model_dump()


@app.get("/api/state")
async def get_state(session_id: str = Query("default")):
    sess = get_session_store().get(session_id)
    return {
        "session_id": session_id,
        "state": sess.gateway.snapshot(),
        "pending": sess.pending.model_dump() if sess.pending else None,
        "slots": sess.slots,
        "agent": {
            "transcript_chars": sess.transcript.total_chars(),
            "transcript_messages": len(sess.transcript.load()),
            "memory_preview": sess.memory.load_auto_memory(max_lines=30)[:500],
            "session_dir": str(sess.root),
        },
    }


@app.get("/api/agent/context")
async def agent_context(session_id: str = Query("default")):
    store = get_session_store()
    sess = store.get(session_id)
    bundle = store.assemble_context(sess)
    return {
        "session_id": session_id,
        "sources": bundle.sources,
        "total_chars": bundle.total_chars,
        "recent_dialog": bundle.recent_dialog[-2000:],
        "user_context_preview": bundle.user_context[:3000],
    }


@app.post("/api/agent/compact")
async def agent_compact(session_id: str = Query("default"), model: str = Query("remote")):
    store = get_session_store()
    sess = store.get(session_id)
    llm = get_llm(model)
    report = store.maybe_compact(sess, llm=llm, force=True)
    return {
        "session_id": session_id,
        "report": report.model_dump() if report else {"layers": [], "note": "nothing_to_compact"},
        "transcript_chars": sess.transcript.total_chars(),
    }


@app.get("/api/agent/sessions")
async def agent_sessions():
    return {"sessions": get_session_store().list_sessions()}


@app.get("/api/agent/history")
async def agent_history(
    session_id: str = Query("default"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    sess = get_session_store().get(session_id)
    turns = sess.traces.list_turns(limit=limit, offset=offset)
    return {
        "session_id": session_id,
        "total_returned": len(turns),
        "turns": turns,
    }


@app.get("/api/agent/turns/{turn_id}")
async def agent_turn(turn_id: str, session_id: str = Query("default")):
    sess = get_session_store().get(session_id)
    turn = sess.traces.get_turn(turn_id)
    if not turn:
        return JSONResponse({"error": "turn not found", "turn_id": turn_id}, status_code=404)
    return turn.model_dump()


@app.get("/api/agent/transcript")
async def agent_transcript(
    session_id: str = Query("default"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    sess = get_session_store().get(session_id)
    msgs = sess.transcript.load()
    slice_ = msgs[offset : offset + limit]
    return {
        "session_id": session_id,
        "total": len(msgs),
        "offset": offset,
        "limit": limit,
        "messages": [m.model_dump() for m in slice_],
    }


@app.get("/agent", response_class=HTMLResponse)
async def agent_console(request: Request):
    path = config.WEBUI_DIR / "agent.html"
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>agent.html missing</h1>", status_code=404)


@app.post("/api/reset")
async def reset_state(session_id: str = Query("default")):
    state = get_session_store().reset(session_id)
    return {"success": True, "message": "会话状态已重置", "state": state}


@app.post("/api/reset-state")
async def reset_state_compat():
    """兼容原 webui/index.html 的重置按钮。"""
    state = get_session_store().reset("default")
    return {"success": True, "message": "状态与记忆已重置", "detail": {"state_reset": True}, "state": state}


@app.get("/api/apps")
async def list_installed_apps(category: str = Query(None)):
    """模拟车机已安装应用目录（App API）。"""
    from app.gateway.apps_catalog import INSTALLED_APPS, list_apps

    apps = list_apps(category=category or None)
    return {
        "count": len(apps),
        "apps": apps,
        "categories": sorted({a.get("category", "other") for a in INSTALLED_APPS}),
        "note": "模拟已安装应用；通过 apps.launch 打开/关闭",
    }


@app.get("/api/tools")
async def list_tools():
    reg = get_registry()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "risk": t.risk.value,
                "domain": t.domain,
                "schema": t.args_model.model_json_schema(),
            }
            for t in reg.list_tools()
        ]
    }


@app.get("/api/image")
async def get_image(path: str):
    try:
        from src.utils import convert_db_path_to_local, to_absolute_path

        local_path = to_absolute_path(convert_db_path_to_local(path))
    except Exception:
        local_path = path
    if os.path.exists(local_path):
        return FileResponse(local_path)
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse(status_code=404, content="not found")


@app.get("/manual")
async def manual():
    if config.PDF_PATH.exists():
        return FileResponse(config.PDF_PATH, media_type="application/pdf")
    return JSONResponse({"error": "PDF not found", "path": str(config.PDF_PATH)}, status_code=404)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    orch = get_orchestrator()

    async def event_gen():
        try:
            for ev in orch.handle(req.query, req.session_id, req.model, req.confirm):
                yield json.dumps({"type": ev.type, "data": ev.data}, ensure_ascii=False) + "\n"
                # 仅让出事件循环以便立刻刷出，不加人为延时
                await asyncio.sleep(0)
        except Exception as e:
            yield json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_gen(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# React 座舱静态资源（Vite build → frontend/dist）
if HAS_CABIN_HMI:
    assets_dir = CABIN_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="cabin-assets")


def main():
    uvicorn.run("app.api.server:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
