# -*- coding: utf-8 -*-
"""综合压测：多工具 / 多意图 / 人设记忆偏好 / 边界 / 压缩；输出极简 HTML。"""
from __future__ import annotations

import html
import json
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config
from app.agent.types import MessageRole
from app.orchestrator.runtime import Orchestrator, _metrics_dict
from app.session.store import get_session_store

TEST_DIR = Path(__file__).resolve().parent
RESULTS_DIR = TEST_DIR / "results"
CASES_PATH = TEST_DIR / "test_cases_stress_50.json"


@dataclass
class TurnRecord:
    case_id: str
    category: str
    query: str
    wall_ms: int = 0
    intent: str = ""
    tool_count: int = 0
    persona_updated: bool = False
    memories_updated: bool = False
    preferences_updated: bool = False
    profile_intent: Dict[str, Any] = field(default_factory=dict)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_elapsed_ms: int = 0
    compact_layers: List[str] = field(default_factory=list)
    passed: bool = False
    pass_reason: str = ""
    error: str = ""


@dataclass
class CompactRecord:
    case_id: str
    chars_before: int = 0
    chars_after: int = 0
    layers: List[str] = field(default_factory=list)
    wall_ms: int = 0
    passed: bool = False


def _snapshot(sess) -> Dict[str, Any]:
    return {
        "persona": sess.memory.load_persona(),
        "memories": sess.memory.load_memories(),
        "preferences": sess.memory.load_preferences(),
    }


def _inject_bulk(sess, n: int = 45, tool_chars: int = 1500) -> None:
    for i in range(n):
        sess.transcript.append(MessageRole.USER, f"压测填充轮次{i}：查看空调车窗并闲聊。")
        if i % 2 == 0:
            sess.transcript.append(
                MessageRole.TOOL,
                "x" * tool_chars,
                meta={"tool": "climate.get_state"},
            )
        else:
            sess.transcript.append(MessageRole.ASSISTANT, f"【听】第{i}轮回复。")


def _judge(
    rec: TurnRecord,
    expect: Dict[str, Any],
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> Tuple[bool, str]:
    checks: List[str] = []
    failed: List[str] = []

    if expect.get("intent"):
        if rec.intent == expect["intent"]:
            checks.append(f"intent={rec.intent}")
        else:
            failed.append(f"intent 期望 {expect['intent']} 实际 {rec.intent}")

    if expect.get("persona_updated"):
        if rec.persona_updated or after["persona"] != before["persona"]:
            checks.append("persona 已更新")
        else:
            failed.append("persona 未更新")

    if expect.get("memories_updated"):
        bi = before["memories"].get("items") or []
        ai = after["memories"].get("items") or []
        if rec.memories_updated or ai != bi:
            checks.append("memories 已更新")
        else:
            failed.append("memories 未更新")

    if expect.get("preferences_updated"):
        if rec.preferences_updated or after["preferences"] != before["preferences"]:
            checks.append("preferences 已更新")
        else:
            failed.append("preferences 未更新")

    if expect.get("no_profile_update"):
        if not (rec.persona_updated or rec.memories_updated or rec.preferences_updated):
            if after == before:
                checks.append("画像无变化")
            else:
                failed.append("画像意外变化")
        else:
            failed.append("不应更新画像")

    if expect.get("tone"):
        tone = str(after["persona"].get("tone") or "")
        if tone == expect["tone"]:
            checks.append(f"tone={tone}")
        else:
            failed.append(f"tone 期望 {expect['tone']} 实际 {tone}")

    if expect.get("preferred_seat"):
        seat = after["preferences"].get("preferred_seat")
        if seat == expect["preferred_seat"]:
            checks.append(f"seat={seat}")
        else:
            failed.append(f"seat 期望 {expect['preferred_seat']} 实际 {seat}")

    if expect.get("temp"):
        temps = after["preferences"].get("climate_temp_c") or {}
        ok = any(abs(float(v) - float(expect["temp"])) < 0.5 for v in temps.values())
        if ok:
            checks.append("温度 OK")
        else:
            failed.append(f"温度未写入 {temps}")

    if expect.get("memory_contains"):
        blob = json.dumps(after["memories"], ensure_ascii=False)
        if expect["memory_contains"] in blob:
            checks.append("记忆含关键词")
        else:
            failed.append(f"记忆不含「{expect['memory_contains']}」")

    if expect.get("memory_not_contains"):
        blob = json.dumps(after["memories"], ensure_ascii=False)
        if expect["memory_not_contains"] not in blob:
            checks.append("记忆已删")
        else:
            failed.append(f"记忆仍含「{expect['memory_not_contains']}」")

    if expect.get("display_contains"):
        blob = json.dumps(after["preferences"], ensure_ascii=False)
        if expect["display_contains"] in blob:
            checks.append("称呼已写")
        else:
            failed.append(f"称呼不含「{expect['display_contains']}」")

    if expect.get("persona_default"):
        if str(after["persona"].get("tone") or "default") == "default":
            checks.append("persona default")
        else:
            failed.append("persona 未恢复 default")

    if expect.get("prefs_cleared"):
        prefs = after["preferences"]
        empty = not prefs.get("preferred_seat") and not (prefs.get("climate_temp_c") or {}) and not prefs.get("music_pref")
        if empty or rec.preferences_updated:
            checks.append("偏好已清/更新")
        else:
            failed.append("偏好未清空")

    if expect.get("observe"):
        checks.append("观测")
        failed.clear()

    passed = len(failed) == 0 and (len(checks) > 0 or not expect)
    reason = "；".join(checks) if passed else "；".join(failed)
    return passed, reason


def _run_turn(orch, session_id: str, case_id: str, cat: str, query: str, expect: Dict[str, Any]) -> TurnRecord:
    store = get_session_store()
    sess = store.get(session_id)
    rec = TurnRecord(case_id=case_id, category=cat, query=query)
    before = _snapshot(sess)
    t0 = time.perf_counter()
    metrics = None
    try:
        gen = orch.handle(query, session_id=session_id, model="local")
        while True:
            try:
                ev = next(gen)
                if ev.type == "profile":
                    d = ev.data or {}
                    rec.persona_updated = bool(d.get("persona_updated"))
                    rec.memories_updated = bool(d.get("memories_updated"))
                    rec.preferences_updated = bool(d.get("preferences_updated"))
                if ev.type == "intent":
                    d = ev.data or {}
                    rec.profile_intent = dict(d.get("profile_update") or {})
                    if d.get("tool_calls"):
                        rec.tool_count = len(d.get("tool_calls") or [])
                    if d.get("compact_layers"):
                        rec.compact_layers = list(d.get("compact_layers") or [])
                if ev.type == "final" and isinstance(ev.data, dict):
                    tr = ev.data.get("tool_result") or {}
                    if tr.get("task_count"):
                        rec.tool_count = int(tr.get("task_count") or rec.tool_count)
            except StopIteration as e:
                metrics = e.value
                break
    except Exception as e:
        rec.error = str(e)
        rec.wall_ms = int((time.perf_counter() - t0) * 1000)
        rec.passed = False
        rec.pass_reason = str(e)
        return rec

    rec.wall_ms = int((time.perf_counter() - t0) * 1000)
    after = _snapshot(store.get(session_id))
    if metrics:
        md = _metrics_dict(metrics)
        rec.intent = metrics.intent or rec.intent
        rec.llm_calls = int(md.get("llm_calls") or 0)
        rec.prompt_tokens = int(md.get("prompt_tokens") or 0)
        rec.completion_tokens = int(md.get("completion_tokens") or 0)
        rec.total_tokens = int(md.get("total_tokens") or 0)
        rec.llm_elapsed_ms = int(md.get("llm_elapsed_ms") or 0)
        if not rec.compact_layers:
            rec.compact_layers = list(md.get("compact_layers") or [])

    rec.passed, rec.pass_reason = _judge(rec, expect, before, after)
    return rec


def _run_compact(session_id: str, case_id: str) -> CompactRecord:
    from app.llm.client import get_llm

    store = get_session_store()
    sess = store.get(session_id)
    rec = CompactRecord(case_id=case_id)
    msgs = sess.transcript.load()
    rec.chars_before = store.compactor.total_chars(msgs)
    t0 = time.perf_counter()
    report = store.maybe_compact(sess, llm=get_llm("local"), force=True)
    rec.wall_ms = int((time.perf_counter() - t0) * 1000)
    msgs2 = store.get(session_id).transcript.load()
    rec.chars_after = store.compactor.total_chars(msgs2)
    if report:
        rec.layers = list(report.layers)
    rec.passed = rec.chars_after < rec.chars_before and bool(rec.layers)
    store.save(sess)
    return rec


def _cat_stats(records: List[TurnRecord]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for r in records:
        s = out.setdefault(r.category, {"pass": 0, "fail": 0, "tokens": 0, "ms": 0})
        if r.passed:
            s["pass"] += 1
        else:
            s["fail"] += 1
        s["tokens"] += r.total_tokens
        s["ms"] += r.wall_ms
    return out


def _write_html(path: Path, summary: Dict[str, Any], records: List[TurnRecord], compact: Optional[CompactRecord]) -> None:
    passed = sum(1 for r in records if r.passed)
    fail = len(records) - passed
    total_tokens = sum(r.total_tokens for r in records)
    total_ms = sum(r.wall_ms for r in records) + (compact.wall_ms if compact else 0)

    rows = []
    for r in records:
        status = "pass" if r.passed else "fail"
        pmf = f"{r.persona_updated}/{r.memories_updated}/{r.preferences_updated}"
        rows.append(
            f"<tr class='{status}'><td>{html.escape(r.case_id)}</td>"
            f"<td>{html.escape(r.category)}</td>"
            f"<td>{html.escape(r.query[:48])}</td>"
            f"<td>{r.wall_ms}</td><td>{r.total_tokens}</td>"
            f"<td>{html.escape(r.intent)}</td><td>{r.tool_count}</td><td>{pmf}</td>"
            f"<td>{'✓' if r.passed else '✗'} {html.escape(r.pass_reason[:60])}</td></tr>"
        )

    cat_rows = []
    for cat, st in (summary.get("by_category") or {}).items():
        cat_rows.append(
            f"<tr><td>{html.escape(cat)}</td><td>{st['pass']}</td><td>{st['fail']}</td>"
            f"<td>{st['tokens']}</td><td>{st['ms']}</td></tr>"
        )

    compact_html = ""
    if compact:
        compact_html = (
            f"<p>压缩 {compact.case_id}: {compact.chars_before}→{compact.chars_after} chars, "
            f"{compact.wall_ms}ms, layers={compact.layers}, "
            f"{'PASS' if compact.passed else 'FAIL'}</p>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>压测报告 {html.escape(summary.get('run_id', ''))}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#fafafa;color:#111}}
h1{{font-size:1.25rem;margin:0 0 8px}}
.meta{{color:#555;font-size:13px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}}
.card{{background:#fff;border:1px solid #e5e5e5;border-radius:8px;padding:12px}}
.card b{{display:block;font-size:22px}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff}}
th,td{{border:1px solid #eee;padding:6px 8px;text-align:left}}
th{{background:#f0f0f0}}
tr.fail td{{background:#fff5f5}}
tr.pass td{{background:#fff}}
</style></head><body>
<h1>Tesla Agent 综合压测</h1>
<div class="meta">会话 {html.escape(summary.get('session_id',''))} · 
模型 {html.escape(summary.get('model',''))} · 
{html.escape(summary.get('finished_at',''))}</div>
<div class="grid">
<div class="card">通过<b>{passed}</b> / {len(records)}</div>
<div class="card">失败<b>{fail}</b></div>
<div class="card">总 Token<b>{total_tokens}</b></div>
<div class="card">总耗时<b>{total_ms/1000:.1f}s</b></div>
</div>
<h2>分类</h2>
<table><tr><th>类别</th><th>通过</th><th>失败</th><th>Token</th><th>ms</th></tr>
{''.join(cat_rows)}</table>
{compact_html}
<h2>明细</h2>
<table><tr><th>ID</th><th>类</th><th>输入</th><th>ms</th><th>Token</th><th>意图</th><th>工具数</th><th>P/M/F</th><th>结果</th></tr>
{''.join(rows)}</table>
</body></html>"""
    path.write_text(doc, encoding="utf-8")


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    nickname = str(raw.get("meta", {}).get("user_nickname") or "压测专用")
    run_id = f"stress_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    from app.llm.client import probe_local_llm

    probe = probe_local_llm(force=True)
    if not probe.get("ok"):
        print("本地模型不可用:", probe.get("error"))
        return 1

    store = get_session_store()
    sess = store.ensure_user(nickname)
    session_id = sess.session_id
    store.save(sess)

    orch = Orchestrator()
    records: List[TurnRecord] = []
    compact_rec: Optional[CompactRecord] = None
    t_all = time.perf_counter()

    print(f"用户: {nickname}  session: {session_id}")
    print(f"用例: {len(raw['cases'])}  model: {config.VLLM_MODEL_NAME}")
    print("-" * 60)

    for c in raw["cases"]:
        cid, cat, q = c["id"], c["cat"], c["q"]
        expect = dict(c.get("expect") or {})
        if cat == "compact_mid":
            _inject_bulk(store.get(session_id))
            store.save(store.get(session_id))
            compact_rec = _run_compact(session_id, cid)
            print(f"[{cid}] compact {compact_rec.chars_before}->{compact_rec.chars_after} {compact_rec.wall_ms}ms")
            continue
        print(f"[{cid}] {q[:40]}...")
        rec = _run_turn(orch, session_id, cid, cat, q, expect)
        records.append(rec)
        print(
            f"  {'PASS' if rec.passed else 'FAIL'} | {rec.wall_ms}ms | tok={rec.total_tokens} "
            f"| {rec.intent} tools={rec.tool_count} | {rec.pass_reason}"
        )

    wall_all = int((time.perf_counter() - t_all) * 1000)
    snap = _snapshot(store.get(session_id))
    summary = {
        "run_id": run_id,
        "session_id": session_id,
        "nickname": nickname,
        "model": config.VLLM_MODEL_NAME,
        "endpoint": config.VLLM_API_BASE,
        "case_count": len(records),
        "turn_pass": sum(1 for r in records if r.passed),
        "turn_fail": sum(1 for r in records if not r.passed),
        "total_tokens": sum(r.total_tokens for r in records),
        "total_wall_ms": wall_all,
        "by_category": _cat_stats(records),
        "compact": asdict(compact_rec) if compact_rec else None,
        "final_profile": snap,
        "finished_at": datetime.now().isoformat(),
    }

    out_json = RESULTS_DIR / f"{run_id}_results.json"
    out_json.write_text(json.dumps({"summary": summary, "turns": [asdict(r) for r in records]}, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = TEST_DIR / "stress_report.html"
    _write_html(html_path, summary, records, compact_rec)

    print("-" * 60)
    print(f"通过 {summary['turn_pass']}/{len(records)} | Token {summary['total_tokens']} | {wall_all/1000:.1f}s")
    print(f"HTML: {html_path}")
    print(f"JSON: {out_json}")
    return 0 if summary["turn_fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
