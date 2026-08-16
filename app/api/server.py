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
from app.models import ChatRequest, ControlRequest, ModelStatus, ToolCall
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
    return {
        **ModelStatus(
            remote_available=remote.available,
            local_available=local_ok,
            local_model_name=config.VLLM_MODEL_NAME,
        ).model_dump(),
        "speech": {
            "asr_model": config.ASR_MODEL,
            "tts_model": config.TTS_MODEL,
            "tts_voice": config.TTS_VOICE,
            "tts_rate": getattr(config, "TTS_RATE", 1.12),
            "bailian_configured": bool(config.BAILIAN_API_KEY),
        },
        "maps": {
            "amap_configured": bool(config.AMAP_MAPS_API_KEY),
            "js_key_configured": bool(config.AMAP_JS_KEY),
        },
    }


@app.get("/api/maps/config", response_class=JSONResponse)
async def maps_config():
    """前端高德 JS API 配置（Web 端 Key + 可选安全密钥）。"""
    from app.maps import BIT_ZHONGGUANCUN_SOUTH_GATE, amap_configured

    return {
        "ok": True,
        "provider": "amap",
        "mcp_url": "https://mcp.amap.com/mcp",
        "configured": amap_configured(),
        "js_key": config.AMAP_JS_KEY or "",
        "security_code": config.AMAP_JS_SECURITY_CODE or "",
        "origin": BIT_ZHONGGUANCUN_SOUTH_GATE,
    }


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


@app.get("/api/sessions")
async def list_sessions():
    store = get_session_store()
    return {"ok": True, "sessions": store.list_sessions()}


@app.post("/api/users/login")
async def user_login(request: Request):
    """用户管理：昵称登录 → SQLite users 记录 + 独立 session / Auto Memory。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    nickname = str((body or {}).get("nickname") or "").strip()
    if not nickname:
        return JSONResponse({"ok": False, "error": "请填写昵称"}, status_code=400)
    if len(nickname) > 24:
        return JSONResponse({"ok": False, "error": "昵称最多 24 个字"}, status_code=400)
    store = get_session_store()
    try:
        sess = store.ensure_user(nickname)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    user = store.db.get_user_by_session(sess.session_id) or {}
    return {
        "ok": True,
        "nickname": user.get("nickname") or nickname,
        "session_id": sess.session_id,
        "title": sess.title,
        "user": user,
        "users": store.list_users(),
    }


@app.get("/api/users")
async def list_users():
    store = get_session_store()
    return {"ok": True, "users": store.list_users()}


@app.post("/api/sessions")
async def create_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = str((body or {}).get("title") or "").strip() or None
    store = get_session_store()
    sess = store.create_session(title=title)
    return {
        "ok": True,
        "session_id": sess.session_id,
        "title": sess.title,
        "sessions": store.list_sessions(),
    }


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = str((body or {}).get("title") or "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "title 不能为空"}, status_code=400)
    store = get_session_store()
    if not store.rename_session(session_id, title):
        return JSONResponse({"ok": False, "error": "会话不存在或无法重命名"}, status_code=404)
    return {"ok": True, "session_id": session_id, "title": title, "sessions": store.list_sessions()}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    store = get_session_store()
    result = store.delete_session(session_id)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return {**result, "sessions": store.list_sessions()}


@app.post("/api/sessions/purge")
async def purge_all_sessions():
    """清空全部用户会话与昵称用户，仅保留重置后的 default。"""
    store = get_session_store()
    result = store.purge_all_sessions()
    return {**result, "sessions": store.list_sessions(), "users": store.list_users()}


@app.get("/api/sessions/{session_id}/messages")
async def session_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    store = get_session_store()
    sess = store.get(session_id)
    # 优先 SQLite，保证与文件双写一致
    from app.session.db import get_session_db

    db = get_session_db()
    rows = db.list_messages(session_id, limit=limit, offset=offset)
    total = db.count_messages(session_id)
    if total == 0:
        msgs = sess.transcript.load()
        total = len(msgs)
        slice_ = msgs[offset : offset + limit]
        rows = [m.model_dump() for m in slice_]
    meta = db.load_meta(session_id)
    return {
        "ok": True,
        "session_id": session_id,
        "title": meta.get("title") or sess.title,
        "total": total,
        "offset": offset,
        "limit": limit,
        "messages": [{k: v for k, v in m.items() if k != "_total"} for m in rows],
    }


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


@app.get("/agent-console", response_class=HTMLResponse)
async def agent_console_legacy(request: Request):
    """旧版 HTML Agent Console；React HMI 使用 /agent。"""
    path = config.WEBUI_DIR / "agent.html"
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>agent.html missing</h1>", status_code=404)


@app.get("/apps", response_class=HTMLResponse)
@app.get("/agent", response_class=HTMLResponse)
@app.get("/settings", response_class=HTMLResponse)
async def cabin_spa_routes():
    """React Router 深链接：回落至 HMI index.html。"""
    if HAS_CABIN_HMI and config.PREFER_CABIN_HMI:
        return FileResponse(CABIN_DIST / "index.html")
    return HTMLResponse("<h1>Cabin HMI not built. Run: cd frontend && npm run build</h1>", status_code=404)


@app.post("/api/reset")
async def reset_state(session_id: str = Query("default")):
    store = get_session_store()
    store.reset(session_id)
    sess = store.get(session_id)
    # 不在此推进动力学：重置瞬间必须保持南门 + 车速 0，由前端 tick 再起步
    return {"success": True, "message": "会话状态已重置", "state": sess.gateway.snapshot()}


@app.post("/api/control")
async def control_vehicle(req: ControlRequest):
    """中控 HMI 直接执行工具，写回车辆状态。"""
    reg = get_registry()
    if not reg.get(req.tool):
        return JSONResponse({"ok": False, "error": f"未知工具: {req.tool}"}, status_code=400)
    store = get_session_store()
    sess = store.get(req.session_id)
    call = ToolCall(name=req.tool, arguments=req.arguments or {})
    result = reg.execute(sess.gateway, call)
    if req.tool == "driving.set_adas" and (req.arguments or {}).get("enable"):
        sess.gateway.tick_dynamics(0.35)
    if req.tool == "driving.set_speed" and float((req.arguments or {}).get("speed_kmh") or 0) > 0:
        sess.gateway.tick_dynamics(0.35)
    if req.tool in {"navigation.navigate_to", "navigation.start"} and result.success:
        sess.gateway.tick_dynamics(0.35)
    store.save(sess)
    return {
        "ok": bool(result.success),
        "message": result.message,
        "data": result.data,
        "tool": req.tool,
        "state": sess.gateway.snapshot(),
    }


@app.post("/api/dynamics/tick")
async def dynamics_tick(session_id: str = Query("default"), dt: float = Query(0.25)):
    store = get_session_store()
    sess = store.get(session_id)
    result = sess.gateway.tick_dynamics(dt)
    store.save(sess)
    return {
        "ok": True,
        "message": result.get("message"),
        "data": result.get("data"),
        "state": sess.gateway.snapshot(),
    }


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


@app.post("/api/asr")
async def asr_endpoint(request: Request):
    """千问语音识别：上传音频文件字段 audio。"""
    form = await request.form()
    upload = form.get("audio")
    if upload is None:
        return JSONResponse({"ok": False, "error": "缺少 audio 字段"}, status_code=400)
    raw = await upload.read() if hasattr(upload, "read") else None
    if not raw:
        return JSONResponse({"ok": False, "error": "音频为空"}, status_code=400)

    filename = getattr(upload, "filename", "") or "audio.webm"
    fmt = (filename.rsplit(".", 1)[-1] if "." in filename else "webm").lower()
    content_type = getattr(upload, "content_type", "") or ""
    if "wav" in content_type:
        fmt = "wav"
    elif "mpeg" in content_type or "mp3" in content_type:
        fmt = "mp3"
    elif "ogg" in content_type:
        fmt = "ogg"
    elif "mp4" in content_type or "m4a" in content_type or "aac" in content_type:
        fmt = "mp4"
    # Safari 常上传 .mp4 / .m4a
    if fmt in ("m4a", "aac", "caf"):
        fmt = "mp4"

    try:
        from app.speech import transcribe_audio

        text = await asyncio.to_thread(transcribe_audio, raw, format=fmt, language="zh")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)

    return {"ok": True, "text": text, "model": config.ASR_MODEL}


@app.post("/api/tts")
async def tts_endpoint(request: Request):
    """CosyVoice 女声情感合成，返回 base64 音频。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "无效 JSON"}, status_code=400)

    text = str((body or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text 为空"}, status_code=400)

    voice = (body or {}).get("voice") or None
    emotion = (body or {}).get("emotion") or None
    try:
        from app.speech import synthesize_speech

        audio, mime, meta = await asyncio.to_thread(
            synthesize_speech, text, voice=voice, emotion=emotion
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)

    import base64

    return {
        "ok": True,
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "mime": mime,
        "model": config.TTS_MODEL,
        "voice": meta.get("voice") or voice or config.TTS_VOICE,
        "emotion": meta.get("emotion"),
    }


@app.post("/api/tts/stream")
async def tts_stream_endpoint(request: Request):
    """SSE 流式 TTS：默认 PCM 首包可播，前端边下边播。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "无效 JSON"}, status_code=400)

    text = str((body or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text 为空"}, status_code=400)

    voice = (body or {}).get("voice") or None
    emotion = (body or {}).get("emotion") or None
    fmt = str((body or {}).get("format") or "pcm").strip().lower() or "pcm"
    if fmt not in ("pcm", "mp3", "wav"):
        fmt = "pcm"

    from app.speech import iter_synthesize_stream

    def event_gen():
        for ev in iter_synthesize_stream(text, voice=voice, emotion=emotion, format=fmt):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )



@app.get("/manual")
async def manual(download: int = Query(0)):
    if config.PDF_PATH.exists():
        headers = {}
        if download:
            headers["Content-Disposition"] = 'attachment; filename="Tesla_Manual.pdf"'
        return FileResponse(
            config.PDF_PATH,
            media_type="application/pdf",
            headers=headers,
            filename="Tesla_Manual.pdf" if download else None,
        )
    return JSONResponse({"error": "PDF not found", "path": str(config.PDF_PATH)}, status_code=404)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    orch = get_orchestrator()

    async def event_gen():
        try:
            for ev in orch.handle(
                req.query,
                req.session_id,
                req.model,
                req.confirm,
                active_seat=req.active_seat,
            ):
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
