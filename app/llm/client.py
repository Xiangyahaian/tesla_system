# -*- coding: utf-8 -*-
"""统一 LLM 客户端：remote 百炼 / local vLLM，支持 timeout 与真流式。"""
from __future__ import annotations

from typing import AsyncIterator, Iterator, Optional

import openai

from app import config


class LLMClient:
    def __init__(self, mode: str = "remote"):
        self.mode = mode if mode in {"remote", "local"} else "remote"
        if self.mode == "remote":
            self.base_url = config.BAILIAN_API_BASE
            self.api_key = config.BAILIAN_API_KEY or "EMPTY"
            self.model = config.BAILIAN_MODEL_NAME
        else:
            self.base_url = config.VLLM_API_BASE
            self.api_key = config.VLLM_API_KEY
            self.model = config.VLLM_MODEL_NAME
        self._client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=config.LLM_TIMEOUT_SEC,
        )

    @property
    def available(self) -> bool:
        if self.mode == "remote":
            return bool(config.BAILIAN_API_KEY)
        try:
            self._client.models.list()
            return True
        except Exception:
            return False

    def chat(self, system: str, user: str, temperature: Optional[float] = None) -> str:
        extra = {}
        if self.mode == "remote":
            extra["extra_body"] = {"enable_thinking": False}
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
            stream=False,
            **extra,
        )
        if not resp.choices:
            return ""
        return (resp.choices[0].message.content or "").strip()

    def chat_stream(self, system: str, user: str, temperature: Optional[float] = None) -> Iterator[str]:
        extra = {}
        if self.mode == "remote":
            extra["extra_body"] = {"enable_thinking": False}
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
            stream=True,
            **extra,
        )
        for chunk in stream:
            # 百炼/兼容接口末包常带 usage 且 choices=[]，不能直接 [0]
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None)
            if content:
                yield content


def get_llm(mode: str = "remote") -> LLMClient:
    return LLMClient(mode=mode)
