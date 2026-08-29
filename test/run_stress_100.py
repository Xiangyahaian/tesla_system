# -*- coding: utf-8 -*-
"""深度压测 100：独立用户+独立会话；冷门指令/多工具/上下文/压缩；HTML+MD+JSON。"""
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
    seq: int
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


def _inject_bulk(sess, n: int = 55, tool_chars: int = 1800) -> None:
    for i in range(n):
        sess.transcript.append(MessageRole.USER, f"深度压测填充轮{i}：方向盘加热儿童锁电台WiFi导航混合。")
        if i % 2 == 0:
            sess.transcript.append(
                MessageRole.TOOL,
                ("长工具输出#" + str(i) + "#") * max(1, tool_chars // 18),
                meta={"tool": "climate.get_state"},
            )
        else:
            sess.transcript.append(MessageRole.ASSISTANT, f"【填充】第{i}轮已执行。")


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
            checks.append(f"命中 {sorted(want & got)}")
        else:
            failed.append(f"未命中 期望任一 {sorted(want)} 实际 {sorted(got)}")

    if expect.get("persona_updated"):
        if rec.persona_updated or after["persona"] != before["persona"]:
            checks.append("persona✓")
        else:
            failed.append("persona 未更新")

    if expect.get("memories_updated"):
        bi = before["memories"].get("items") or []
        ai = after["memories"].get("items") or []
        if rec.memories_updated or ai != bi:
            checks.append("memories✓")
        else:
            failed.append("memories 未更新")

    if expect.get("preferences_updated"):
        if rec.preferences_updated or after["preferences"] != before["preferences"]:
            checks.append("preferences✓")
        else:
            failed.append("preferences 未更新")

    if expect.get("preferred_seat"):
        seat = after["preferences"].get("preferred_seat")
        if seat == expect["preferred_seat"]:
            checks.append(f"seat={seat}")
        else:
            failed.append(f"seat 期望 {expect['preferred_seat']} 实际 {seat}")

    if expect.get("memory_contains"):
        blob = json.dumps(after["memories"], ensure_ascii=False)
        if expect["memory_contains"] in blob:
            checks.append("记忆含词")
        else:
            failed.append(f"记忆不含「{expect['memory_contains']}」")

    if expect.get("no_profile_update"):
        changed = (
            rec.persona_updated
            or rec.memories_updated
            or rec.preferences_updated
            or after != before
        )
        if not changed:
            checks.append("画像无变")
        else:
            failed.append("画像意外变化")

    if expect.get("observe"):
        checks.append("观测")
        failed.clear()

    passed = len(failed) == 0 and (len(checks) > 0 or not expect)
    return passed, "；".join(checks) if passed else "；".join(failed)


def _run_turn(
    orch, session_id: str, seq: int, case_id: str, cat: str, query: str, expect: Dict[str, Any]
) -> TurnRecord:
    store = get_session_store()
    sess = store.get(session_id)
    rec = TurnRecord(seq=seq, case_id=case_id, category=cat, query=query)
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
                    calls = d.get("tool_calls") or []
                    if calls:
                        rec.tool_count = max(rec.tool_count, len(calls))
                        for c in calls:
                            if isinstance(c, dict):
                                n = str(c.get("name") or "")
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
    rec.answer_preview = _last_assistant(store.get(session_id))[:200]
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


def _write_markdown(path: Path, summary: Dict[str, Any], records: List[TurnRecord], compact: Optional[CompactRecord]) -> None:
    passed = sum(1 for r in records if r.passed)
    lines = [
        f"# Tesla Agent 深度压测 100",
        "",
        f"- **Run ID**: {summary.get('run_id')}",
        f"- **用户**: {summary.get('nickname')} (`{summary.get('user_id')}`)",
        f"- **会话**: `{summary.get('session_id')}`",
        f"- **模型**: {summary.get('model')}",
        f"- **完成**: {summary.get('finished_at')}",
        f"- **通过**: {passed}/{len(records)} ({100*passed/max(1,len(records)):.1f}%)",
        f"- **总 Token**: {summary.get('total_tokens', 0):,}",
        f"- **总墙钟**: {summary.get('total_wall_ms', 0)/1000:.1f}s",
        f"- **LLM 累计**: {summary.get('total_llm_ms', 0)/1000:.1f}s",
        "",
    ]
    if compact:
        ratio = (100.0 * (1 - compact.chars_after / compact.chars_before)) if compact.chars_before else 0
        lines += [
            f"## 压缩 ({compact.case_id})",
            f"- {compact.chars_before} → {compact.chars_after} chars（-{ratio:.1f}%）",
            f"- layers: {compact.layers}, {compact.wall_ms}ms, {'PASS' if compact.passed else 'FAIL'}",
            "",
        ]

    lines += [
        "## 分类统计",
        "",
        "| 类别 | 通过 | 失败 | Token | 墙钟ms | LLM ms | 工具次 | 通过率 |",
        "|------|------|------|-------|--------|--------|--------|--------|",
    ]
    for cat, st in (summary.get("by_category") or {}).items():
        n = max(1, int(st.get("count") or (st["pass"] + st["fail"])))
        rate = 100.0 * st["pass"] / n
        lines.append(
            f"| {cat} | {st['pass']} | {st['fail']} | {st['tokens']} | {st['ms']} | {st.get('llm_ms',0)} | {st.get('tools',0)} | {rate:.0f}% |"
        )

    lines += [
        "",
        "## 全量明细（按顺序）",
        "",
        "| # | ID | 类 | 输入 | 结果 | 意图 | 工具 | Token | 墙钟ms | LLM ms | 回复摘要 |",
        "|---|-----|-----|------|------|------|------|-------|--------|--------|----------|",
    ]
    for r in records:
        ok = "✓" if r.passed else "✗"
        q = r.query.replace("|", "/")[:36]
        ans = (r.answer_preview or "").replace("|", "/").replace("\n", " ")[:48]
        tools = ",".join(r.tools[:3])
        lines.append(
            f"| {r.seq} | {r.case_id} | {r.category} | {q} | {ok} | {r.intent} | {r.tool_count}({tools}) | {r.total_tokens} | {r.wall_ms} | {r.llm_elapsed_ms} | {ans} |"
        )

    fails = [r for r in records if not r.passed]
    if fails:
        lines += ["", "## 失败明细", ""]
        for r in fails:
            lines.append(f"- **{r.case_id}** `{r.query[:60]}` — {r.pass_reason}")
            if r.answer_preview:
                lines.append(f"  - 回复: {r.answer_preview[:120]}")

    path.write_text("\n".join(lines), encoding="utf-8")


def _bar(pct: float, color: str = "#2563eb") -> str:
    w = max(0, min(100, pct))
    return f"<div class='bar'><i style='width:{w:.1f}%;background:{color}'></i><span>{w:.0f}%</span></div>"


def _write_html(path: Path, summary: Dict[str, Any], records: List[TurnRecord], compact: Optional[CompactRecord]) -> None:
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
    for cat, st in (summary.get("by_category") or {}).items():
        n = max(1, int(st.get("count") or (st["pass"] + st["fail"])))
        rate = 100.0 * st["pass"] / n
        cat_rows.append(
            f"<tr><td>{html.escape(cat)}</td><td>{st['pass']}</td><td>{st['fail']}</td>"
            f"<td>{st['tokens']}</td><td>{st['ms']}</td><td>{st.get('llm_ms',0)}</td>"
            f"<td>{st.get('tools',0)}</td><td>{_bar(rate, '#16a34a' if rate >= 70 else '#dc2626')}</td></tr>"
        )
        cat_bars.append(f"<div class='cat-bar'><em>{html.escape(cat)}</em>{_bar(rate)}</div>")

    rows = []
    for r in records:
        status = "pass" if r.passed else "fail"
        tools = ",".join(r.tools[:4]) + ("…" if len(r.tools) > 4 else "")
        rows.append(
            f"<tr class='{status}'><td>{r.seq}</td><td>{html.escape(r.case_id)}</td>"
            f"<td>{html.escape(r.category)}</td>"
            f"<td class='q' title='{html.escape(r.query)}'>{html.escape(r.query[:52])}</td>"
            f"<td>{'✓' if r.passed else '✗'}</td>"
            f"<td>{r.wall_ms}<div class='mini'>{_bar(100.0*r.wall_ms/max_ms,'#7c3aed')}</div></td>"
            f"<td>{r.llm_elapsed_ms}</td>"
            f"<td>{r.total_tokens}<div class='mini'>{_bar(100.0*r.total_tokens/max_tok,'#0891b2')}</div></td>"
            f"<td>{html.escape(r.intent)}</td><td>{r.tool_count}<div class='tools'>{html.escape(tools)}</div></td>"
            f"<td title='{html.escape(r.pass_reason)}'>{html.escape((r.answer_preview or '')[:64])}</td></tr>"
        )

    compact_html = "<p class='mute'>未触发压缩</p>"
    if compact:
        ratio = (100.0 * (1 - compact.chars_after / compact.chars_before)) if compact.chars_before else 0
        compact_html = (
            f"<div class='card wide'><h3>压缩 {html.escape(compact.case_id)}</h3>"
            f"<p>{compact.chars_before}→{compact.chars_after} chars (-{ratio:.1f}%) · "
            f"{compact.wall_ms}ms · layers={html.escape(str(compact.layers))} · "
            f"<b>{'PASS' if compact.passed else 'FAIL'}</b></p></div>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>深度压测100 {html.escape(summary.get('run_id',''))}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --line:#e6e8ec; --text:#111827; --mute:#6b7280; }}
body {{ font-family:"PingFang SC","Segoe UI",system-ui,sans-serif; margin:0; background:var(--bg); color:var(--text); }}
.wrap {{ max-width:1320px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:1.4rem; margin:0 0 8px; }}
.meta {{ color:var(--mute); font-size:13px; margin-bottom:16px; }}
.grid {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin-bottom:16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; }}
.card b {{ display:block; font-size:1.35rem; }}
.card .lbl {{ font-size:11px; color:var(--mute); }}
.panel {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:14px; overflow:auto; }}
.bar {{ position:relative; height:8px; background:#eef2f7; border-radius:99px; margin-top:4px; }}
.bar i {{ display:block; height:100%; border-radius:99px; }}
.bar span {{ position:absolute; right:0; top:-14px; font-size:10px; color:var(--mute); }}
.mini .bar {{ height:5px; }} .mini .bar span {{ display:none; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th,td {{ border-bottom:1px solid #f0f1f4; padding:6px 7px; text-align:left; vertical-align:top; }}
th {{ background:#f8fafc; position:sticky; top:0; }}
tr.fail td {{ background:#fff7f7; }}
.q {{ max-width:220px; }} .tools {{ font-size:10px; color:var(--mute); }}
@media(max-width:900px){{ .grid{{ grid-template-columns:repeat(2,1fr); }} }}
</style></head><body><div class="wrap">
<h1>Tesla Agent · 深度压测 100</h1>
<div class="meta">用户 {html.escape(str(summary.get('nickname')))} · uid {html.escape(str(summary.get('user_id')))} ·
会话 <code>{html.escape(summary.get('session_id',''))}</code> · {html.escape(summary.get('finished_at',''))}</div>
<div class="grid">
  <div class="card"><span class="lbl">通过</span><b>{passed}</b>/ {len(records)}</div>
  <div class="card"><span class="lbl">失败</span><b>{fail}</b></div>
  <div class="card"><span class="lbl">总 Token</span><b>{total_tokens:,}</b></div>
  <div class="card"><span class="lbl">总耗时</span><b>{total_ms/1000:.1f}s</b></div>
  <div class="card"><span class="lbl">均耗时</span><b>{avg_ms:.0f}ms</b></div>
  <div class="card"><span class="lbl">均 Token</span><b>{avg_tok:.0f}</b></div>
</div>
<div class="panel"><h3>分类通过率</h3>{''.join(cat_bars)}</div>
{compact_html}
<h3>分类统计</h3><div class="panel" style="padding:0"><table>
<tr><th>类</th><th>过</th><th>败</th><th>Token</th><th>墙钟</th><th>LLM</th><th>工具</th><th>率</th></tr>
{''.join(cat_rows)}</table></div>
<h3>全量明细（100条顺序）</h3><div class="panel" style="padding:0;max-height:75vh"><table>
<tr><th>#</th><th>ID</th><th>类</th><th>输入</th><th>果</th><th>墙钟</th><th>LLM</th><th>Tok</th><th>意图</th><th>工具</th><th>回复/原因</th></tr>
{''.join(rows)}</table></div>
</div></body></html>"""
    path.write_text(doc, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tesla Agent 深度压测 100")
    parser.add_argument("--cases", default=str(TEST_DIR / "test_cases_stress_100_v2.json"))
    parser.add_argument("--report", default=str(TEST_DIR / "stress_100_report.html"))
    parser.add_argument("--markdown", default=str(TEST_DIR / "stress_100_report.md"))
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]

    cases_path = Path(args.cases)
    html_path = Path(args.report)
    md_path = Path(args.markdown)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    raw = json.loads(cases_path.read_text(encoding="utf-8"))
    prefix = str(raw.get("meta", {}).get("user_nickname_prefix") or "深度压测")
    nickname = f"{prefix}_{datetime.now().strftime('%m%d%H%M')}"
    run_id = f"stress_100_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    from app.llm.client import probe_local_llm

    probe = probe_local_llm(force=True)
    if not probe.get("ok"):
        print("本地模型不可用:", probe.get("error"))
        return 1

    store = get_session_store()
    home = store.ensure_user(nickname)
    user_id = str(home.slots.get("user_id") or home.user_id or "")
    sess = store.create_session(title=f"压测100-{run_id[-6:]}", owner_id=user_id)
    session_id = sess.session_id
    store.save(sess)

    orch = Orchestrator()
    records: List[TurnRecord] = []
    compact_rec: Optional[CompactRecord] = None
    t_all = time.perf_counter()
    seq = 0
    checkpoint = RESULTS_DIR / f"{run_id}_checkpoint.json"

    def _flush_checkpoint() -> None:
        checkpoint.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "user_id": user_id,
                    "session_id": session_id,
                    "nickname": nickname,
                    "done": len(records),
                    "compact": asdict(compact_rec) if compact_rec else None,
                    "turns": [asdict(r) for r in records],
                    "updated_at": datetime.now().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    print(f"新用户: {nickname} (uid={user_id})", flush=True)
    print(f"新会话: {session_id}", flush=True)
    print(f"用例: {len(raw['cases'])}  model: {config.VLLM_MODEL_NAME}", flush=True)
    print("-" * 60, flush=True)

    for c in raw["cases"]:
        cid, cat, q = c["id"], c["cat"], c["q"]
        expect = dict(c.get("expect") or {})
        if cat == "compact_mid":
            _inject_bulk(store.get(session_id))
            store.save(store.get(session_id))
            compact_rec = _run_compact(session_id, cid)
            print(
                f"[{cid}] compact {compact_rec.chars_before}->{compact_rec.chars_after} "
                f"{compact_rec.wall_ms}ms {'PASS' if compact_rec.passed else 'FAIL'}",
                flush=True,
            )
            _flush_checkpoint()
            continue
        seq += 1
        print(f"[{seq:03d}/{len(raw['cases'])-1}] {cid} {q[:40]}...", flush=True)
        rec = _run_turn(orch, session_id, seq, cid, cat, q, expect)
        records.append(rec)
        print(
            f"  {'PASS' if rec.passed else 'FAIL'} | {rec.wall_ms}ms | tok={rec.total_tokens} | "
            f"{rec.intent} tools={rec.tool_count} | {rec.pass_reason}",
            flush=True,
        )
        _flush_checkpoint()

    wall_all = int((time.perf_counter() - t_all) * 1000)
    snap = _snapshot(store.get(session_id))
    summary = {
        "run_id": run_id,
        "user_id": user_id,
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
    _write_markdown(md_path, summary, records, compact_rec)

    print("-" * 60)
    print(f"通过 {summary['turn_pass']}/{len(records)} | Token {summary['total_tokens']} | 墙钟 {wall_all/1000:.1f}s")
    print(f"HTML: {html_path}")
    print(f"MD:   {md_path}")
    print(f"JSON: {out_json}")
    return 0 if summary["turn_fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
