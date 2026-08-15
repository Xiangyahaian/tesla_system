# -*- coding: utf-8 -*-
"""地点门禁与逐步规划清洗。"""
from __future__ import annotations

import unittest

from app.models import ToolCall
from app.nlu.destination_guard import is_relative_or_category_destination
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

    def test_recover_nearby_when_only_relative_nav(self):
        orig = [ToolCall(name="navigation.navigate_to", arguments={"destination": "最近的商场"})]
        out = recover_nearby_from_relative_nav("帮我导航到最近的商场", [], orig)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].name, "maps.search_nearby")
        self.assertEqual(out[0].arguments.get("keywords"), "商场")


if __name__ == "__main__":
    unittest.main()
