# -*- coding: utf-8 -*-
"""用户偏好：写入后跨话题仍改默认行为。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.agent.memory import MemoryStore, PreferenceDelta, build_preference_tool_calls
from app.agent.profile_extract import extract_after_turn
from app.agent.user_profile import UserProfileStore
from app.models import ToolCall
from app.nlu.fast_path import try_combo_cabin_utterance, try_fast_path_route, try_navigate_utterance
from app.nlu.seat_context import apply_memory_climate_defaults


def _md_reply(persona="UNCHANGED", memories="UNCHANGED", preferences="UNCHANGED") -> str:
    return (
        f"---persona.md---\n{persona}\n"
        f"---memories.md---\n{memories}\n"
        f"---preferences.md---\n{preferences}\n"
    )


class MockLLM:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, *_a, **_k) -> str:
        self.calls += 1
        return self.responses[min(self.calls - 1, len(self.responses) - 1)]


def _apply_seat_pref(store: UserProfileStore) -> None:
    llm = MockLLM(
        [
            _md_reply(
                preferences="# 偏好\n\n- 常坐副驾\n- 温度习惯：副驾 22 度\n",
            )
        ]
    )
    extract_after_turn(llm, store, "我坐副驾，喜欢22度", "好")


class MemoryPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mem = MemoryStore(self.root)
        self.profile = UserProfileStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_preferences_persist(self):
        _apply_seat_pref(self.profile)
        prefs = self.mem.load_preferences()
        self.assertEqual(prefs["preferred_seat"], "front_right")
        self.assertEqual(prefs["climate_temp_c"]["front_right"], 22.0)
        self.assertIn("副驾", prefs["text"])

    def test_resolve_seat_after_topic_change(self):
        _apply_seat_pref(self.profile)
        seat, src = self.mem.resolve_active_seat("front_left", "把空调打开")
        self.assertEqual(seat, "front_right")
        self.assertEqual(src, "memory")

    def test_apply_preferred_temp_on_power(self):
        _apply_seat_pref(self.profile)
        calls = [ToolCall(name="climate.set_power", arguments={"enable": True}, reason="开空调")]
        out = apply_memory_climate_defaults(calls, "front_right", 22.0)
        self.assertIn("climate.set_temperature", [c.name for c in out])

    def test_preference_tools(self):
        delta = PreferenceDelta(
            preferred_seat="front_right",
            climate_temps={"front_right": 22.0},
        )
        tools = build_preference_tool_calls(delta)
        self.assertGreaterEqual(len(tools), 2)

    def test_combo_fast_path_deferred_to_nlu_for_compound(self):
        q = "导航到中关村软件园，副驾空调22度，播放周杰伦的晴天"
        self.assertIsNone(try_combo_cabin_utterance(q))
        self.assertIsNone(try_navigate_utterance(q))
        self.assertIsNone(try_fast_path_route(q))

    def test_short_simple_phrase_can_use_fast_path(self):
        self.assertIsNotNone(try_fast_path_route("打开空调"))
        self.assertIsNotNone(try_fast_path_route("我在哪"))


if __name__ == "__main__":
    unittest.main()
