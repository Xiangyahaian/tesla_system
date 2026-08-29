# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models import IntentType
from app.nlu.fast_path import (
    chat_web_query,
    extract_web_query,
    try_nearby_utterance,
    try_web_search_utterance,
)
from app.tools.registry import get_registry
from app.websearch import web_search


class TestWebSearchFastPath(unittest.TestCase):
    def test_extract_search_command(self):
        self.assertEqual(extract_web_query("帮我搜一下今天国内油价"), "今天国内油价")
        self.assertEqual(extract_web_query("百度一下英伟达股价"), "英伟达股价")
        self.assertEqual(extract_web_query("网上查一下美元汇率"), "美元汇率")
        self.assertTrue(extract_web_query("今天有什么新闻"))
        self.assertTrue(extract_web_query("帮我去总结一些昨天发生的大新闻"))
        self.assertTrue(extract_web_query("最近一周的AI大事有哪些"))

    def test_not_steal_nearby_or_car(self):
        self.assertIsNone(extract_web_query("搜一下附近的餐厅"))
        self.assertIsNone(extract_web_query("附近的充电站有哪些"))
        self.assertIsNone(extract_web_query("自动泊车怎么用"))
        self.assertIsNone(extract_web_query("查一下电量"))
        self.assertIsNone(try_web_search_utterance("打开空调"))
        self.assertIsNotNone(try_nearby_utterance("附近有什么好吃的"))
        self.assertIsNone(try_web_search_utterance("附近有什么好吃的"))

    def test_route_tool_call(self):
        route = try_web_search_utterance("帮我搜一下黄金价格")
        self.assertIsNotNone(route)
        self.assertEqual(route.intent, IntentType.TOOL)
        self.assertEqual(route.tool_calls[0].name, "web.search")
        self.assertEqual(route.tool_calls[0].arguments.get("query"), "黄金价格")


class TestChatWebQuery(unittest.TestCase):
    def test_movie_chat_needs_search(self):
        q = "我最近比较无聊想看电影，最近有什么比较好看的电影吗"
        self.assertIsNotNone(chat_web_query(q))
        self.assertIsNone(try_web_search_utterance(q))

    def test_followup_uses_recent_user_turn(self):
        recent = (
            "user: 我最近比较无聊想看电影，最近有什么比较好看的电影吗\n"
            "assistant: 最近口碑不错的有哪吒2\n"
        )
        q = "你说说这个电影好看在哪里"
        got = chat_web_query(q, recent)
        self.assertIsNotNone(got)
        self.assertIn("电影", got)
        self.assertIn("无聊想看电影", got)

    def test_not_search_on_plain_venting(self):
        self.assertIsNone(chat_web_query("今天工作不顺心，想吐槽一下"))
        self.assertIsNone(chat_web_query("打开空调"))
        self.assertIsNone(chat_web_query("附近有什么好吃的"))


class TestWebSearchCatalog(unittest.TestCase):
    def test_registered(self):
        spec = get_registry().get("web.search")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.domain, "web")

    def test_domain_catalog_hides_web_on_climate(self):
        cat = get_registry().prompt_catalog(["climate"])
        self.assertNotIn("web.search", cat)
        self.assertIn("web.search", get_registry().prompt_catalog(["web"]))


class TestWebSearchExec(unittest.TestCase):
    def test_mock_provider(self):
        hits = [
            {
                "title": "国内油价",
                "url": "https://example.com/oil",
                "snippet": "92号汽油 7.5 元",
                "source": "example.com",
            }
        ]
        with patch("app.websearch._CACHE", {}), patch(
            "app.websearch._providers",
            return_value=[("mock", lambda _q, _n: hits)],
        ):
            out = web_search("今天国内油价", 3)
        self.assertTrue(out["success"])
        self.assertEqual(out["data"]["provider"], "mock")
        self.assertEqual(out["data"]["results"][0]["title"], "国内油价")


if __name__ == "__main__":
    unittest.main()
