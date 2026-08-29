# -*- coding: utf-8 -*-
"""用户画像：人设 / 身份记忆 / 偏好 按语义改写 Markdown。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.agent.memory import MemoryStore
from app.agent.profile_extract import extract_after_turn
from app.agent.user_profile import UserProfileStore
from app.models import ProfileUpdatePlan


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
        idx = min(self.calls - 1, len(self.responses) - 1)
        return self.responses[idx]


class ProfileExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = UserProfileStore(Path(self.tmp.name))
        self.mem = MemoryStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_persona_only(self):
        llm = MockLLM(
            [
                _md_reply(
                    persona="# 人设\n\n- 语气专业严谨，少说废话\n",
                )
            ]
        )
        report = extract_after_turn(llm, self.store, "希望你说话专业一点", "好的")
        self.assertTrue(report.persona_updated)
        self.assertEqual(self.store.load_persona()["tone"], "professional")
        self.assertIn("专业", self.store.read_persona_md())

    def test_memory_identity(self):
        llm = MockLLM(
            [
                _md_reply(
                    memories="# 身份记忆\n\n- 北京望京\n",
                )
            ]
        )
        report = extract_after_turn(llm, self.store, "我家住在望京", "记住了")
        self.assertTrue(report.memories_updated)
        items = self.store.load_memories()["items"]
        self.assertEqual(items[-1]["value"], "北京望京")

    def test_preferences_climate(self):
        llm = MockLLM(
            [
                _md_reply(
                    preferences="# 偏好\n\n- 全车默认 21 度\n",
                )
            ]
        )
        report = extract_after_turn(llm, self.store, "以后空调全开21度", "好")
        self.assertTrue(report.preferences_updated)
        prefs = self.store.load_preferences()
        self.assertTrue(prefs.get("climate_apply_all"))
        self.assertEqual(len(prefs.get("climate_temp_c") or {}), 5)

    def test_no_update_for_control(self):
        llm = MockLLM([_md_reply()])
        report = extract_after_turn(llm, self.store, "打开空调", "已打开")
        self.assertFalse(
            any([report.persona_updated, report.memories_updated, report.preferences_updated])
        )

    def test_nlu_empty_plan_skips_llm(self):
        llm = MockLLM([_md_reply(memories="# 身份记忆\n\n- 不该写入\n")])
        report = extract_after_turn(
            llm, self.store, "打开空调", "已打开", profile_plan=ProfileUpdatePlan()
        )
        self.assertEqual(llm.calls, 0)
        self.assertFalse(report.memories_updated)

    def test_semantic_not_bound_to_nlu_hint(self):
        llm = MockLLM(
            [
                _md_reply(
                    memories="# 身份记忆\n\n- 晚上开车容易犯困\n",
                )
            ]
        )
        report = extract_after_turn(
            llm,
            self.store,
            "我晚上开车容易犯困",
            "记下了",
            profile_plan=ProfileUpdatePlan(persona=True),
        )
        self.assertTrue(report.memories_updated)
        self.assertIn("犯困", self.store.read_memories_md())

    def test_memory_facade_extract(self):
        llm = MagicMock()
        llm.chat.return_value = _md_reply(
            persona="# 人设\n\n- 语气温柔陪伴\n",
        )
        report = self.mem.extract_after_turn(llm, "温柔一点", "好呀")
        self.assertTrue(report.persona_updated)

    def test_sanitize_drops_speculative_padding(self):
        """小模型灌水的「用户可能希望…」不得落盘。"""
        pad = "\n".join(
            [f"- 用户可能希望助手记住条目{i}" for i in range(30)]
        )
        llm = MockLLM(
            [
                _md_reply(
                    memories=(
                        "# 身份记忆\n\n"
                        "- 用户名叫赵照儿\n"
                        f"{pad}\n"
                    ),
                    preferences=(
                        "# 偏好\n\n"
                        "- 称呼：赵照儿\n"
                        "- 称呼：不要使用昵称\n"
                        "- 称呼：不要使用外号\n"
                        "- 称呼：不要使用艺名\n"
                    ),
                )
            ]
        )
        report = extract_after_turn(
            llm,
            self.store,
            "以后叫我赵照儿",
            "好",
            profile_plan=ProfileUpdatePlan(memory=True, preferences=True),
        )
        self.assertTrue(report.preferences_updated)
        self.assertFalse(report.memories_updated)
        mem = self.store.read_memories_md()
        self.assertNotIn("用户可能", mem)
        self.assertNotIn("赵照儿", mem)
        prefs = self.store.read_preferences_md()
        self.assertIn("赵照儿", prefs)
        self.assertLessEqual(prefs.count("称呼：不要"), 1)

    def test_name_preference_not_copied_to_all_docs(self):
        """「以后称呼我为X」只应写入 preferences，不能三份各写一遍。"""
        llm = MockLLM(
            [
                _md_reply(
                    persona="# 人设\n\n- 称呼：赵照\n",
                    memories="# 身份记忆\n\n- 用户姓名：赵照\n",
                    preferences="# 偏好\n\n- 称呼：赵照\n",
                )
            ]
        )
        report = extract_after_turn(
            llm,
            self.store,
            "我是说你以后称呼我为赵照",
            "好",
            profile_plan=ProfileUpdatePlan(persona=True),
        )
        self.assertTrue(report.preferences_updated)
        self.assertFalse(report.persona_updated)
        self.assertFalse(report.memories_updated)
        self.assertIn("赵照", self.store.read_preferences_md())
        self.assertNotIn("赵照", self.store.read_persona_md())
        self.assertNotIn("赵照", self.store.read_memories_md())


if __name__ == "__main__":
    unittest.main()
