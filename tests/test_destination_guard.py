# -*- coding: utf-8 -*-
"""地点门禁与逐步规划清洗。"""
from __future__ import annotations

import unittest

from app.models import ToolCall
from app.nlu.destination_guard import (
    COMPLEX_UTTERANCE_MIN_CHARS,
    is_compound_multi_tool_utterance,
    is_complex_utterance,
    is_relative_or_category_destination,
    should_skip_code_fast_path,
    strip_compound_tail_from_destination,
)
from app.nlu.planner import recover_nearby_from_relative_nav, sanitize_tool_calls


class TestDestinationGuard(unittest.TestCase):
    def test_relative_phrases(self):
        self.assertTrue(is_relative_or_category_destination("最近的商场"))
        self.assertTrue(is_relative_or_category_destination("附近的充电站"))
        self.assertTrue(is_relative_or_category_destination("找个咖啡厅"))
        self.assertTrue(is_relative_or_category_destination("商场"))
        self.assertFalse(is_relative_or_category_destination("中关村软件园"))
        self.assertFalse(is_relative_or_category_destination("艾瑟顿商业广场"))

    def test_sanitize_drops_relative_nav(self):
        calls = [
            ToolCall(name="maps.search_nearby", arguments={"keywords": "商场"}),
            ToolCall(name="navigation.navigate_to", arguments={"destination": "最近的商场"}),
        ]
        out = sanitize_tool_calls(calls)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].name, "maps.search_nearby")

    def test_sanitize_drops_map_app_unless_asked(self):
        calls = [
            ToolCall(name="maps.search_nearby", arguments={"keywords": "酒吧"}),
            ToolCall(name="apps.launch", arguments={"app_name": "高德地图", "enable": True}),
        ]
        out = sanitize_tool_calls(calls, "导航到最近的酒吧")
        self.assertEqual([c.name for c in out], ["maps.search_nearby"])

        out2 = sanitize_tool_calls(calls, "导航到附近酒店，同时打开高德地图")
        self.assertEqual({c.name for c in out2}, {"maps.search_nearby", "apps.launch"})

    def test_recover_nearby_when_only_relative_nav(self):
        orig = [ToolCall(name="navigation.navigate_to", arguments={"destination": "最近的商场"})]
        out = recover_nearby_from_relative_nav("帮我导航到最近的商场", [], orig)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].name, "maps.search_nearby")
        self.assertEqual(out[0].arguments.get("keywords"), "商场")

    def test_compound_multi_tool_detected(self):
        q = "导航到中关村软件园，副驾空调22度，播放周杰伦的晴天"
        self.assertTrue(is_compound_multi_tool_utterance(q))
        self.assertFalse(is_compound_multi_tool_utterance("导航到中关村软件园"))

    def test_strip_compound_tail_from_destination(self):
        raw = "中关村软件园，副驾空调22度，播放周杰伦的晴天"
        self.assertEqual(strip_compound_tail_from_destination(raw), "中关村软件园")

    def test_sanitize_strips_compound_destination(self):
        calls = [
            ToolCall(
                name="navigation.navigate_to",
                arguments={"destination": "中关村软件园，副驾空调22度，播放周杰伦的晴天"},
            ),
        ]
        out = sanitize_tool_calls(calls)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].arguments.get("destination"), "中关村软件园")

    def test_complex_utterance_by_length(self):
        short = "自动泊车怎么用"
        long = "我现在发现无法充电怎么办"
        self.assertFalse(is_complex_utterance(short))
        self.assertTrue(is_complex_utterance(long))
        self.assertEqual(len(short.strip()), 7)
        self.assertGreater(len(long.strip()), COMPLEX_UTTERANCE_MIN_CHARS)
        self.assertTrue(should_skip_code_fast_path(long))
        self.assertFalse(should_skip_code_fast_path(short))


if __name__ == "__main__":
    unittest.main()
