# -*- coding: utf-8 -*-
"""千问 ASR：qwen3-asr-flash（OpenAI 兼容 chat/completions）。"""
from __future__ import annotations

import base64
import json
from typing import Optional
from urllib import error, request

from app import config

_MIME = {
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "mp4": "audio/mp4",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
}


def _mime_for(fmt: str) -> str:
    key = (fmt or "webm").lower().lstrip(".")
    return _MIME.get(key, f"audio/{key}")


def transcribe_audio(
    audio_bytes: bytes,
    *,
    format: str = "webm",
    language: Optional[str] = "zh",
) -> str:
    """将音频识别为文本。失败抛 RuntimeError。"""
    if not config.BAILIAN_API_KEY:
        raise RuntimeError("未配置 BAILIAN_API_KEY，无法使用语音识别")
    if not audio_bytes:
        raise RuntimeError("音频为空")

    b64 = base64.b64encode(audio_bytes).decode("ascii")
    mime = _mime_for(format)
    data_uri = f"data:{mime};base64,{b64}"

    body: dict = {
        "model": config.ASR_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": {"data": data_uri}},
                ],
            }
        ],
    }
    if language:
        # 部分版本支持 asr_options；不支持时服务端会忽略
        body["asr_options"] = {"language": language}

    url = f"{config.BAILIAN_API_BASE.rstrip('/')}/chat/completions"
    req = request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.BAILIAN_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        raise RuntimeError("语音识别暂时不可用") from e
    except Exception as e:
        raise RuntimeError("语音识别暂时不可用") from e

    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError("ASR 响应格式异常") from e

    return (text or "").strip()
