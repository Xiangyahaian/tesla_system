# -*- coding: utf-8 -*-
"""黄金用例 — 回归与验收。"""

GOLDEN_CASES = [
    # climate
    {"id": "ac_on", "query": "打开空调", "expect_intent": "tool", "expect_tools": ["climate.set_power"]},
    {"id": "ac_temp", "query": "把温度调到23度", "expect_intent": "tool", "expect_tools": ["climate.set_temperature"]},
    {"id": "ac_down", "query": "温度降2度", "expect_intent": "tool", "expect_tools": ["climate.adjust_temperature"]},
    {"id": "ac_rear", "query": "打开后排空调", "expect_intent": "tool", "expect_tools": ["climate.set_power"]},
    # cabin
    {"id": "win_open", "query": "打开车窗", "expect_intent": "tool", "expect_tools": ["cabin.set_windows"]},
    {"id": "win_more", "query": "车窗再开大一点", "expect_intent": "tool", "expect_tools": ["cabin.adjust_windows"]},
    {"id": "door_unlock", "query": "解锁右后门", "expect_intent": "tool", "expect_tools": ["cabin.set_door_locks"], "expect_confirm": True},
    # media
    {"id": "music", "query": "播放周杰伦的晴天", "expect_intent": "tool", "expect_tools": ["media.play_music"]},
    {"id": "vol", "query": "音量调到30", "expect_intent": "tool", "expect_tools": ["media.set_volume"]},
    # multi
    {"id": "multi", "query": "打开空调并播放晴天", "expect_intent": "multi_tool", "min_tools": 2},
    # search
    {"id": "search_temp", "query": "现在空调多少度", "expect_intent": "search"},
    # knowledge
    {"id": "knowledge", "query": "自动泊车怎么用", "expect_intent": "knowledge"},
    # chat
    {"id": "chat", "query": "你好", "expect_intent": "chat"},
]
