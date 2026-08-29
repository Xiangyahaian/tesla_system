# -*- coding: utf-8 -*-
"""统一 LLM 客户端：remote 百炼 / local vLLM，支持 timeout 与真流式。"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, Optional

import httpx
import openai

from app import config
from app.llm.io_log import make_logged_httpx_client

_local_probe: Dict[str, Any] = {"ts": 0.0, "result": None}


def probe_local_llm(timeout: float = 2.5, *, force: bool = False) -> Dict[str, Any]:
    """探测本地 vLLM。TCP 通但无 HTTP 响应时尽快失败，避免对话空等。"""
    now = time.time()
    cached = _local_probe.get("result")
    if not force and cached and now - float(_local_probe.get("ts") or 0) < 8:
        return dict(cached)

    endpoint = (config.VLLM_API_BASE or "").rstrip("/")
    result: Dict[str, Any] = {
        "ok": False,
        "endpoint": endpoint,
        "model": config.VLLM_MODEL_NAME,
        "error": "",
        "served": [],
    }
    if not endpoint:
        result["error"] = "未配置本地模型地址 VLLM_API_BASE"
        _local_probe["ts"] = now
        _local_probe["result"] = result
        return result

    url = f"{endpoint}/models"
    try:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {config.VLLM_API_KEY or 'EMPTY'}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "ignore")
            data = json.loads(body) if body.strip() else {}
            ids = [str(x.get("id") or "") for x in (data.get("data") or []) if isinstance(x, dict)]
            result["served"] = [x for x in ids if x]
            if result["served"] and config.VLLM_MODEL_NAME not in result["served"]:
                result["model"] = result["served"][0]
            result["ok"] = True
            result["error"] = ""
    except socket.timeout:
        result["error"] = (
            f"已连上 {endpoint}，但模型没有应答。"
            "请在 GPU 那台本机执行 curl http://127.0.0.1:8000/v1/models ；"
            "若本机也卡住，重启 python vllm_start.py。"
        )
    except TimeoutError:
        result["error"] = (
            f"已连上 {endpoint}，但模型没有应答。"
            "请在 GPU 那台确认 vLLM 已加载完成。"
        )
    except urllib.error.HTTPError as e:
        result["error"] = f"本地模型接口返回 HTTP {e.code}（{endpoint}）"
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e) or e)
        low = reason.lower()
        if "refused" in low:
            result["error"] = (
                f"本地模型端口未开放（{endpoint}）。"
                "请先在 GPU 电脑启动 python vllm_start.py，并放行 TCP 8000。"
            )
        elif "timed out" in low or "timeout" in low:
            result["error"] = f"连接本地模型超时（{endpoint}）。请确认 GPU 电脑在线且防火墙已放行 8000。"
        else:
            result["error"] = f"连不上本地模型 {endpoint}"
    except Exception:
        result["error"] = "本地模型探测失败。请确认 GPU 电脑上的 vLLM 已启动。"

    _local_probe["ts"] = now
    _local_probe["result"] = result
    return dict(result)


def _error_chain_text(exc: BaseException) -> str:
    parts: list[str] = []
    cur: Optional[BaseException] = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        text = str(cur) or cur.__class__.__name__
        if text:
            parts.append(text)
        nxt = cur.__cause__ or cur.__context__
        cur = nxt if nxt is not None and id(nxt) not in seen else None
    return "\n".join(parts)


def _innermost_error_text(exc: BaseException) -> str:
    cur: BaseException = exc
    seen: set[int] = set()
    while cur.__cause__ is not None and id(cur.__cause__) not in seen:
        seen.add(id(cur))
        cur = cur.__cause__
    return str(cur) or cur.__class__.__name__


def classify_llm_error(exc: BaseException | str, *, mode: str = "remote") -> Dict[str, str]:
    """把模型异常拆成：口语原因、处理建议、原始报错（只给执行轨迹）。"""
    if isinstance(exc, str):
        raw = exc.strip() or "unknown"
        chain = raw
    else:
        raw = (_innermost_error_text(exc) or "").strip() or exc.__class__.__name__
        chain = _error_chain_text(exc) or raw
    low = chain.lower()
    llm_mode = mode if mode in {"remote", "local"} else "remote"

    kind = "unknown"
    spoken = "【听】模型这会儿连不上，这句没法生成。"
    hint = "你可以稍后再问，或先切到另一边模型试试。"

    if any(
        k in chain
        for k in ("Arrearage", "arrearage", "overdue-payment", "欠费", "Access denied, please make sure your account")
    ) or ("overdue" in low and ("payment" in low or "account" in low)):
        kind = "arrearage"
        if llm_mode == "local":
            spoken = "【听】本地模型拒绝了这次请求。"
            hint = "请在 GPU 电脑上看一下 vLLM 是否还在跑。"
        else:
            spoken = "【听】云端模型账号欠费停用了。"
            hint = "可以去阿里云百炼充值，或先切到本地模型再问一遍。"
    elif any(k in low for k in ("insufficient_quota", "exceeded your current quota", "billing", "quota exceeded")):
        kind = "quota"
        spoken = "【听】云端模型额度用完了。"
        hint = "可以去百炼查看额度，或先切到本地模型。"
    elif "401" in chain or "invalid api key" in low or "incorrect api key" in low or "unauthorized" in low:
        kind = "auth"
        spoken = "【听】云端模型密钥无效。"
        hint = "请在设置里核对百炼 API Key。"
    elif "429" in chain or "rate limit" in low or "too many requests" in low:
        kind = "rate_limit"
        spoken = "【听】模型这会儿太忙，请求被限流了。"
        hint = "稍等几秒再问一遍就行。"
    elif "timeout" in low or "timed out" in low:
        kind = "timeout"
        if llm_mode == "local":
            spoken = "【听】本地模型响应超时。"
            hint = "请确认 GPU 电脑上的 vLLM 已加载完成。"
        else:
            spoken = "【听】云端模型响应超时。"
            hint = "稍后再问一遍，或先切到本地模型。"
    elif "max_model_len" in low or "context length" in low or "maximum context" in low:
        kind = "context_length"
        spoken = "【听】这句话超出了模型上下文长度。"
        hint = "请换一句更短的，或加大本地模型的 --max-model-len。"
    elif "refused" in low or "connect" in low or "connection" in low or "name or service not known" in low:
        kind = "connect"
        if llm_mode == "local":
            spoken = "【听】连不上本地模型。"
            hint = f"请先启动 vLLM（{config.VLLM_API_BASE}）。"
        else:
            spoken = "【听】云端模型暂时连不上。"
            hint = "请检查网络，或先切到本地模型。"
    elif llm_mode == "local" and ("not found" in low or "does not exist" in low):
        kind = "model_missing"
        spoken = f"【听】本地服务里没有模型 {config.VLLM_MODEL_NAME}。"
        hint = "请核对 --served-model-name。"

    return {
        "kind": kind,
        "spoken": spoken,
        "hint": hint,
        "error": raw[:2000],
        "llm_mode": llm_mode,
    }


def compose_llm_fail_reply(info: Dict[str, str], *, fact: str = "") -> str:
    """用户可见回复：可选车况事实 + 人话原因 + 下一步。不含 API 原文。"""
    spoken = (info.get("spoken") or "【听】模型这会儿连不上。").strip()
    hint = (info.get("hint") or "").strip()
    fact = (fact or "").strip()
    bits: list[str] = []
    if fact:
        bits.append(fact if fact.startswith("【听】") else f"【听】{fact}")
        cause = spoken.replace("【听】", "").strip()
        if cause:
            bits.append(cause)
    else:
        bits.append(spoken)
    if hint and hint not in " ".join(bits):
        bits.append(hint)
    text = " ".join(b.rstrip("。") for b in bits if b)
    return text + "。" if text and not text.endswith(("。", "！", "？")) else text


def _friendly_llm_error(exc: BaseException, *, mode: str) -> str:
    info = classify_llm_error(exc, mode=mode)
    return compose_llm_fail_reply(info).replace("【听】", "").strip()


class LLMClient:
    def __init__(self, mode: str = "remote"):
        self.mode = mode if mode in {"remote", "local"} else "remote"
        if self.mode == "remote":
            self.base_url = config.BAILIAN_API_BASE
            self.api_key = config.BAILIAN_API_KEY or "EMPTY"
            self.model = config.BAILIAN_MODEL_NAME
            timeout: httpx.Timeout | float = config.LLM_TIMEOUT_SEC
        else:
            self.base_url = config.VLLM_API_BASE
            self.api_key = config.VLLM_API_KEY or "EMPTY"
            self.model = config.VLLM_MODEL_NAME
            timeout = httpx.Timeout(connect=4.0, read=90.0, write=30.0, pool=5.0)
        self._http = make_logged_httpx_client(self.mode, timeout)
        self._client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
            http_client=self._http,
        )
        self._usage_log: list[Dict[str, Any]] = []

    def ping(self) -> Dict[str, Any]:
        if self.mode != "local":
            return {"ok": bool(config.BAILIAN_API_KEY), "error": "" if config.BAILIAN_API_KEY else "未配置云端模型密钥"}
        st = probe_local_llm()
        if st.get("ok") and st.get("model"):
            self.model = str(st["model"])
        return st

    @property
    def available(self) -> bool:
        if self.mode == "remote":
            return bool(config.BAILIAN_API_KEY)
        return bool(probe_local_llm().get("ok"))

    def _extra_body(self) -> Dict[str, Any]:
        extra: Dict[str, Any] = {}
        extra["extra_body"] = {
            "enable_thinking": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        return extra

    @staticmethod
    def _transient_llm_error(exc: BaseException) -> bool:
        text = (str(exc) or exc.__class__.__name__).lower()
        keys = ("timeout", "timed out", "temporar", "connection", "connect", "reset", "unavailable", "429", "502", "503", "504")
        return any(k in text for k in keys)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """接口没返回 usage 时的粗估：约 2 字/token。页面会标明「估算」。"""
        n = len(text or "")
        if n <= 0:
            return 0
        return max(1, (n + 1) // 2)

    @staticmethod
    def _parse_usage(usage: Any) -> Dict[str, Any]:
        if usage is None:
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "token_source": "none"}
        if isinstance(usage, dict):
            raw = usage
        else:
            dump = getattr(usage, "model_dump", None)
            if callable(dump):
                try:
                    raw = dump()
                except Exception:
                    raw = {}
            else:
                raw = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                }
        if not isinstance(raw, dict):
            raw = {}
        prompt = int(raw.get("prompt_tokens") or 0)
        completion = int(raw.get("completion_tokens") or 0)
        total = int(raw.get("total_tokens") or 0) or (prompt + completion)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "token_source": "api" if (prompt or completion or total) else "none",
        }

    def _record_usage(
        self,
        system: str,
        user: str,
        output: str,
        usage: Any,
        elapsed_ms: int = 0,
    ) -> None:
        sys_s = system or ""
        usr_s = user or ""
        out_s = output or ""
        parsed = self._parse_usage(usage)
        if parsed["token_source"] == "none":
            parsed["prompt_tokens"] = self.estimate_tokens(sys_s) + self.estimate_tokens(usr_s)
            parsed["completion_tokens"] = self.estimate_tokens(out_s)
            parsed["total_tokens"] = parsed["prompt_tokens"] + parsed["completion_tokens"]
            parsed["token_source"] = "estimate"
        self._usage_log.append(
            {
                "model": self.model,
                "mode": self.mode,
                "system": sys_s,
                "user": usr_s,
                "output": out_s,
                "prompt_chars": len(sys_s) + len(usr_s),
                "completion_chars": len(out_s),
                "system_chars": len(sys_s),
                "user_chars": len(usr_s),
                "prompt_tokens": parsed["prompt_tokens"],
                "completion_tokens": parsed["completion_tokens"],
                "total_tokens": parsed["total_tokens"],
                "token_source": parsed["token_source"],
                "elapsed_ms": max(0, int(elapsed_ms or 0)),
            }
        )

    def drain_usage(self) -> list[Dict[str, Any]]:
        out = list(self._usage_log)
        self._usage_log.clear()
        return out

    def chat(
        self,
        system: str,
        user: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        retries: int = 1,
    ) -> str:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
            "stream": False,
            **self._extra_body(),
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        attempts = max(1, int(retries) + 1)
        last_err: Optional[BaseException] = None
        for i in range(attempts):
            try:
                t0 = time.perf_counter()
                resp = self._client.chat.completions.create(**kwargs)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                text = ""
                if resp.choices:
                    text = (resp.choices[0].message.content or "").strip()
                self._record_usage(system, user, text, getattr(resp, "usage", None), elapsed_ms)
                return text
            except Exception as e:
                last_err = e
                if i + 1 < attempts and self._transient_llm_error(e):
                    time.sleep(0.35 * (i + 1))
                    continue
                raise RuntimeError(_friendly_llm_error(e, mode=self.mode)) from e
        raise RuntimeError(_friendly_llm_error(last_err or RuntimeError("LLM 调用失败"), mode=self.mode))

    def chat_stream(
        self,
        system: str,
        user: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
            **self._extra_body(),
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        try:
            t0 = time.perf_counter()
            try:
                stream = self._client.chat.completions.create(**kwargs)
            except Exception:
                if kwargs.pop("stream_options", None) is None:
                    raise
                t0 = time.perf_counter()
                stream = self._client.chat.completions.create(**kwargs)
            pieces: list[str] = []
            usage_obj: Any = None
            for chunk in stream:
                u = getattr(chunk, "usage", None)
                if u:
                    usage_obj = u
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                content = getattr(delta, "content", None)
                if content:
                    pieces.append(content)
                    yield content
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            self._record_usage(system, user, "".join(pieces), usage_obj, elapsed_ms)
        except Exception as e:
            raise RuntimeError(_friendly_llm_error(e, mode=self.mode)) from e


def get_llm(mode: str = "remote") -> LLMClient:
    return LLMClient(mode=mode)
