# -*- coding: utf-8 -*-
"""拦截每一次 POST /v1/chat/completions，把输入输出写成 log/*.json。

文件名与字段对齐现有样例：20260821_102319_169_0006.json
（独立于会话目录）。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app import config

_lock = threading.Lock()
_seq = 0


def _next_seq() -> int:
    global _seq
    with _lock:
        _seq += 1
        return _seq


def flatten_messages(messages: Optional[List[Dict[str, Any]]]) -> str:
    parts: List[str] = []
    for m in messages or []:
        role = str((m or {}).get("role") or "")
        content = (m or {}).get("content")
        if content is None:
            content = ""
        elif not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def _to_plain(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(x) for x in obj]
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return _to_plain(dump())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return _to_plain({k: v for k, v in vars(obj).items() if not k.startswith("_")})
        except Exception:
            return str(obj)
    return str(obj)


def usage_block(usage: Any) -> Dict[str, Any]:
    raw = _to_plain(usage) if usage is not None else {}
    if not isinstance(raw, dict):
        raw = {}
    prompt = int(raw.get("prompt_tokens") or 0)
    completion = int(raw.get("completion_tokens") or 0)
    total = int(raw.get("total_tokens") or 0) or (prompt + completion)
    source = "usage" if (prompt or completion or total) else "none"
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "source": source,
    }


def assistant_text(output: Any) -> str:
    data = _to_plain(output)
    if not isinstance(data, dict):
        return str(output or "")
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    msg = choices[0].get("message") or {}
    if isinstance(msg, dict) and msg.get("content"):
        return str(msg.get("content") or "")
    delta = choices[0].get("delta") or {}
    if isinstance(delta, dict) and delta.get("content"):
        return str(delta.get("content") or "")
    return ""


def parse_sse_completion(raw: bytes) -> Tuple[Dict[str, Any], str]:
    """把 stream=true 的 SSE 拼回一份 chat.completion JSON。"""
    pieces: List[str] = []
    last: Dict[str, Any] = {}
    usage = None
    finish = None
    cid = ""
    model = ""
    text = raw.decode("utf-8", "ignore")
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("data:"):
            continue
        data = s[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        last = obj
        cid = str(obj.get("id") or cid)
        model = str(obj.get("model") or model)
        if obj.get("usage"):
            usage = obj.get("usage")
        for ch in obj.get("choices") or []:
            if not isinstance(ch, dict):
                continue
            if ch.get("finish_reason"):
                finish = ch.get("finish_reason")
            delta = ch.get("delta") if isinstance(ch.get("delta"), dict) else {}
            if delta.get("content"):
                pieces.append(str(delta["content"]))
            msg = ch.get("message") if isinstance(ch.get("message"), dict) else {}
            if msg.get("content") and not delta.get("content"):
                pieces.append(str(msg["content"]))
    full = "".join(pieces)
    output = {
        "id": cid,
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full,
                    "refusal": None,
                    "annotations": None,
                    "audio": None,
                    "function_call": None,
                    "tool_calls": [],
                    "reasoning": None,
                },
                "logprobs": None,
                "finish_reason": finish or ("stop" if full else None),
                "stop_reason": None,
                "token_ids": None,
            }
        ],
        "usage": usage,
    }
    if last.get("created") is not None:
        output["created"] = last.get("created")
    return output, full


def _write_record(record: Dict[str, Any], log_dir: Optional[Path] = None) -> Optional[Path]:
    if not getattr(config, "LLM_LOG_ENABLE", True):
        return None
    root = Path(log_dir or config.LLM_LOG_DIR)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    now = datetime.now()
    seq = _next_seq()
    name = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}_{seq:04d}.json"
    path = root / name
    record.setdefault("time", now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}")
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def write_completion_log(
    *,
    input_obj: Dict[str, Any],
    output_obj: Any,
    elapsed_ms: int,
    status: int,
    method: str = "POST",
    path: str = "/v1/chat/completions",
    client: str = "cabin",
    error: str = "",
    log_dir: Optional[Path] = None,
) -> Optional[Path]:
    messages = input_obj.get("messages") if isinstance(input_obj.get("messages"), list) else []
    out = _to_plain(output_obj) if output_obj is not None else {}
    if not isinstance(out, dict):
        out = {"raw": out}
    if error and not out:
        out = {"error": error}
    text = assistant_text(out) or error
    usage_src = out.get("usage") if isinstance(out, dict) else None
    record = {
        "elapsed_ms": int(elapsed_ms),
        "client": client,
        "method": method,
        "path": path,
        "status": int(status),
        "tokens": usage_block(usage_src),
        "input_text": flatten_messages(messages),
        "output_text": text,
        "input": input_obj,
        "output": out,
    }
    return _write_record(record, log_dir=log_dir)


def log_http_exchange(
    *,
    request: httpx.Request,
    status: int,
    elapsed_ms: int,
    body_bytes: bytes,
    mode: str,
    error: str = "",
    log_dir: Optional[Path] = None,
) -> Optional[Path]:
    try:
        req_json = json.loads(request.content.decode("utf-8") or "{}")
    except Exception:
        req_json = {"raw": (request.content or b"").decode("utf-8", "ignore")}
    if not isinstance(req_json, dict):
        req_json = {"raw": req_json}

    is_stream = bool(req_json.get("stream"))
    output: Any = {}
    if is_stream:
        output, _ = parse_sse_completion(body_bytes or b"")
    elif body_bytes:
        try:
            output = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            output = {"raw": body_bytes.decode("utf-8", "ignore")}
    if error and not assistant_text(output):
        output = dict(output) if isinstance(output, dict) else {"raw": output}
        output["error"] = error

    parsed = urlparse(str(request.url))
    path = parsed.path or "/v1/chat/completions"
    return write_completion_log(
        input_obj=req_json,
        output_obj=output,
        elapsed_ms=elapsed_ms,
        status=status,
        method=request.method or "POST",
        path=path,
        client=f"cabin/{mode}",
        error=error,
        log_dir=log_dir,
    )


class _TeeByteStream(httpx.SyncByteStream):
    def __init__(self, inner: Any, on_done):
        self._inner = inner
        self._on_done = on_done
        self._buf: List[bytes] = []
        self._done = False

    def __iter__(self):
        try:
            for chunk in self._inner:
                if chunk:
                    self._buf.append(chunk if isinstance(chunk, bytes) else bytes(chunk))
                yield chunk
        finally:
            self._finish()

    def close(self) -> None:
        try:
            closer = getattr(self._inner, "close", None)
            if closer:
                closer()
        finally:
            self._finish()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            self._on_done(b"".join(self._buf))
        except Exception:
            pass


class LlmLogTransport(httpx.BaseTransport):
    """包一层 HTTP 传输：只记录 chat/completions，其它请求原样转发。"""

    def __init__(self, inner: httpx.BaseTransport, mode: str = "remote"):
        self._inner = inner
        self._mode = mode

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/chat/completions" not in url:
            return self._inner.handle_request(request)
        t0 = time.perf_counter()
        try:
            response = self._inner.handle_request(request)
        except Exception as e:
            try:
                log_http_exchange(
                    request=request,
                    status=0,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    body_bytes=b"",
                    mode=self._mode,
                    error=str(e),
                )
            except Exception:
                pass
            raise

        req_json: Dict[str, Any] = {}
        try:
            req_json = json.loads((request.content or b"{}").decode("utf-8") or "{}")
        except Exception:
            pass
        is_stream = bool(req_json.get("stream")) if isinstance(req_json, dict) else False

        if not is_stream:
            raw = response.read()
            try:
                log_http_exchange(
                    request=request,
                    status=response.status_code,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    body_bytes=raw,
                    mode=self._mode,
                )
            except Exception:
                pass
            # read() 已经解过 gzip；重建响应时必须去掉 Content-Encoding，否则 SDK 会再解一次失败
            headers = httpx.Headers(response.headers)
            for key in ("content-encoding", "content-length", "transfer-encoding"):
                headers.pop(key, None)
            try:
                response.close()
            except Exception:
                pass
            return httpx.Response(
                status_code=response.status_code,
                headers=headers,
                content=raw,
                request=request,
                extensions=response.extensions,
            )

        def _on_done(raw: bytes) -> None:
            try:
                log_http_exchange(
                    request=request,
                    status=response.status_code,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    body_bytes=raw,
                    mode=self._mode,
                )
            except Exception:
                pass

        response.stream = _TeeByteStream(response.stream, _on_done)
        return response

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if closer:
            closer()


def make_logged_httpx_client(mode: str, timeout: Any) -> httpx.Client:
    inner = httpx.HTTPTransport()
    return httpx.Client(timeout=timeout, transport=LlmLogTransport(inner, mode=mode))


# 兼容旧测试：直接写一条
def write_llm_call_log(
    *,
    kwargs: Dict[str, Any],
    mode: str,
    elapsed_ms: int,
    status: int,
    output_text: str = "",
    output: Any = None,
    error: str = "",
    log_dir: Optional[Path] = None,
) -> Optional[Path]:
    extra = kwargs.get("extra_body") if isinstance(kwargs.get("extra_body"), dict) else {}
    input_obj: Dict[str, Any] = {
        "messages": kwargs.get("messages") or [],
        "model": kwargs.get("model"),
        "stream": bool(kwargs.get("stream")),
        "temperature": kwargs.get("temperature"),
    }
    if kwargs.get("max_tokens") is not None:
        input_obj["max_tokens"] = kwargs.get("max_tokens")
    input_obj.update(extra)
    out = _to_plain(output) if output is not None else {}
    if isinstance(out, dict) and output_text and not assistant_text(out):
        out.setdefault("choices", [{"message": {"role": "assistant", "content": output_text}}])
    return write_completion_log(
        input_obj=input_obj,
        output_obj=out,
        elapsed_ms=elapsed_ms,
        status=status,
        client=f"cabin/{mode}",
        error=error,
        log_dir=log_dir,
    )


def log_llm_call(**kwargs: Any) -> Optional[Path]:
    try:
        return write_llm_call_log(**kwargs)
    except Exception:
        return None
