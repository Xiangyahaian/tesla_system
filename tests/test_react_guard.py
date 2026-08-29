# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from app.models import ToolCall
from app.nlu.react_guard import coerce_step_done, should_continue_after_success


class TestReactGuard(unittest.TestCase):
    def test_volume_forces_done(self):
        calls = [ToolCall(name="media.set_volume", arguments={"volume": 40})]
        self.assertTrue(coerce_step_done(calls, False))
        self.assertFalse(should_continue_after_success(calls, False))

    def test_climate_forces_done(self):
        calls = [ToolCall(name="climate.set_temperature", arguments={"temperature": 21})]
        self.assertTrue(coerce_step_done(calls, False))

    def test_search_nearby_keeps_done_false(self):
        calls = [ToolCall(name="maps.search_nearby", arguments={"keywords": "咖啡"})]
        self.assertFalse(coerce_step_done(calls, False))
        self.assertTrue(should_continue_after_success(calls, False))

    def test_empty_calls_done(self):
        self.assertTrue(coerce_step_done([], False))


if __name__ == "__main__":
    unittest.main()
