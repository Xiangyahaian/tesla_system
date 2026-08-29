# -*- coding: utf-8 -*-
"""意图直达 / 纠偏回归：手册、闲聊、控车、车况不要互相抢。"""
from __future__ import annotations

import unittest

from app.models import IntentType
from app.nlu.fast_path import (
    coerce_planned_intent,
    looks_like_smalltalk,
    looks_like_vehicle_knowledge,
    try_app_utterance,
    try_direct_cabin_utterance,
    try_fast_path_route,
    try_knowledge_utterance,
    try_nearby_utterance,
    try_status_utterance,
    try_web_search_utterance,
)


def peek_fast_intent(query: str) -> str | None:
    route = try_fast_path_route(query)
    return route.intent.value if route else None


KNOWLEDGE_CASES = [
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
    "玩具箱怎么用",
    "灯光秀怎么开启",
    "胎压报警什么意思",
    "能量回收怎么设置",
    "宠物模式是什么意思",
    "怎么开行车记录仪",
    "手机钥匙没电了怎么办",
    "充电口打不开怎么办",
    "超充超时占用费怎么算",
    "雨刮怎么用",
    "营地模式如何开启",
]

CHAT_CASES = [
    "你是谁啊",
    "你是谁",
    "你谁呀",
    "你叫什么",
    "你叫啥",
    "介绍一下你自己",
    "你是人工智能吗",
    "who are you",
    "你好",
    "谢谢",
    "再见",
    "讲个笑话",
    "这首歌有什么故事",
    "今天开了一天的会，脑子很乱，随便陪我聊两句放松一下吧",
    "夜里开车感觉好孤独啊",
    "今天工作不顺心，想吐槽一下",
    "前面又大塞车了，心情有点烦躁,有什么故事能让我心情好一点",
]

NOT_KNOWLEDGE = [
    "打开空调",
    "把温度调到23度",
    "播放周杰伦的晴天",
    "现在空调多少度",
    "附近的充电站有哪些",
    "我附近有哪些好吃的",
    "帮我导航到中关村软件园",
    "打开飞书",
    "打开后备箱",
    "结束导航",
    "我现在播放的音乐是什么",
    "我现在的播放的音量多少",
    "请给我播放下一首歌",
    "帮我把前排空调温度调到22度",
    "我在哪",
    "周末我想开车去周边转转，如果是你的话，你会推荐去哪儿",
]


class TestIntentRouting(unittest.TestCase):
    def test_knowledge_not_fast_path(self):
        """手册问法不再走快路径，一律交 StructuredNLU。"""
        for q in KNOWLEDGE_CASES:
            self.assertTrue(looks_like_vehicle_knowledge(q), q)
            self.assertIsNone(peek_fast_intent(q), q)
            self.assertIsNone(try_knowledge_utterance(q), q)

    def test_chat_identity_and_smalltalk(self):
        for q in CHAT_CASES:
            self.assertFalse(looks_like_vehicle_knowledge(q), q)
            self.assertNotEqual(peek_fast_intent(q), "knowledge", q)
        for q in ("你是谁啊", "你是谁", "你叫什么", "介绍一下你自己"):
            self.assertTrue(looks_like_smalltalk(q), q)
            # 陪聊不再走快路径，交给 StructuredNLU
            self.assertIsNone(peek_fast_intent(q), q)

    def test_contextual_chat_presets_skip_fast_path(self):
        chats = [
            "前面又大塞车了，心情有点烦躁,有什么故事能让我心情好一点",
            "今天开了一天的会，脑子很乱，随便陪我聊两句放松一下吧",
            "周末我想开车去周边转转，如果是你的话，你会推荐去哪儿",
            "夜里开车感觉好孤独啊",
            "今天工作不顺心，想吐槽一下",
            "我最近比较无聊想看电影，最近有什么比较好看的电影吗",
            "你说说这个电影好看在哪里",
        ]
        for q in chats:
            self.assertIsNone(peek_fast_intent(q), q)
            self.assertIsNone(try_nearby_utterance(q), q)

    def test_controls_and_nearby_not_handbook(self):
        for q in NOT_KNOWLEDGE:
            self.assertFalse(looks_like_vehicle_knowledge(q), q)
            self.assertIsNone(try_knowledge_utterance(q), q)

    def test_nearby_beats_knowledge(self):
        self.assertEqual(peek_fast_intent("附近的充电站有哪些"), "tool")
        self.assertEqual(peek_fast_intent("我附近有哪些好吃的"), "tool")

    def test_status_beats_chat(self):
        self.assertEqual(peek_fast_intent("我现在在哪里"), "search")

    def test_coerce_does_not_flip_forbidden_knowledge(self):
        intent = coerce_planned_intent(
            IntentType.CHAT,
            "你是谁啊",
            "用户询问身份属于寒暄/闲聊，符合 chat 意图定义，禁止使用 knowledge 或 tool。",
        )
        self.assertEqual(intent, IntentType.CHAT)

    def test_coerce_flips_wrong_knowledge_on_identity(self):
        intent = coerce_planned_intent(
            IntentType.KNOWLEDGE,
            "你是谁啊",
            "查询车辆身份识别。",
        )
        self.assertEqual(intent, IntentType.CHAT)

    def test_coerce_still_saves_real_handbook_chat_mislabel(self):
        intent = coerce_planned_intent(
            IntentType.CHAT,
            "无法充电怎么办",
            "应调用 knowledge 获取车主手册信息，而非直接执行工具或闲聊。",
        )
        self.assertEqual(intent, IntentType.KNOWLEDGE)

    def test_coerce_does_not_flip_handbook_by_query_regex(self):
        intent = coerce_planned_intent(
            IntentType.CHAT,
            "自动泊车怎么用",
            "闲聊",
        )
        self.assertEqual(intent, IntentType.CHAT)


if __name__ == "__main__":
    unittest.main()
