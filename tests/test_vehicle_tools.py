# -*- coding: utf-8 -*-
"""契约单测：Gateway / Tool / Policy / 相对调节 / schema 不漂移。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.gateway.stub import StubVehicleGateway
from app.models import ToolCall
from app.policy.engine import PolicyEngine
from app.tools.registry import get_registry


class TestVehicleTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"
        self.gw = StubVehicleGateway(self.path)
        self.reg = get_registry()

    def tearDown(self):
        self.tmp.cleanup()

    def test_climate_power_and_temp(self):
        r = self.reg.execute(self.gw, ToolCall(name="climate.set_power", arguments={"enable": True}))
        self.assertTrue(r.success)
        st = self.gw.snapshot()
        self.assertTrue(st["climate"]["power"])
        self.assertIsInstance(st["climate"]["zones"]["front_left"], dict)

        r = self.reg.execute(
            self.gw,
            ToolCall(name="climate.set_temperature", arguments={"temperature": 23, "zones": ["front_left"]}),
        )
        self.assertTrue(r.success)
        self.assertEqual(self.gw.snapshot()["climate"]["zones"]["front_left"]["temp"], 23.0)

    def test_relative_temp(self):
        self.reg.execute(self.gw, ToolCall(name="climate.set_temperature", arguments={"temperature": 24}))
        r = self.reg.execute(self.gw, ToolCall(name="climate.adjust_temperature", arguments={"delta": -2}))
        self.assertTrue(r.success)
        self.assertEqual(self.gw.snapshot()["climate"]["zones"]["front_left"]["temp"], 22.0)

    def test_window_schema_stays_object(self):
        r = self.reg.execute(
            self.gw,
            ToolCall(name="cabin.set_windows", arguments={"percent": 50, "positions": ["front_left"]}),
        )
        self.assertTrue(r.success)
        node = self.gw.snapshot()["cabin"]["windows"]["front_left"]
        self.assertIsInstance(node, dict)
        self.assertEqual(node["percent"], 50)

        r = self.reg.execute(
            self.gw,
            ToolCall(name="cabin.adjust_windows", arguments={"delta": 20, "positions": ["front_left"]}),
        )
        self.assertTrue(r.success)
        self.assertEqual(self.gw.snapshot()["cabin"]["windows"]["front_left"]["percent"], 70)

    def test_door_lock_schema(self):
        r = self.reg.execute(
            self.gw,
            ToolCall(name="cabin.set_door_locks", arguments={"locked": False, "positions": ["rear_right"]}),
        )
        self.assertTrue(r.success)
        node = self.gw.snapshot()["cabin"]["doors"]["rear_right"]
        self.assertEqual(node, {"locked": False})

    def test_music_library(self):
        r = self.reg.execute(
            self.gw,
            ToolCall(name="media.play_music", arguments={"artist": "周杰伦", "title": "晴天"}),
        )
        self.assertTrue(r.success)
        music = self.gw.snapshot()["media"]["music"]
        self.assertTrue(music["playing"])
        self.assertEqual(music["title"], "晴天")

    def test_policy_confirm_unlock(self):
        policy = PolicyEngine(self.reg)
        decision = policy.evaluate(
            [ToolCall(name="cabin.set_door_locks", arguments={"locked": False, "positions": ["front_left"]})],
            self.gw.snapshot(),
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.require_confirm)

    def test_invalid_tool_args(self):
        r = self.reg.execute(self.gw, ToolCall(name="climate.set_temperature", arguments={"temperature": 99}))
        self.assertFalse(r.success)


if __name__ == "__main__":
    unittest.main()
