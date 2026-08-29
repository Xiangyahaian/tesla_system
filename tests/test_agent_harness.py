# -*- coding: utf-8 -*-
"""Agent harness：transcript / compact / session 目录。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.agent.compact import ContextCompactor
from app.agent.memory import MemoryStore
from app.agent.transcript import TranscriptStore
from app.agent.types import MessageRole
from app.session.db import SessionDatabase
from app.session.store import SessionStore


class TestAgentHarness(unittest.TestCase):
    def test_transcript_append_load(self):
        with tempfile.TemporaryDirectory() as td:
            tr = TranscriptStore(Path(td) / "t.jsonl")
            tr.append(MessageRole.USER, "打开空调")
            tr.append(MessageRole.ASSISTANT, "好的")
            msgs = tr.load()
            self.assertEqual(len(msgs), 2)
            self.assertEqual(msgs[0].content, "打开空调")

    def test_compact_layers(self):
        msgs = []
        for i in range(40):
            from app.agent.types import TranscriptMessage

            role = MessageRole.USER if i % 2 == 0 else MessageRole.TOOL
            content = ("x" * 200) if role == MessageRole.TOOL else f"msg-{i}"
            msgs.append(TranscriptMessage(role=role, content=content, ts=float(i)))

        class _FakeLLM:
            def chat(self, *a, **k):
                return "- 历史多轮用户消息与工具输出已归档。"

        comp = ContextCompactor(soft_limit_chars=1000, keep_recent_turns=5, tool_max_chars=50)
        new_msgs, report = comp.compact(msgs, llm=_FakeLLM(), force_auto=True)
        self.assertTrue(report.layers)
        self.assertIn("append_compact", report.layers)
        self.assertEqual(len(new_msgs), len(msgs) + 1)
        self.assertEqual(new_msgs[-1].role, MessageRole.COMPACTION)
        self.assertLess(report.after_chars, report.before_chars)

    def test_session_dir_layout(self):
        with tempfile.TemporaryDirectory() as td:
            db = SessionDatabase(Path(td) / "sessions.db")
            store = SessionStore(root=Path(td), db=db)
            sess = store.get("demo")
            sess.transcript.append(MessageRole.USER, "音量多少")
            sess.slots["last"] = 1
            store.save(sess)
            self.assertTrue((sess.user_root / "vehicle.json").exists())
            mem = sess.user_root / "memory"
            self.assertEqual(
                sorted(p.name for p in mem.iterdir() if p.is_file()),
                ["memories.md", "persona.md", "preferences.md"],
            )
            self.assertFalse((mem / "persona.json").exists())
            self.assertFalse((mem / "memories.json").exists())
            self.assertFalse((mem / "preferences.json").exists())
            self.assertTrue((sess.root / "session.jsonl").exists())
            self.assertFalse((sess.root / "transcript.jsonl").exists())
            self.assertFalse((sess.root / "session.json").exists())
            raw = (sess.root / "session.jsonl").read_text(encoding="utf-8").strip()
            self.assertIn('"role"', raw)
            self.assertEqual(sess.root, sess.user_root / "sessions" / "demo")
            self.assertFalse((sess.root / "vehicle.json").exists())
            self.assertTrue(hasattr(sess, "traces"))
            db.close()
            db2 = SessionDatabase(Path(td) / "sessions.db")
            try:
                store2 = SessionStore(root=Path(td), db=db2)
                sess2 = store2.get("demo")
                self.assertEqual(sess2.slots.get("last"), 1)
                self.assertEqual(len(sess2.transcript.load()), 1)
            finally:
                db2.close()

    def test_append_compact_keeps_history(self):
        with tempfile.TemporaryDirectory() as td:
            from app.agent.types import TranscriptMessage

            msgs = []
            for i in range(12):
                msgs.append(TranscriptMessage(role=MessageRole.USER, content=f"用户说事实{i}：住址公司家人", ts=float(i)))
                msgs.append(TranscriptMessage(role=MessageRole.ASSISTANT, content=f"已记下{i}", ts=float(i) + 0.1))
            comp = ContextCompactor(soft_limit_chars=10, keep_recent_turns=5)

            class _FakeLLM:
                def chat(self, *a, **k):
                    return "- 用户聊过住址公司家人等事实，多轮确认。"

            new_msgs, report = comp.compact(msgs, llm=_FakeLLM(), force_auto=True)
            self.assertIn("append_compact", report.layers)
            self.assertEqual(len(new_msgs), len(msgs) + 1)
            self.assertEqual(new_msgs[-1].role, MessageRole.COMPACTION)
            self.assertTrue(new_msgs[-1].content)
            # 原消息未被删除
            self.assertEqual(new_msgs[0].content, msgs[0].content)

    def test_trace_store(self):
        with tempfile.TemporaryDirectory() as td:
            from app.agent.trace import TraceStore, TurnTrace, StepType

            store = TraceStore(Path(td) / "turns.jsonl")
            turn = TurnTrace(session_id="demo", query="打开空调")
            turn.add(StepType.INTENT, "tool", {"intent": "tool"})
            turn.finish(status="ok", intent="tool", answer_preview="已打开")
            store.append_turn(turn)
            items = store.list_turns()
            self.assertEqual(len(items), 1)
            got = store.get_turn(turn.turn_id)
            self.assertIsNotNone(got)
            self.assertEqual(got.intent, "tool")


if __name__ == "__main__":
    unittest.main()
