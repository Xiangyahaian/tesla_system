# -*- coding: utf-8 -*-
"""CosyVoice TTS：女声 + 情感指令 + SSE 流式（降首包延迟）。"""
from __future__ import annotations

import base64
import json
import re
from typing import Generator, Iterable, Optional, Tuple
from urllib import error, request

from app import config

DASHSCOPE_TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"

# 欢脱元气女，支持 Instruct 情感（happy/sad/…）
DEFAULT_FEMALE_VOICE = "longanhuan"


def infer_emotion(text: str) -> str:
    """根据回复内容挑情感，默认积极陪伴。"""
    t = text or ""
    if re.search(r"(抱歉|失败|连不上|没法|找不到|出错|暂时没有)", t):
        return "sad"
    if re.search(r"(注意|危险|请确认|小心|过高)", t):
        return "surprised"
    if re.search(r"(好了|搞定|找到|推荐|打开|已帮|可以|出发|导航)", t):
        return "happy"
    return "happy"


def build_instruction(emotion: Optional[str] = None, *, scene: str = "闲聊对话") -> str:
    emo = (emotion or "happy").strip() or "happy"
    # longanhuan 固定句式，句末必须有句号
    return f"你说话的角色是温和客服，你说话的情感是{emo}。"


def _clean_text(text: str, limit: int = 160) -> str:
    clean = (text or "").strip()
    clean = re.sub(r"^>.*$", "", clean, flags=re.M)
    clean = re.sub(r"[#*`_]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:limit]


def _tts_body(
    text: str,
    *,
    voice: str,
    format: str,
    sample_rate: int,
    instruction: str,
    rate: float,
) -> dict:
    return {
        "model": config.TTS_MODEL,
        "input": {
            "text": text,
            "voice": voice,
            "format": format,
            "sample_rate": sample_rate,
            "instruction": instruction,
        },
        "parameters": {
            # 略加快语速，座舱听感更利落
            "rate": max(0.8, min(1.35, float(rate))),
            "volume": 55,
        },
    }


def synthesize_speech(
    text: str,
    *,
    voice: Optional[str] = None,
    format: str = "mp3",
    emotion: Optional[str] = None,
    rate: Optional[float] = None,
) -> Tuple[bytes, str, dict]:
    """非流式合成，返回 (audio_bytes, mime_type, meta)。"""
    clean = _clean_text(text, 100)
    if not clean:
        raise RuntimeError("合成文本为空")
    if not config.BAILIAN_API_KEY:
        raise RuntimeError("未配置 BAILIAN_API_KEY，无法使用语音合成")

    use_voice = (voice or config.TTS_VOICE or DEFAULT_FEMALE_VOICE).strip()
    emo = emotion or infer_emotion(clean)
    instruction = build_instruction(emo)
    speech_rate = float(rate if rate is not None else getattr(config, "TTS_RATE", 1.12))

    body = _tts_body(
        clean,
        voice=use_voice,
        format=format,
        sample_rate=24000,
        instruction=instruction,
        rate=speech_rate,
    )
    req = request.Request(
        DASHSCOPE_TTS_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.BAILIAN_API_KEY}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=18) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        # SSE 失败时回退一次非流式（仍用女声+情感，不换男声）
        if "SSE" in detail or e.code >= 400:
            return _synthesize_non_sse(clean, use_voice, format, instruction, speech_rate, emo)
        raise RuntimeError("语音播报暂时不可用") from e
    except Exception as e:
        raise RuntimeError("语音播报暂时不可用") from e

    chunks = list(_iter_sse_audio_b64(raw))
    if chunks:
        audio = b"".join(base64.b64decode(c) for c in chunks if c)
        if audio:
            mime = "audio/mpeg" if format == "mp3" else f"audio/{format}"
            return audio, mime, {"voice": use_voice, "emotion": emo, "instruction": instruction, "streaming": True}

    # SSE 未吐出分片时，再走非流式拿完整音频
    return _synthesize_non_sse(clean, use_voice, format, instruction, speech_rate, emo)


def _synthesize_non_sse(
    clean: str,
    voice: str,
    format: str,
    instruction: str,
    rate: float,
    emotion: str,
) -> Tuple[bytes, str, dict]:
    body = _tts_body(
        clean,
        voice=voice,
        format=format,
        sample_rate=24000,
        instruction=instruction,
        rate=rate,
    )
    req = request.Request(
        DASHSCOPE_TTS_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.BAILIAN_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=18) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    audio = (payload.get("output") or {}).get("audio") or {}
    raw_b64 = (audio.get("data") or "").strip()
    if raw_b64:
        return base64.b64decode(raw_b64), f"audio/{format}", {
            "voice": voice,
            "emotion": emotion,
            "instruction": instruction,
            "streaming": False,
        }
    url = (audio.get("url") or "").strip()
    if not url:
        raise RuntimeError("语音播报暂时不可用")
    with request.urlopen(url, timeout=12) as audio_resp:
        data = audio_resp.read()
    if not data:
        raise RuntimeError("TTS 音频为空")
    return data, f"audio/{format}", {
        "voice": voice,
        "emotion": emotion,
        "instruction": instruction,
        "streaming": False,
    }


def _iter_sse_audio_b64(raw: str) -> Generator[str, None, None]:
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        out = obj.get("output") or obj
        audio = out.get("audio") if isinstance(out, dict) else None
        if isinstance(audio, dict):
            b64 = (audio.get("data") or "").strip()
            if b64:
                yield b64
            continue
        # 兼容其它字段名
        b64 = (out.get("data") or "").strip() if isinstance(out, dict) else ""
        if b64:
            yield b64


def iter_synthesize_stream(
    text: str,
    *,
    voice: Optional[str] = None,
    emotion: Optional[str] = None,
    format: str = "mp3",
    rate: Optional[float] = None,
) -> Iterable[dict]:
    """流式合成：逐片产出 {type, data/...}，供 SSE 推给前端抢先播。"""
    clean = _clean_text(text, 100)
    if not clean:
        yield {"type": "error", "error": "合成文本为空"}
        return
    if not config.BAILIAN_API_KEY:
        yield {"type": "error", "error": "未配置 BAILIAN_API_KEY"}
        return

    use_voice = (voice or config.TTS_VOICE or DEFAULT_FEMALE_VOICE).strip()
    emo = emotion or infer_emotion(clean)
    instruction = build_instruction(emo)
    speech_rate = float(rate if rate is not None else getattr(config, "TTS_RATE", 1.12))
    yield {
        "type": "meta",
        "voice": use_voice,
        "emotion": emo,
        "instruction": instruction,
        "format": format,
        "sample_rate": 24000,
        "mime": "audio/pcm" if format == "pcm" else ("audio/mpeg" if format == "mp3" else f"audio/{format}"),
    }

    body = _tts_body(
        clean,
        voice=use_voice,
        format=format,
        sample_rate=24000,
        instruction=instruction,
        rate=speech_rate,
    )
    req = request.Request(
        DASHSCOPE_TTS_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.BAILIAN_API_KEY}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=18) as resp:
            # 边读边吐，降低首包
            buf = b""
            got = False
            while True:
                chunk = resp.read(2048)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    s = line.decode("utf-8", errors="replace").strip()
                    if not s.startswith("data:"):
                        continue
                    payload = s[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    out = obj.get("output") or obj
                    audio = out.get("audio") if isinstance(out, dict) else None
                    b64 = ""
                    if isinstance(audio, dict):
                        b64 = (audio.get("data") or "").strip()
                    elif isinstance(out, dict):
                        b64 = (out.get("data") or "").strip()
                    if b64:
                        got = True
                        yield {"type": "audio", "data": b64}
            if not got:
                # 流式没拿到分片 → 整包合成兜底（仍女声情感）
                audio, mime, meta = _synthesize_non_sse(
                    clean, use_voice, format, instruction, speech_rate, emo
                )
                yield {
                    "type": "audio",
                    "data": base64.b64encode(audio).decode("ascii"),
                    "mime": mime,
                    **meta,
                }
    except Exception:
        yield {"type": "error", "error": "语音播报暂时不可用"}
        return

    yield {"type": "done"}
