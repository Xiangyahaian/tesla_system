# -*- coding: utf-8
"""测试用 LLM mock。"""
from __future__ import annotations

import json
from typing import Any, Dict


class MockLLM:
    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        self.calls = 0

    def chat(self, *_args, **_kwargs) -> str:
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)
