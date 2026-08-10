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
        comp = ContextCompactor(soft_limit_chars=1000, keep_recent=8, tool_max_chars=50)
        new_msgs, report = comp.compact(msgs, llm=None)
        self.assertTrue(report.layers)
        self.assertLess(report.after_chars, report.before_chars)
        self.assertTrue(len(new_msgs) < len(msgs) or any("truncated" in (m.meta or {}) for m in new_msgs))

    def test_session_dir_layout(self):
        with tempfile.TemporaryDirectory() as td:
            store = SessionStore(root=Path(td))
            sess = store.get("demo")
            sess.transcript.append(MessageRole.USER, "音量多少")
            sess.slots["last"] = 1
            store.save(sess)
            self.assertTrue((sess.root / "vehicle.json").exists())
            self.assertTrue((sess.root / "transcript.jsonl").exists())
            self.assertTrue((sess.root / "session.json").exists())
            self.assertTrue((sess.root / "memory" / "MEMORY.md").exists())
            self.assertTrue(hasattr(sess, "traces"))
            # reload
            store2 = SessionStore(root=Path(td))
            sess2 = store2.get("demo")
            self.assertEqual(sess2.slots.get("last"), 1)
            self.assertEqual(len(sess2.transcript.load()), 1)

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
