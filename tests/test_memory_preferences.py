# -*- coding: utf-8 -*-
"""Claude Code 同款记忆：偏好写入后跨话题仍改默认行为。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.agent.memory import MemoryStore, build_preference_tool_calls
from app.models import ToolCall
from app.nlu.fast_path import try_combo_cabin_utterance, try_preference_utterance
from app.nlu.seat_context import apply_memory_climate_defaults


class MemoryPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mem = MemoryStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingest_passenger_22(self):
        d = self.mem.ingest_utterance("我坐副驾，喜欢22度")
        self.assertTrue(d.applied)
        self.assertEqual(d.preferred_seat, "front_right")
        self.assertEqual(d.climate_temps.get("front_right"), 22.0)
        prefs = self.mem.load_preferences()
        self.assertEqual(prefs["preferred_seat"], "front_right")
        self.assertEqual(prefs["climate_temp_c"]["front_right"], 22.0)
        md = self.mem.load_auto_memory()
        self.assertIn("副驾", md)
        self.assertIn("22", md)

    def test_resolve_seat_after_topic_change(self):
        self.mem.ingest_utterance("我坐副驾，喜欢22度")
        seat, src = self.mem.resolve_active_seat("front_left", "把空调打开")
        self.assertEqual(seat, "front_right")
        self.assertEqual(src, "memory")

    def test_apply_preferred_temp_on_power(self):
        self.mem.ingest_utterance("我坐副驾，喜欢22度")
        calls = [
            ToolCall(name="climate.set_power", arguments={"enable": True}, reason="开空调"),
        ]
        out = apply_memory_climate_defaults(calls, "front_right", 22.0)
        names = [c.name for c in out]
        self.assertIn("climate.set_temperature", names)
        temp_call = next(c for c in out if c.name == "climate.set_temperature")
        self.assertEqual(temp_call.arguments.get("temperature"), 22.0)

    def test_preference_tools(self):
        d = self.mem.ingest_utterance("我坐副驾，喜欢22度")
        tools = build_preference_tool_calls(d)
        self.assertGreaterEqual(len(tools), 2)
        self.assertEqual(tools[0].arguments.get("zones"), ["front_right"])

    def test_fast_paths(self):
        self.assertIsNotNone(try_preference_utterance("我坐副驾，喜欢22度"))
        combo = try_combo_cabin_utterance("导航到中关村软件园，副驾空调22度，播放周杰伦的晴天")
        self.assertIsNotNone(combo)
        assert combo is not None
        self.assertGreaterEqual(len(combo.tool_calls), 3)


if __name__ == "__main__":
    unittest.main()
