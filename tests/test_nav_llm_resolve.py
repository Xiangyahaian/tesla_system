# -*- coding: utf-8 -*-
"""导航澄清：口语简称由 LLM 在候选内判定；规则不得误伤。"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from app.nlu.nav_resolve import resolve_nav_selection

USER_CANDS = [
    {
        "index": 1,
        "name": "北京理工大学中关村校区附属小学(南门)",
        "address": "海淀区中关村南大街5号",
    },
    {"index": 2, "name": "北京理工大学良乡校区南校区", "address": "房山区"},
    {
        "index": 3,
        "name": "北京理工大学(中关村校区)",
        "address": "海淀区中关村南大街5号",
    },
    {"index": 4, "name": "北京理工大学社区(西1门)", "address": "海淀区"},
]

PALACE_CANDS = [
    {"index": 1, "name": "北京故宫博物院北院区(建设中)"},
    {"index": 2, "name": "上新了故宫(北京站店)"},
    {"index": 3, "name": "北景源·北京涮肉(故宫角楼店)"},
    {"index": 4, "name": "故宫博物院-神武门"},
]

COMPANY_CANDS = [
    {"index": 1, "name": "北京中云宽频通讯技术有限公司"},
    {"index": 2, "name": "北京理工新源信息科技有限公司"},
    {"index": 3, "name": "北京学策科技有限公司"},
]


class NavLlmResolveTests(unittest.TestCase):
    def test_llm_picks_zhongguancun_campus(self):
        llm = MagicMock()
        llm.chat.return_value = json.dumps(
            {
                "action": "navigate",
                "index": 3,
                "reason": "用户说中关村，对应主校区",
            },
            ensure_ascii=False,
        )
        sel = resolve_nav_selection(
            "中关村的那俺们",
            USER_CANDS,
            llm=llm,
            query_label="北京理工大学南门",
        )
        self.assertEqual(sel.action, "navigate")
        self.assertEqual(sel.destination, "北京理工大学(中关村校区)")
        self.assertTrue(sel.used_llm)
        llm.chat.assert_called_once()

    def test_llm_narrow_still_ambiguous(self):
        llm = MagicMock()
        llm.chat.return_value = json.dumps(
            {
                "action": "narrow",
                "indices": [1, 3],
                "reason": "都在中关村，需再确认",
            },
            ensure_ascii=False,
        )
        sel = resolve_nav_selection(
            "中关村的南门",
            USER_CANDS,
            llm=llm,
            query_label="北京理工大学南门",
        )
        self.assertEqual(sel.action, "narrow")
        self.assertEqual(len(sel.candidates), 2)
        self.assertTrue(sel.used_llm)

    def test_ordinal_skips_llm(self):
        llm = MagicMock()
        sel = resolve_nav_selection("第三个", USER_CANDS, llm=llm)
        self.assertEqual(sel.action, "navigate")
        self.assertEqual(sel.destination, "北京理工大学(中关村校区)")
        self.assertFalse(sel.used_llm)
        llm.chat.assert_not_called()

    def test_yixia_not_ordinal(self):
        """「一下」绝不能当成第 1 个候选。"""
        llm = MagicMock()
        llm.chat.return_value = json.dumps(
            {"action": "clear", "reason": "用户要搜网"},
            ensure_ascii=False,
        )
        sel = resolve_nav_selection(
            "好玩的有吗，你去网上搜索一下",
            PALACE_CANDS,
            llm=llm,
        )
        self.assertEqual(sel.action, "clear")
        self.assertNotEqual(sel.reason, "序号选择")
        llm.chat.assert_not_called()

    def test_reject_all_with_new_place(self):
        llm = MagicMock()
        sel = resolve_nav_selection(
            "都不想要，我想去北京故宫边上的",
            [
                {"index": 1, "name": "报刊亭"},
                {"index": 2, "name": "工会户外劳动者爱心驿站(海淀街道温馨家园)"},
            ],
            llm=llm,
        )
        self.assertEqual(sel.action, "new_destination")
        llm.chat.assert_not_called()

    def test_plain_reject_clears(self):
        llm = MagicMock()
        sel = resolve_nav_selection("不行", PALACE_CANDS, llm=llm)
        self.assertEqual(sel.action, "clear")
        llm.chat.assert_not_called()

    def test_wo_bu_xuan_clears(self):
        llm = MagicMock()
        sel = resolve_nav_selection("我不选。", COMPANY_CANDS, llm=llm)
        self.assertEqual(sel.action, "clear")
        llm.chat.assert_not_called()

    def test_ask_home_off_topic_clears(self):
        llm = MagicMock()
        sel = resolve_nav_selection("家在哪里吗？", COMPANY_CANDS, llm=llm)
        self.assertEqual(sel.action, "clear")
        llm.chat.assert_not_called()

    def test_ask_assistant_knows_home_clears(self):
        llm = MagicMock()
        sel = resolve_nav_selection(
            "我是说你，你知道我的家在哪里吗？",
            COMPANY_CANDS,
            llm=llm,
        )
        self.assertEqual(sel.action, "clear")
        llm.chat.assert_not_called()

    def test_llm_mistaken_repeat_forced_clear(self):
        llm = MagicMock()
        llm.chat.return_value = json.dumps(
            {"action": "repeat", "reason": "仍需澄清"},
            ensure_ascii=False,
        )
        sel = resolve_nav_selection("我不想从里面挑", COMPANY_CANDS, llm=llm)
        self.assertEqual(sel.action, "clear")


if __name__ == "__main__":
    unittest.main()
