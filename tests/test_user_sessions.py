# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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

    def test_same_nickname_same_memory(self):
        a = self.store.ensure_user("小明")
        a.memory.ingest_utterance("我坐副驾，喜欢22度")
        b = self.store.ensure_user("小明")
        self.assertEqual(a.session_id, b.session_id)
        prefs = b.memory.load_preferences()
        self.assertEqual(prefs.get("preferred_seat"), "front_right")
        self.assertEqual(prefs.get("climate_temp_c", {}).get("front_right"), 22.0)

    def test_different_nickname_isolated(self):
        a = self.store.ensure_user("小明")
        a.memory.ingest_utterance("我坐副驾，喜欢22度")
        b = self.store.ensure_user("小红")
        self.assertNotEqual(a.session_id, b.session_id)
        prefs = b.memory.load_preferences()
        self.assertNotEqual(prefs.get("preferred_seat"), "front_right")
        users = self.store.list_users()
        names = {u["nickname"] for u in users}
        self.assertIn("小明", names)
        self.assertIn("小红", names)

    def test_sqlite_user_login_count(self):
        self.store.ensure_user("阿特")
        self.store.ensure_user("阿特")
        self.store.ensure_user("阿特")
        row = self.db.get_user_by_nickname("阿特")
        self.assertIsNotNone(row)
        self.assertEqual(row["nickname"], "阿特")
        self.assertEqual(row["login_count"], 3)
        self.assertTrue(row["session_id"].startswith("u_"))
        # 持久化：新连接仍能读到
        db2 = SessionDatabase(Path(self.tmp.name) / "users.db")
        try:
            again = db2.get_user_by_nickname("阿特")
            self.assertIsNotNone(again)
            self.assertEqual(again["login_count"], 3)
            self.assertEqual(len(db2.list_users()), 1)
        finally:
            db2.close()

    def test_casefold_nickname_same_user(self):
        a = self.store.ensure_user("Alex")
        b = self.store.ensure_user("alex")
        self.assertEqual(a.session_id, b.session_id)
        self.assertEqual(len(self.db.list_users()), 1)


if __name__ == "__main__":
    unittest.main()
