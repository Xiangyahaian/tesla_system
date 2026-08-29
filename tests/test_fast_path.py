# -*- coding: utf-8 -*-
"""确认门控短指令测试（意图分类已改为 StructuredNLU，不再做关键词路由）。"""
from __future__ import annotations

import unittest

from app.models import IntentType
from app.nlu.fast_path import (
    coerce_planned_intent,
    looks_like_vehicle_knowledge,
    try_confirm_utterance,
    try_knowledge_utterance,
    try_status_utterance,
)


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


class TestStatusAndPreference(unittest.TestCase):
    def test_where_am_i_is_search_not_preference(self):
        for q in ("我现在在哪儿啊啊", "我现在在哪里", "我在哪", "现在在哪儿"):
            route = try_status_utterance(q)
            self.assertIsNotNone(route, q)
            self.assertEqual(route.intent, IntentType.SEARCH, q)
            self.assertEqual(route.reason, "查询当前位置", q)
            self.assertEqual(route.tool_calls, [])


class TestKnowledgeUtterance(unittest.TestCase):
    KNOWLEDGE_QUERIES = (
        "我现在发现无法充电怎么办",
        "自动泊车怎么用",
        "怎么寻找充电地点？",
        "前撞预警可以监测到哪些东西呢？",
        "智能泊车在什么状况下也许不能正常工作啊？",
        "Model 3上要咋搜索音频内容呢？",
        "若检测到外部充电设备发生故障，车辆能不能进行直流快速充电呢？",
        "车辆的最大允许总质量包含哪些部分？",
        "为什么Model 3长时间停着的时候要用充电器充电呢？",
        "前摄像头外壳里有冷凝了，怎么清洁呢？",
        "车电量耗尽的时候，在车里边打开后备箱该如何操作呢？",
        "紧急制动的情况下制动功能不正常了，怎样停车呢?",
        "用哪些方式能够关上后备箱啊?",
        "在超级充电站充电，什么情况下会被收取超时占用费呀？",
        "电池图标变成黄色代表着什么呢？",
        "充不了电是怎么回事",
        "哨兵模式怎么开",
    )

    def test_handbook_heuristic_not_routed(self):
        for q in self.KNOWLEDGE_QUERIES:
            self.assertTrue(looks_like_vehicle_knowledge(q), q)
            self.assertIsNone(try_knowledge_utterance(q), q)

    def test_not_stolen_from_tool_search_nearby_chat(self):
        negatives = (
            "打开空调",
            "把温度调到23度",
            "播放周杰伦的晴天",
            "现在空调多少度",
            "附近的充电站有哪些",
            "你好",
            "这首歌有什么故事",
            "帮我导航到中关村软件园",
        )
        for q in negatives:
            self.assertFalse(looks_like_vehicle_knowledge(q), q)
            self.assertIsNone(try_knowledge_utterance(q), q)

    def test_coerce_chat_when_reason_says_knowledge(self):
        intent = coerce_planned_intent(
            IntentType.CHAT,
            "随便说一句",
            "应调用 knowledge 获取车主手册信息，而非直接执行工具或闲聊。",
        )
        self.assertEqual(intent, IntentType.KNOWLEDGE)

    def test_coerce_chat_when_query_is_handbook_stays_chat(self):
        intent = coerce_planned_intent(IntentType.CHAT, "我现在发现无法充电怎么办", "闲聊")
        self.assertEqual(intent, IntentType.CHAT)

    def test_who_are_you_is_not_knowledge(self):
        self.assertFalse(looks_like_vehicle_knowledge("你是谁啊"))
        self.assertIsNone(try_knowledge_utterance("你是谁啊"))
        intent = coerce_planned_intent(
            IntentType.CHAT,
            "你是谁啊",
            "用户询问身份属于寒暄/闲聊，符合 chat 意图定义，禁止使用 knowledge 或 tool。",
        )
        self.assertEqual(intent, IntentType.CHAT)


if __name__ == "__main__":
    unittest.main()
