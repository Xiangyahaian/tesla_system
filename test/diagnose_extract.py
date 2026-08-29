# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent.profile_extract import extract_preferences, extract_after_turn
from app.agent.user_profile import UserProfileStore
from app.llm.client import get_llm
from app.models import ProfileUpdatePlan

llm = get_llm("local")
store = UserProfileStore(Path("state/sessions/memtest_20260823_164817_480a548b"))

queries = [
    ("F-01", "我坐副驾，喜欢22度", "【听】副驾空调已调到22度。"),
    ("F-03", "以后空调全开21度", "【听】全车空调已设为21度。"),
    ("F-01_alt", "以后我坐副驾，空调默认22度", "【听】好的，记住了。"),
]
for label, q, a in queries:
    plan = ProfileUpdatePlan(preferences=True)
    pref, step = extract_preferences(llm, q, store.load_preferences(), a)
    rep = extract_after_turn(llm, store, q, a, profile_plan=plan)
    print("===", label, q)
    print("intent_decision:", json.dumps(rep.intent_decision, ensure_ascii=False))
    print("pref_delta:", pref)
    print("update_step:", json.dumps(step, ensure_ascii=False, default=str))
    print(
        "report:",
        rep.persona_updated,
        rep.memories_updated,
        rep.preferences_updated,
        rep.notes,
        rep.triage,
    )
    print("prefs:", json.dumps(store.load_preferences(), ensure_ascii=False))
    print()
