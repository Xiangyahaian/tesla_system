# -*- coding: utf-8 -*-
"""模型失败：口语不含原始报错；原因进轨迹；车况可兜底。"""
from __future__ import annotations

import unittest

from app.agent.context import spoken_vehicle_status
from app.llm.client import classify_llm_error, compose_llm_fail_reply


ARREARAGE = (
    "Error code: 400 - {'error': {'message': "
    "'Access denied, please make sure your account is in good standing. "
    "For more details, please refer to: "
    "https://help.aliyun.com/zh/model-studio/error-code#overdue-payment', "
    "'type': 'invalid_request_error', 'param': None, 'code': 'Arrearage'}, "
    "'request_id': 'test-id'}"
)


class LlmErrorSpeechTests(unittest.TestCase):
    def test_arrearage_spoken_hides_raw(self):
        wrapped = RuntimeError("云端模型账号欠费停用了。")
        wrapped.__cause__ = RuntimeError(ARREARAGE)
        info = classify_llm_error(wrapped, mode="remote")
        self.assertEqual(info["kind"], "arrearage")
        self.assertIn("Arrearage", info["error"])
        reply = compose_llm_fail_reply(info)
        self.assertIn("欠费", reply)
        self.assertIn("本地模型", reply)
        self.assertNotIn("Error code", reply)
        self.assertNotIn("Arrearage", reply)
        self.assertNotIn("request_id", reply)

    def test_search_fallback_uses_vehicle_place(self):
        info = classify_llm_error(ARREARAGE, mode="remote")
        fact = spoken_vehicle_status(
            {
                "navigation": {
                    "navigating": False,
                    "position": {"name": "益城路靠近古美路"},
                }
            },
            "我现在在哪儿啊",
        )
        reply = compose_llm_fail_reply(info, fact=fact)
        self.assertIn("益城路", reply)
        self.assertIn("欠费", reply)
        self.assertNotIn("Error code", reply)
        self.assertTrue(fact.startswith("【听】"))

    def test_timeout_local_hint(self):
        info = classify_llm_error("Read timed out", mode="local")
        self.assertEqual(info["kind"], "timeout")
        self.assertIn("vLLM", info["hint"])


class SpokenGuardTests(unittest.TestCase):
    def test_mixed_chinese_and_api_dump_is_replaced(self):
        from app.agent.speech_guard import looks_like_raw_error, sanitize_spoken

        dump = "状态我这边刚看岔了：" + ARREARAGE
        self.assertTrue(looks_like_raw_error(dump))
        out = sanitize_spoken(dump)
        self.assertNotIn("Error code", out)
        self.assertNotIn("Arrearage", out)
        self.assertIn("【听】", out)

    def test_normal_oral_kept(self):
        from app.agent.speech_guard import looks_like_raw_error, sanitize_spoken

        text = "【听】你现在在益城路靠近古美路，导航没开。"
        self.assertFalse(looks_like_raw_error(text))
        self.assertEqual(sanitize_spoken(text), text)

    def test_transcript_assistant_strips_dump(self):
        import tempfile
        from pathlib import Path

        from app.agent.transcript import TranscriptStore
        from app.agent.types import MessageRole

        with tempfile.TemporaryDirectory() as td:
            store = TranscriptStore(Path(td) / "t.jsonl")
            store.append(MessageRole.USER, "我在哪")
            store.append(MessageRole.ASSISTANT, "状态看岔了：" + ARREARAGE)
            msgs = store.load()
            self.assertEqual(msgs[-1].role, MessageRole.ASSISTANT)
            self.assertNotIn("Error code", msgs[-1].content)
            self.assertNotIn("Arrearage", msgs[-1].content)

    def test_tool_exception_message_has_no_dump(self):
        from app.models import ToolCall
        from app.tools.registry import ToolRegistry, ToolSpec
        from pydantic import BaseModel

        class Empty(BaseModel):
            pass

        def boom(_gw, _args):
            raise RuntimeError(ARREARAGE)

        reg = ToolRegistry()
        reg.register(
            ToolSpec(name="test.boom", description="x", args_model=Empty, handler=boom)
        )
        result = reg.execute(None, ToolCall(name="test.boom", arguments={}))  # type: ignore[arg-type]
        self.assertFalse(result.success)
        self.assertNotIn("Error code", result.message)
        self.assertNotIn("Arrearage", result.message)
        self.assertIn("Arrearage", str(result.data.get("error") or ""))


if __name__ == "__main__":
    unittest.main()
