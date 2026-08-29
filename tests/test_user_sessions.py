# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.agent.memory import PreferenceDelta
from app.agent.types import MessageRole
from app.session.db import SessionDatabase
from app.session.store import SessionStore


class UserSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = SessionDatabase(root / "users.db")
        self.store = SessionStore(root=root / "sessions", db=self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _write_seat_pref(self, sess) -> None:
        sess.memory.upsert_preferences(
            PreferenceDelta(preferred_seat="front_right", climate_temps={"front_right": 22})
        )

    def test_same_nickname_same_memory(self):
        a = self.store.ensure_user("小明")
        self._write_seat_pref(a)
        b = self.store.ensure_user("小明")
        self.assertEqual(a.session_id, b.session_id)
        prefs = b.memory.load_preferences()
        self.assertEqual(prefs.get("preferred_seat"), "front_right")

    def test_nickname_id_uses_pinyin(self):
        a = self.store.ensure_user("象牙海岸")
        self.assertTrue(a.session_id.startswith("u_xiangyahaian"))
        self.assertNotIn("u_user_", a.session_id)
        b = self.store.ensure_user("Alice")
        self.assertEqual(b.session_id, "u_alice")
        c = self.store.ensure_user("芃澈")
        self.assertTrue(c.session_id.startswith("u_pengche"))

    def test_pinyin_collision_gets_short_suffix(self):
        # 人为占用同 slug，验证另一昵称不会撞车
        first = self.store.ensure_user("小明")
        self.assertEqual(first.session_id, "u_xiaoming")
        # 直接写入同 session_id 的假用户不可能；改测：第二个同拼音不同字用后缀
        # 「明明」与「小明」拼音不同；构造同 slug：Xiaoming 英文与 小明
        eng = self.store.ensure_user("xiaoming")
        self.assertNotEqual(eng.session_id, first.session_id)
        self.assertTrue(eng.session_id.startswith("u_xiaoming"))

    def test_different_nickname_isolated(self):
        a = self.store.ensure_user("小明")
        self._write_seat_pref(a)
        b = self.store.ensure_user("小红")
        self.assertNotEqual(a.session_id, b.session_id)
        prefs = b.memory.load_preferences()
        self.assertNotEqual(prefs.get("preferred_seat"), "front_right")

    def test_extra_session_shares_profile_and_vehicle_not_transcript(self):
        home = self.store.ensure_user("小明")
        self._write_seat_pref(home)
        extra = self.store.create_session(title="第二段对话", owner_id=home.slots["user_id"])
        self.assertEqual(extra.user_id, home.session_id)
        self.assertEqual(extra.user_root, home.user_root)
        self.assertIs(extra.gateway, home.gateway)
        self.assertEqual(extra.memory.memory_dir, home.memory.memory_dir)
        prefs = extra.memory.load_preferences()
        self.assertEqual(prefs.get("preferred_seat"), "front_right")

        home.transcript.append(MessageRole.USER, "主会话这句话")
        extra.transcript.append(MessageRole.USER, "新会话那句话")
        home_texts = [m.content for m in home.transcript.load()]
        extra_texts = [m.content for m in extra.transcript.load()]
        self.assertIn("主会话这句话", home_texts)
        self.assertNotIn("主会话这句话", extra_texts)
        self.assertIn("新会话那句话", extra_texts)
        self.assertNotIn("新会话那句话", home_texts)

        self.assertTrue((home.user_root / "vehicle.json").exists())
        mem_names = sorted(p.name for p in (home.user_root / "memory").iterdir() if p.is_file())
        self.assertEqual(mem_names, ["memories.md", "persona.md", "preferences.md"])
        self.assertEqual(extra.root.parent, home.user_root / "sessions")
        self.assertTrue((extra.root / "session.jsonl").exists())
        self.assertFalse((extra.root / "transcript.jsonl").exists())
        self.assertFalse((extra.root / "session.json").exists())
        self.assertFalse((extra.root / "vehicle.json").exists())
        self.assertFalse((extra.root / "memory").exists())

    def test_create_session_resets_vehicle_to_south_gate(self):
        from app.maps import BIT_ZHONGGUANCUN_SOUTH_GATE

        home = self.store.ensure_user("测新建会话")
        with home.gateway._lock:
            home.gateway._state["navigation"]["progress_m"] = 3200.0
            home.gateway._state["navigation"]["navigating"] = True
            home.gateway._state["navigation"]["destination"] = "测试目的地"
            home.gateway._state["dynamics"]["speed_kmh"] = 48.0
            home.gateway._persist()

        extra = self.store.create_session(title="新窗口", owner_id=home.slots["user_id"])
        snap = extra.gateway.snapshot()
        pos = snap.get("navigation", {}).get("position") or {}
        self.assertAlmostEqual(float(pos.get("lng")), float(BIT_ZHONGGUANCUN_SOUTH_GATE["lng"]), places=4)
        self.assertAlmostEqual(float(pos.get("lat")), float(BIT_ZHONGGUANCUN_SOUTH_GATE["lat"]), places=4)
        self.assertEqual(float(snap.get("dynamics", {}).get("speed_kmh") or 0), 0.0)
        self.assertEqual(float(snap.get("navigation", {}).get("progress_m") or 0), 0.0)
        self.assertFalse(snap.get("navigation", {}).get("navigating"))
        self.assertIsNone(snap.get("navigation", {}).get("destination"))

    def test_two_users_have_isolated_vehicles(self):
        a = self.store.ensure_user("隔离用户甲")
        b = self.store.ensure_user("隔离用户乙")
        self.assertIsNot(a.gateway, b.gateway)
        self.assertNotEqual(a.user_root, b.user_root)
        with a.gateway._lock:
            a.gateway._state["dynamics"]["speed_kmh"] = 77.0
            a.gateway._persist()
        snap_b = b.gateway.snapshot()
        self.assertNotEqual(float(snap_b.get("dynamics", {}).get("speed_kmh") or 0), 77.0)

        self.assertTrue((a.user_root / "vehicle.json").exists())
        self.assertTrue((b.user_root / "vehicle.json").exists())

    def test_legacy_flat_dir_migrates_into_user_layout(self):
        sid = "u_legacy_demo"
        flat = self.store.root / sid
        flat.mkdir(parents=True)
        (flat / "transcript.jsonl").write_text(
            '{"role":"user","content":"旧对话","ts":1.0,"meta":{}}\n',
            encoding="utf-8",
        )
        (flat / "memory").mkdir()
        (flat / "memory" / "preferences.json").write_text(
            '{"version":1,"preferred_seat":"rear_left","climate_temp_c":{},"climate_apply_all":false,"display_name":null,"music_pref":null,"updated_at":null}',
            encoding="utf-8",
        )
        sess = self.store.get(sid)
        self.assertEqual(sess.root, sess.user_root / "sessions" / sid)
        self.assertTrue((sess.root / "session.jsonl").exists())
        self.assertFalse((sess.root / "transcript.jsonl").exists())
        self.assertFalse((sess.root / "session.json").exists())
        self.assertFalse((sess.user_root / "transcript.jsonl").exists())
        self.assertTrue((sess.user_root / "memory" / "preferences.md").exists())
        self.assertFalse((sess.user_root / "memory" / "preferences.json").exists())
        self.assertIn("旧对话", [m.content for m in sess.transcript.load()])
        extra = self.store.create_session(title="迁出后的新会话", owner_id=sid)
        extra.transcript.append(MessageRole.USER, "新窗口")
        self.assertEqual(extra.memory.load_preferences().get("preferred_seat"), "rear_left")
        self.assertNotIn("旧对话", [m.content for m in extra.transcript.load()])
