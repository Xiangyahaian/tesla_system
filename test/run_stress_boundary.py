# -*- coding: utf-8 -*-
"""能力边界压测：多工具 / 闲聊连贯 / 记忆维护 / 压缩；本地模型；HTML 可视化。"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
from dataclasses import asdict, dataclass, field
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


@dataclass
class TurnRecord:
    case_id: str
    category: str
    query: str
    wall_ms: int = 0
    intent: str = ""
    tool_count: int = 0
    tools: List[str] = field(default_factory=list)
    answer_preview: str = ""
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


def _inject_bulk(sess, n: int = 50, tool_chars: int = 1600) -> None:
    for i in range(n):
        sess.transcript.append(MessageRole.USER, f"边界压测填充{i}：空调车窗导航闲聊混合。")
        if i % 2 == 0:
            sess.transcript.append(
                MessageRole.TOOL,
                ("工具长输出#" + str(i) + "#") * max(1, tool_chars // 20),
                meta={"tool": "climate.get_state"},
            )
        else:
            sess.transcript.append(MessageRole.ASSISTANT, f"【听】填充回复第{i}轮。")


def _last_assistant(sess) -> str:
    for m in reversed(sess.transcript.load()):
        if m.role == MessageRole.ASSISTANT:
            return (m.content or "").strip()
    return ""


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

    if expect.get("intent_in"):
        allowed = list(expect["intent_in"] or [])
        if rec.intent in allowed:
            checks.append(f"intent∈{allowed}")
        else:
            failed.append(f"intent 期望∈{allowed} 实际 {rec.intent}")

    if expect.get("min_tools") is not None:
        need = int(expect["min_tools"])
        if rec.tool_count >= need:
            checks.append(f"tools>={need}({rec.tool_count})")
        else:
            failed.append(f"工具数不足 期望>={need} 实际 {rec.tool_count}")

    if expect.get("tools_any"):
        want = set(expect["tools_any"] or [])
        got = set(rec.tools or [])
        if want & got:
            checks.append(f"命中工具 {sorted(want & got)}")
        else:
            failed.append(f"未命中工具 期望任一 {sorted(want)} 实际 {sorted(got)}")

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

    if expect.get("preferred_seat"):
        seat = after["preferences"].get("preferred_seat")
        if seat == expect["preferred_seat"]:
            checks.append(f"seat={seat}")
        else:
            failed.append(f"seat 期望 {expect['preferred_seat']} 实际 {seat}")

    if expect.get("memory_contains"):
        blob = json.dumps(after["memories"], ensure_ascii=False)
        if expect["memory_contains"] in blob:
            checks.append("记忆含关键词")
        else:
            failed.append(f"记忆不含「{expect['memory_contains']}」")

    if expect.get("answer_contains"):
        if expect["answer_contains"] in (rec.answer_preview or ""):
            checks.append("回答含关键词")
        else:
            failed.append(f"回答不含「{expect['answer_contains']}」")

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
                    calls = d.get("tool_calls") or []
                    if calls:
                        rec.tool_count = max(rec.tool_count, len(calls))
                        names = [str(c.get("name") or "") for c in calls if isinstance(c, dict)]
                        for n in names:
                            if n and n not in rec.tools:
                                rec.tools.append(n)
                if ev.type == "final" and isinstance(ev.data, dict):
                    tr = ev.data.get("tool_result") or {}
                    if tr.get("task_count"):
                        rec.tool_count = max(rec.tool_count, int(tr.get("task_count") or 0))
                    for item in ev.data.get("tool_results") or []:
                        if isinstance(item, dict):
                            n = str(item.get("tool") or "")
                            if n and n not in rec.tools:
                                rec.tools.append(n)
                    tasks = tr.get("tasks") or []
                    for t in tasks:
                        if isinstance(t, dict):
                            n = str(t.get("script") or t.get("skill") or "")
                            if n and n not in rec.tools:
                                rec.tools.append(n)
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
    sess2 = store.get(session_id)
    after = _snapshot(sess2)
    rec.answer_preview = _last_assistant(sess2)[:180]
    if metrics:
        md = _metrics_dict(metrics)
        rec.intent = metrics.intent or rec.intent
        rec.llm_calls = int(md.get("llm_calls") or 0)
        rec.prompt_tokens = int(md.get("prompt_tokens") or 0)
        rec.completion_tokens = int(md.get("completion_tokens") or 0)
        rec.total_tokens = int(md.get("total_tokens") or 0)
        rec.llm_elapsed_ms = int(md.get("llm_elapsed_ms") or 0)
        if metrics.tools:
            for n in metrics.tools:
                if n and n not in rec.tools:
                    rec.tools.append(n)
            rec.tool_count = max(rec.tool_count, len(metrics.tools))
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
    store.save(store.get(session_id))
    return rec


def _cat_stats(records: List[TurnRecord]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in records:
        s = out.setdefault(
            r.category,
            {"pass": 0, "fail": 0, "tokens": 0, "ms": 0, "llm_ms": 0, "tools": 0, "count": 0},
        )
        s["count"] += 1
        if r.passed:
            s["pass"] += 1
        else:
            s["fail"] += 1
        s["tokens"] += r.total_tokens
        s["ms"] += r.wall_ms
        s["llm_ms"] += r.llm_elapsed_ms
        s["tools"] += r.tool_count
    return out


def _bar(pct: float, color: str = "#2563eb") -> str:
    w = max(0, min(100, pct))
    return (
        f"<div class='bar'><i style='width:{w:.1f}%;background:{color}'></i>"
        f"<span>{w:.0f}%</span></div>"
    )


def _write_html(
    path: Path,
    summary: Dict[str, Any],
    records: List[TurnRecord],
    compact: Optional[CompactRecord],
) -> None:
    passed = sum(1 for r in records if r.passed)
    fail = len(records) - passed
    total_tokens = sum(r.total_tokens for r in records)
    total_ms = sum(r.wall_ms for r in records) + (compact.wall_ms if compact else 0)
    total_llm_ms = sum(r.llm_elapsed_ms for r in records)
    avg_ms = (sum(r.wall_ms for r in records) / len(records)) if records else 0
    avg_tok = (total_tokens / len(records)) if records else 0
    max_ms = max((r.wall_ms for r in records), default=1) or 1
    max_tok = max((r.total_tokens for r in records), default=1) or 1

    cat_rows = []
    cat_bars = []
    by_cat = summary.get("by_category") or {}
    for cat, st in by_cat.items():
        n = max(1, int(st.get("count") or (st["pass"] + st["fail"])))
        rate = 100.0 * st["pass"] / n
        cat_rows.append(
            f"<tr><td>{html.escape(cat)}</td><td>{st['pass']}</td><td>{st['fail']}</td>"
            f"<td>{st['tokens']}</td><td>{st['ms']}</td><td>{st.get('llm_ms', 0)}</td>"
            f"<td>{st.get('tools', 0)}</td><td>{_bar(rate, '#16a34a' if rate >= 70 else '#dc2626')}</td></tr>"
        )
        cat_bars.append(
            f"<div class='cat-bar'><em>{html.escape(cat)}</em>{_bar(rate)}</div>"
        )

    rows = []
    for r in records:
        status = "pass" if r.passed else "fail"
        pmf = f"{int(r.persona_updated)}/{int(r.memories_updated)}/{int(r.preferences_updated)}"
        tools = ",".join(r.tools[:4]) + ("…" if len(r.tools) > 4 else "")
        rows.append(
            f"<tr class='{status}'>"
            f"<td>{html.escape(r.case_id)}</td>"
            f"<td>{html.escape(r.category)}</td>"
            f"<td class='q' title='{html.escape(r.query)}'>{html.escape(r.query[:56])}</td>"
            f"<td>{r.wall_ms}<div class='mini'>{_bar(100.0 * r.wall_ms / max_ms, '#7c3aed')}</div></td>"
            f"<td>{r.llm_elapsed_ms}</td>"
            f"<td>{r.total_tokens}<div class='mini'>{_bar(100.0 * r.total_tokens / max_tok, '#0891b2')}</div></td>"
            f"<td>{r.prompt_tokens}/{r.completion_tokens}</td>"
            f"<td>{html.escape(r.intent)}</td>"
            f"<td>{r.tool_count}<div class='tools'>{html.escape(tools)}</div></td>"
            f"<td>{pmf}</td>"
            f"<td>{'✓' if r.passed else '✗'} {html.escape(r.pass_reason[:70])}</td>"
            f"</tr>"
        )

    fail_rows = []
    for r in records:
        if r.passed:
            continue
        fail_rows.append(
            f"<tr><td>{html.escape(r.case_id)}</td>"
            f"<td>{html.escape(r.query[:80])}</td>"
            f"<td>{html.escape(r.pass_reason)}</td>"
            f"<td>{html.escape((r.answer_preview or '')[:100])}</td></tr>"
        )

    compact_html = "<p class='mute'>本轮未触发压缩用例</p>"
    if compact:
        ratio = (100.0 * (1 - compact.chars_after / compact.chars_before)) if compact.chars_before else 0
        compact_html = (
            f"<div class='card wide'><h3>压缩 {html.escape(compact.case_id)}</h3>"
            f"<p>{compact.chars_before} → {compact.chars_after} chars "
            f"（压缩 {ratio:.1f}%）· {compact.wall_ms} ms · "
            f"layers={html.escape(str(compact.layers))} · "
            f"<b>{'PASS' if compact.passed else 'FAIL'}</b></p>"
            f"{_bar(ratio, '#ea580c')}</div>"
        )

    profile = summary.get("final_profile") or {}
    mem_items = (profile.get("memories") or {}).get("items") or []
    profile_html = (
        f"<pre>{html.escape(json.dumps({'persona': profile.get('persona'), 'preferences': profile.get('preferences'), 'memories_n': len(mem_items), 'memories_sample': mem_items[:5]}, ensure_ascii=False, indent=2))}</pre>"
    )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>能力边界压测 {html.escape(summary.get('run_id', ''))}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --line:#e6e8ec; --text:#111827; --mute:#6b7280; }}
* {{ box-sizing:border-box; }}
body {{ font-family: "Segoe UI", "PingFang SC", "Noto Sans SC", system-ui, sans-serif;
  margin:0; background:linear-gradient(180deg,#eef2ff 0%, var(--bg) 28%); color:var(--text); }}
.wrap {{ max-width:1280px; margin:0 auto; padding:28px 20px 60px; }}
h1 {{ font-size:1.45rem; margin:0 0 6px; letter-spacing:-0.02em; }}
h2 {{ font-size:1.05rem; margin:28px 0 12px; }}
h3 {{ font-size:0.95rem; margin:0 0 8px; }}
.meta {{ color:var(--mute); font-size:13px; margin-bottom:18px; }}
.grid {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; margin-bottom:18px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px;
  box-shadow:0 1px 0 rgba(15,23,42,.03); }}
.card.wide {{ margin-top:12px; }}
.card b {{ display:block; font-size:1.45rem; margin-top:4px; }}
.card .lbl {{ font-size:12px; color:var(--mute); }}
.panel {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin-bottom:16px; }}
.bar {{ position:relative; height:10px; background:#eef2f7; border-radius:999px; overflow:hidden; margin-top:6px; }}
.bar i {{ display:block; height:100%; border-radius:999px; }}
.bar span {{ position:absolute; right:0; top:-16px; font-size:11px; color:var(--mute); }}
.mini .bar {{ margin-top:4px; height:6px; }}
.mini .bar span {{ display:none; }}
.cat-bar {{ margin:8px 0; }}
.cat-bar em {{ font-style:normal; font-size:12px; color:var(--mute); }}
table {{ width:100%; border-collapse:collapse; font-size:12.5px; background:#fff; }}
th,td {{ border-bottom:1px solid #f0f1f4; padding:8px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f8fafc; position:sticky; top:0; z-index:1; font-weight:600; }}
tr.fail td {{ background:#fff7f7; }}
.q {{ max-width:240px; }}
.tools {{ color:var(--mute); font-size:11px; margin-top:2px; word-break:break-all; }}
pre {{ background:#0b1220; color:#e5e7eb; padding:12px; border-radius:10px; overflow:auto; font-size:12px; }}
.mute {{ color:var(--mute); }}
@media (max-width:960px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} }}
</style></head><body>
<div class="wrap">
<h1>Tesla Agent · 能力边界压测</h1>
<div class="meta">
  用户 {html.escape(str(summary.get('nickname') or ''))} ·
  会话 <code>{html.escape(summary.get('session_id',''))}</code> ·
  模型 {html.escape(summary.get('model',''))} ·
  {html.escape(summary.get('finished_at',''))} ·
  焦点：多工具 / 闲聊 / 记忆 / 压缩
</div>

<div class="grid">
  <div class="card"><span class="lbl">通过</span><b>{passed}</b><span class="mute">/ {len(records)}</span></div>
  <div class="card"><span class="lbl">失败</span><b>{fail}</b></div>
  <div class="card"><span class="lbl">总 Token</span><b>{total_tokens:,}</b></div>
  <div class="card"><span class="lbl">总耗时</span><b>{total_ms/1000:.1f}s</b></div>
  <div class="card"><span class="lbl">均耗时</span><b>{avg_ms:.0f}ms</b></div>
  <div class="card"><span class="lbl">均 Token</span><b>{avg_tok:.0f}</b></div>
</div>

<div class="panel">
  <h3>分类通过率</h3>
  {''.join(cat_bars) or '<p class="mute">无</p>'}
  <p class="mute" style="margin-top:12px">LLM 累计耗时 {total_llm_ms/1000:.1f}s · 墙钟 {summary.get('total_wall_ms', total_ms)/1000:.1f}s</p>
</div>

{compact_html}

<h2>分类统计</h2>
<div class="panel" style="padding:0; overflow:auto">
<table>
<tr><th>类别</th><th>通过</th><th>失败</th><th>Token</th><th>墙钟 ms</th><th>LLM ms</th><th>工具次数</th><th>通过率</th></tr>
{''.join(cat_rows)}
</table>
</div>

<h2>失败明细</h2>
<div class="panel" style="padding:0; overflow:auto">
<table>
<tr><th>ID</th><th>输入</th><th>原因</th><th>回答摘录</th></tr>
{''.join(fail_rows) or '<tr><td colspan="4">无失败</td></tr>'}
</table>
</div>

<h2>全部明细（每步耗时 / Token）</h2>
<div class="panel" style="padding:0; overflow:auto; max-height:70vh">
<table>
<tr>
  <th>ID</th><th>类</th><th>输入</th><th>墙钟 ms</th><th>LLM ms</th>
  <th>Token</th><th>P/C</th><th>意图</th><th>工具</th><th>P/M/F</th><th>结果</th>
</tr>
{''.join(rows)}
</table>
</div>

<h2>最终画像快照</h2>
<div class="panel">{profile_html}</div>
</div>
</body></html>"""
    path.write_text(doc, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tesla Agent 能力边界压测")
    parser.add_argument(
        "--cases",
        default=str(TEST_DIR / "test_cases_stress_boundary_50.json"),
        help="用例 JSON 路径",
    )
    parser.add_argument(
        "--report",
        default=str(TEST_DIR / "stress_boundary_report.html"),
        help="HTML 报告输出路径",
    )
    args = parser.parse_args()
    # RAG / FlagEmbedding 等第三方可能再 parse sys.argv，避免吃掉我们的参数
    sys.argv = [sys.argv[0]]

    cases_path = Path(args.cases)
    html_path = Path(args.report)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    raw = json.loads(cases_path.read_text(encoding="utf-8"))
    nickname = str(raw.get("meta", {}).get("user_nickname") or "边界压测甲")
    run_id = f"stress_boundary_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    from app.llm.client import probe_local_llm

    probe = probe_local_llm(force=True)
    if not probe.get("ok"):
        print("本地模型不可用:", probe.get("error"))
        return 1

    store = get_session_store()
    sess = store.ensure_user(nickname)
    session_id = sess.session_id
    # 独立干净会话：重置主会话内容，保留用户目录
    store.reset(session_id)
    sess = store.get(session_id)
    store.save(sess)

    orch = Orchestrator()
    records: List[TurnRecord] = []
    compact_rec: Optional[CompactRecord] = None
    t_all = time.perf_counter()

    print(f"用户: {nickname}  session: {session_id}")
    print(f"用例: {len(raw['cases'])}  model: {config.VLLM_MODEL_NAME}")
    print(f"端点: {config.VLLM_API_BASE}")
    print("-" * 60)

    for c in raw["cases"]:
        cid, cat, q = c["id"], c["cat"], c["q"]
        expect = dict(c.get("expect") or {})
        if cat == "compact_mid":
            _inject_bulk(store.get(session_id))
            store.save(store.get(session_id))
            compact_rec = _run_compact(session_id, cid)
            print(
                f"[{cid}] compact {compact_rec.chars_before}->{compact_rec.chars_after} "
                f"{compact_rec.wall_ms}ms {'PASS' if compact_rec.passed else 'FAIL'}"
            )
            continue
        print(f"[{cid}] {q[:42]}...")
        rec = _run_turn(orch, session_id, cid, cat, q, expect)
        records.append(rec)
        print(
            f"  {'PASS' if rec.passed else 'FAIL'} | {rec.wall_ms}ms | llm={rec.llm_elapsed_ms}ms "
            f"| tok={rec.total_tokens} | {rec.intent} tools={rec.tool_count} {rec.tools[:3]} | {rec.pass_reason}"
        )

    wall_all = int((time.perf_counter() - t_all) * 1000)
    snap = _snapshot(store.get(session_id))
    summary = {
        "run_id": run_id,
        "session_id": session_id,
        "nickname": nickname,
        "model": config.VLLM_MODEL_NAME,
        "endpoint": config.VLLM_API_BASE,
        "cases_file": str(cases_path),
        "case_count": len(records),
        "turn_pass": sum(1 for r in records if r.passed),
        "turn_fail": sum(1 for r in records if not r.passed),
        "total_tokens": sum(r.total_tokens for r in records),
        "total_prompt_tokens": sum(r.prompt_tokens for r in records),
        "total_completion_tokens": sum(r.completion_tokens for r in records),
        "total_wall_ms": wall_all,
        "total_llm_ms": sum(r.llm_elapsed_ms for r in records),
        "by_category": _cat_stats(records),
        "compact": asdict(compact_rec) if compact_rec else None,
        "final_profile": snap,
        "finished_at": datetime.now().isoformat(),
    }

    out_json = RESULTS_DIR / f"{run_id}_results.json"
    out_json.write_text(
        json.dumps({"summary": summary, "turns": [asdict(r) for r in records]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_html(html_path, summary, records, compact_rec)

    print("-" * 60)
    print(
        f"通过 {summary['turn_pass']}/{len(records)} | Token {summary['total_tokens']} | "
        f"墙钟 {wall_all/1000:.1f}s | LLM {summary['total_llm_ms']/1000:.1f}s"
    )
    print(f"HTML: {html_path}")
    print(f"JSON: {out_json}")
    return 0 if summary["turn_fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
