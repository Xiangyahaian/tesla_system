# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.auth import can_manage_session, inspect_actor, is_admin_nickname, visible_sessions
from app.session.db import SessionDatabase
from app.session.store import SessionStore


class SessionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = SessionDatabase(root / "users.db")
        self.store = SessionStore(root=root / "sessions", db=self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_admin_nickname(self):
        self.assertTrue(is_admin_nickname("象牙海岸"))
        self.assertFalse(is_admin_nickname("小明"))

    def test_user_only_sees_own_sessions(self):
        admin = self.store.ensure_user("象牙海岸")
        ming = self.store.ensure_user("小明")
        extra = self.store.create_session(title="小明的第二会话", owner_id=ming.slots["user_id"])

        ming_list = visible_sessions(ming.session_id, store=self.store)
        ids = {s["session_id"] for s in ming_list}
        self.assertIn(ming.session_id, ids)
        self.assertIn(extra.session_id, ids)
        self.assertNotIn(admin.session_id, ids)

        admin_list = visible_sessions(admin.session_id, store=self.store)
        admin_ids = {s["session_id"] for s in admin_list}
        self.assertNotIn(ming.session_id, admin_ids)
        self.assertNotIn(extra.session_id, admin_ids)
        self.assertIn(admin.session_id, admin_ids)

    def test_admin_can_delete_other_users(self):
        self.store.ensure_user("象牙海岸")
        ming = self.store.ensure_user("小明")
        extra = self.store.create_session(title="小明的第二会话", owner_id=ming.slots["user_id"])
        blocked = self.store.delete_user_account("象牙海岸")
        self.assertFalse(blocked.get("ok"))
        gone = self.store.delete_user_account(ming.slots["user_id"])
        self.assertTrue(gone.get("ok"))
        nicks = {u["nickname"] for u in self.store.list_users()}
        self.assertNotIn("小明", nicks)
        self.assertIn("象牙海岸", nicks)
        self.assertFalse(extra.root.exists())

    def test_user_cannot_manage_others(self):
        admin = self.store.ensure_user("象牙海岸")
        ming = self.store.ensure_user("小明")
        extra = self.store.create_session(title="小明的第二会话", owner_id=ming.slots["user_id"])

        self.assertTrue(can_manage_session(ming.session_id, extra.session_id, store=self.store))
        self.assertFalse(can_manage_session(ming.session_id, admin.session_id, store=self.store))
        self.assertTrue(can_manage_session(admin.session_id, extra.session_id, store=self.store))

        home_del = self.store.delete_session(ming.session_id)
        self.assertFalse(home_del.get("ok"))
        extra_del = self.store.delete_session(extra.session_id)
        self.assertTrue(extra_del.get("ok"))

    def test_inspect_admin_role(self):
        admin = self.store.ensure_user("象牙海岸")
        info = inspect_actor(admin.session_id, store=self.store)
        self.assertEqual(info["role"], "admin")
        self.assertTrue(info["is_admin"])


if __name__ == "__main__":
    unittest.main()
