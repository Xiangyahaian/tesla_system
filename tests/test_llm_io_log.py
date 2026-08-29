# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.llm.io_log import (
    LlmLogTransport,
    flatten_messages,
    parse_sse_completion,
    write_llm_call_log,
)


class LlmIoLogTests(unittest.TestCase):
    def test_flatten_and_write_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_llm_call_log(
                kwargs={
                    "model": "qwen-4b-tesla",
                    "messages": [
                        {"role": "system", "content": "你是规划器"},
                        {"role": "user", "content": "我在哪里"},
                    ],
                    "temperature": 0.0,
                    "stream": False,
                    "max_tokens": 400,
                    "extra_body": {
                        "enable_thinking": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                },
                mode="local",
                elapsed_ms=12,
                status=200,
                output_text='{"intent":"search"}',
                output={
                    "id": "chatcmpl-test",
                    "choices": [{"message": {"role": "assistant", "content": '{"intent":"search"}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                },
                log_dir=Path(td),
            )
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.name.endswith(".json"))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["method"], "POST")
            self.assertEqual(data["path"], "/v1/chat/completions")
            self.assertEqual(data["status"], 200)
            self.assertIn("system: 你是规划器", data["input_text"])
            self.assertIn("user: 我在哪里", data["input_text"])
            self.assertEqual(data["output_text"], '{"intent":"search"}')
            self.assertEqual(data["tokens"]["prompt_tokens"], 10)
            self.assertEqual(data["tokens"]["source"], "usage")
            self.assertEqual(data["input"]["model"], "qwen-4b-tesla")
            self.assertEqual(data["input"]["enable_thinking"], False)
            self.assertEqual(data["client"], "cabin/local")

    def test_http_transport_logs_completion(self):
        class FakeInner(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                payload = {
                    "id": "chatcmpl-x",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "你好"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                }
                return httpx.Response(200, json=payload, request=request)

        with tempfile.TemporaryDirectory() as td:
            import app.config as cfg

            old_dir, old_en = cfg.LLM_LOG_DIR, cfg.LLM_LOG_ENABLE
            cfg.LLM_LOG_DIR = Path(td)
            cfg.LLM_LOG_ENABLE = True
            try:
                client = httpx.Client(transport=LlmLogTransport(FakeInner(), mode="local"))
                res = client.post(
                    "http://127.0.0.1:8000/v1/chat/completions",
                    json={
                        "model": "qwen-4b-tesla",
                        "messages": [
                            {"role": "system", "content": "sys"},
                            {"role": "user", "content": "在吗"},
                        ],
                        "stream": False,
                    },
                )
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["choices"][0]["message"]["content"], "你好")
                files = list(Path(td).glob("*.json"))
                self.assertEqual(len(files), 1)
                data = json.loads(files[0].read_text(encoding="utf-8"))
                self.assertEqual(data["output_text"], "你好")
                self.assertEqual(data["path"], "/v1/chat/completions")
                self.assertEqual(data["method"], "POST")
                self.assertIn("user: 在吗", data["input_text"])
                self.assertEqual(data["tokens"]["total_tokens"], 5)
            finally:
                cfg.LLM_LOG_DIR = old_dir
                cfg.LLM_LOG_ENABLE = old_en

    def test_parse_sse_and_stream_log(self):
        raw = (
            'data: {"id":"c1","model":"qwen","choices":[{"delta":{"content":"你"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n'
            "data: [DONE]\n\n"
        ).encode("utf-8")
        out, text = parse_sse_completion(raw)
        self.assertEqual(text, "你好")
        self.assertEqual(out["choices"][0]["message"]["content"], "你好")
        self.assertEqual(out["usage"]["total_tokens"], 3)

        class FakeInner(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                class Chunks(httpx.SyncByteStream):
                    def __iter__(self):
                        yield raw

                    def close(self) -> None:
                        return None

                return httpx.Response(200, stream=Chunks(), request=request)

        with tempfile.TemporaryDirectory() as td:
            import app.config as cfg

            old_dir, old_en = cfg.LLM_LOG_DIR, cfg.LLM_LOG_ENABLE
            cfg.LLM_LOG_DIR = Path(td)
            cfg.LLM_LOG_ENABLE = True
            try:
                client = httpx.Client(transport=LlmLogTransport(FakeInner(), mode="remote"))
                res = client.post(
                    "https://example.com/v1/chat/completions",
                    json={
                        "model": "qwen3.5-flash",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": True,
                    },
                )
                body = res.read()
                self.assertIn(b"data:", body)
                files = list(Path(td).glob("*.json"))
                self.assertEqual(len(files), 1)
                data = json.loads(files[0].read_text(encoding="utf-8"))
                self.assertEqual(data["output_text"], "你好")
                self.assertTrue(data["input"]["stream"])
            finally:
                cfg.LLM_LOG_DIR = old_dir
                cfg.LLM_LOG_ENABLE = old_en

    def test_flatten_empty(self):
        self.assertEqual(flatten_messages([]), "")
        self.assertIn("assistant: hi", flatten_messages([{"role": "assistant", "content": "hi"}]))


if __name__ == "__main__":
    unittest.main()
