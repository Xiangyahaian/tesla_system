# -*- coding: utf-8 -*-
"""导航候选待选：禁止闲聊编造；简称唯一命中可直达。"""
from __future__ import annotations

import unittest

from app.nlu.fast_path import try_nav_candidate_utterance


CANDS = [
    {"index": 1, "name": "北京理工大学(中关村校区)"},
    {"index": 2, "name": "北京理工大学中关村校区北区"},
    {"index": 3, "name": "北京理工大学中关村校区理工科技大厦"},
    {"index": 4, "name": "北京理工大学中关村校区家属区"},
]


class NavCandidateGateTests(unittest.TestCase):
    def test_ordinal(self):
        r = try_nav_candidate_utterance("第二个", CANDS)
        self.assertIsNotNone(r)
        self.assertEqual(r.tool_calls[0].arguments["destination"], CANDS[1]["name"])

    def test_unique_hint_家属(self):
        r = try_nav_candidate_utterance("去家属区", CANDS)
        self.assertIsNotNone(r)
        self.assertIn("家属区", r.tool_calls[0].arguments["destination"])

    def test_ambiguous_新校区_no_match(self):
        # 候选里没有良乡/新校区 → 不猜，交给上层澄清拦截
        r = try_nav_candidate_utterance("新的校区", CANDS)
        self.assertIsNone(r)

    def test_ambiguous_中关村_multi(self):
        r = try_nav_candidate_utterance("中关村那个", CANDS)
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
