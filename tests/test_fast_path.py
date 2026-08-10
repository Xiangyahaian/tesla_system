# -*- coding: utf-8 -*-
"""确认门控短指令测试（意图分类已改为 StructuredNLU，不再做关键词路由）。"""
from __future__ import annotations

import unittest

from app.models import IntentType
from app.nlu.fast_path import try_confirm_utterance


class TestConfirmUtterance(unittest.TestCase):
    def test_confirm(self):
        route = try_confirm_utterance("确认")
        self.assertIsNotNone(route)
        self.assertEqual(route.intent, IntentType.CONFIRM)

    def test_cancel(self):
        route = try_confirm_utterance("取消")
        self.assertIsNotNone(route)
        self.assertEqual(route.intent, IntentType.CANCEL)

    def test_business_query_not_hijacked(self):
        # 业务问句绝不能被当成确认门控
        self.assertIsNone(try_confirm_utterance("我现在播放的音乐是什么"))
        self.assertIsNone(try_confirm_utterance("打开空调"))
        self.assertIsNone(try_confirm_utterance("自动泊车怎么用"))


if __name__ == "__main__":
    unittest.main()
