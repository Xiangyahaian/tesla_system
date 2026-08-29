# -*- coding: utf-8 -*-
"""真实测试：人设 / 记忆 / 偏好抽取 + 上下文压缩。使用本地 vLLM。"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 项目根
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config
from app.agent.compact import ContextCompactor
from app.agent.types import MessageRole, TranscriptMessage
from app.orchestrator.runtime import Orchestrator, _metrics_dict
from app.session.store import get_session_store


TEST_DIR = Path(__file__).resolve().parent
RESULTS_DIR = TEST_DIR / "results"
SESSION_PREFIX = f"memtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class TurnRecord:
    case_id: str
    category: str
    query: str
    wall_ms: int = 0
    intent: str = ""
    answer_preview: str = ""
    persona_updated: bool = False
    memories_updated: bool = False
    preferences_updated: bool = False
    triage: Dict[str, Any] = field(default_factory=dict)
    profile_notes: List[str] = field(default_factory=list)
    compact_layers: List[str] = field(default_factory=list)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_elapsed_ms: int = 0
    token_source: str = "none"
    transcript_chars_before: int = 0
    transcript_chars_after: int = 0
    persona: Dict[str, Any] = field(default_factory=dict)
    memories: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    passed: bool = False
    pass_reason: str = ""


@dataclass
class CompactRecord:
    case_id: str
    transcript_msgs_before: int = 0
    transcript_chars_before: int = 0
    transcript_msgs_after: int = 0
    transcript_chars_after: int = 0
    layers: List[str] = field(default_factory=list)
    summary: str = ""
    persona_unchanged: bool = True
    memories_unchanged: bool = True
    preferences_unchanged: bool = True
    wall_ms: int = 0
    passed: bool = False
    pass_reason: str = ""


def _snapshot_profile(sess) -> Dict[str, Any]:
    return {
        "persona": sess.memory.load_persona(),
        "memories": sess.memory.load_memories(),
        "preferences": sess.memory.load_preferences(),
    }


def _run_turn(
    orch: Orchestrator,
    session_id: str,
    case_id: str,
    category: str,
    query: str,
    expect: Dict[str, Any],
) -> TurnRecord:
    store = get_session_store()
    sess = store.get(session_id)
    rec = TurnRecord(case_id=case_id, category=category, query=query)
    rec.transcript_chars_before = sess.transcript.total_chars()

    snap_before = _snapshot_profile(sess)
    t0 = time.perf_counter()
    events: List[Dict[str, Any]] = []
    metrics = None
    try:
        gen = orch.handle(query, session_id=session_id, model="local")
        while True:
            try:
                ev = next(gen)
                events.append({"type": ev.type, "data": ev.data})
                if ev.type == "profile":
                    rec.persona_updated = bool((ev.data or {}).get("persona_updated"))
                    rec.memories_updated = bool((ev.data or {}).get("memories_updated"))
                    rec.preferences_updated = bool((ev.data or {}).get("preferences_updated"))
                    rec.profile_notes = list((ev.data or {}).get("notes") or [])
                    rec.triage = dict((ev.data or {}).get("triage") or {})
                if ev.type == "intent":
                    rec.compact_layers = list((ev.data or {}).get("compact_layers") or [])
                if ev.type == "final" and isinstance(ev.data, dict):
                    rec.answer_preview = str(ev.data.get("answer") or ev.data.get("text") or "")[:300]
            except StopIteration as e:
                metrics = e.value
                break
    except Exception as e:
        rec.error = str(e)
        rec.wall_ms = int((time.perf_counter() - t0) * 1000)
        rec.passed = False
        rec.pass_reason = f"异常: {e}"
        return rec

    rec.wall_ms = int((time.perf_counter() - t0) * 1000)
    sess = store.get(session_id)
    rec.transcript_chars_after = sess.transcript.total_chars()
    snap_after = _snapshot_profile(sess)
    rec.persona = snap_after["persona"]
    rec.memories = snap_after["memories"]
    rec.preferences = snap_after["preferences"]

    if metrics is not None:
        md = _metrics_dict(metrics)
        rec.intent = metrics.intent
        rec.llm_calls = int(md.get("llm_calls") or 0)
        rec.prompt_tokens = int(md.get("prompt_tokens") or 0)
        rec.completion_tokens = int(md.get("completion_tokens") or 0)
        rec.total_tokens = int(md.get("total_tokens") or 0)
        rec.llm_elapsed_ms = int(md.get("llm_elapsed_ms") or 0)
        rec.token_source = str(md.get("token_source") or "none")
        if not rec.compact_layers:
            rec.compact_layers = list(md.get("compact_layers") or [])

    # 判定
    checks: List[str] = []
    failed: List[str] = []
    if expect.get("persona_updated"):
        if rec.persona_updated or snap_after["persona"] != snap_before["persona"]:
            checks.append("persona 已更新")
        else:
            failed.append("persona 未更新")
    if expect.get("memories_updated"):
        items = snap_after["memories"].get("items") or []
        before_items = snap_before["memories"].get("items") or []
        if rec.memories_updated or len(items) > len(before_items) or items != before_items:
            checks.append("memories 已更新")
        else:
            failed.append("memories 未更新")
    if expect.get("preferences_updated"):
        if rec.preferences_updated or snap_after["preferences"] != snap_before["preferences"]:
            checks.append("preferences 已更新")
        else:
            failed.append("preferences 未更新")
    if expect.get("no_profile_update"):
        if not (rec.persona_updated or rec.memories_updated or rec.preferences_updated):
            if snap_after == snap_before:
                checks.append("画像无变化")
            else:
                failed.append("画像意外变化")
        else:
            failed.append("不应触发画像更新")
    if expect.get("tone"):
        tone = str(snap_after["persona"].get("tone") or "")
        if tone == expect["tone"]:
            checks.append(f"tone={tone}")
        else:
            failed.append(f"tone 期望 {expect['tone']} 实际 {tone}")
    if expect.get("preferred_seat"):
        seat = snap_after["preferences"].get("preferred_seat")
        if seat == expect["preferred_seat"]:
            checks.append(f"seat={seat}")
        else:
            failed.append(f"seat 期望 {expect['preferred_seat']} 实际 {seat}")
    if expect.get("memory_contains"):
        blob = json.dumps(snap_after["memories"], ensure_ascii=False)
        if expect["memory_contains"] in blob:
            checks.append("记忆含关键词")
        else:
            failed.append(f"记忆不含「{expect['memory_contains']}」")
    if expect.get("temp"):
        temps = snap_after["preferences"].get("climate_temp_c") or {}
        found = any(abs(float(v) - float(expect["temp"])) < 0.5 for v in temps.values())
        if found or (expect.get("preferences_updated") and rec.preferences_updated):
            checks.append("温度偏好已写")
        else:
            failed.append(f"温度偏好未写入 {temps}")
    if expect.get("persona_default"):
        tone = str(snap_after["persona"].get("tone") or "default")
        if tone == "default":
            checks.append("persona 已恢复 default")
        else:
            failed.append(f"persona 未恢复 default，tone={tone}")
    if expect.get("memory_not_contains"):
        blob = json.dumps(snap_after["memories"], ensure_ascii=False)
        if expect["memory_not_contains"] not in blob:
            checks.append("记忆已删除关键词")
        else:
            failed.append(f"记忆仍含「{expect['memory_not_contains']}」")
    if expect.get("prefs_cleared"):
        prefs = snap_after["preferences"]
        empty = not prefs.get("preferred_seat") and not (prefs.get("climate_temp_c") or {}) and not prefs.get("music_pref")
        if empty or rec.preferences_updated:
            checks.append("偏好已清空或更新")
        else:
            failed.append(f"偏好未清空 {prefs}")
    if expect.get("observe"):
        checks.append(expect.get("note") or "观测用例无硬性断言")
        failed.clear()

    rec.passed = len(failed) == 0 and (len(checks) > 0 or not expect)
    rec.pass_reason = "；".join(checks) if rec.passed else "；".join(failed)
    return rec


def _inject_bulk_transcript(sess, n_turns: int = 35, tool_chars: int = 1200) -> None:
    """注入超长 transcript 以触发压缩。"""
    for i in range(n_turns):
        sess.transcript.append(MessageRole.USER, f"测试轮次{i}：帮我看看空调温度和车窗状态，顺便聊聊今天心情。")
        if i % 2 == 0:
            blob = "x" * tool_chars
            sess.transcript.append(
                MessageRole.TOOL,
                f"climate.snapshot={blob}",
                meta={"tool": "climate.get_state"},
            )
        else:
            sess.transcript.append(MessageRole.ASSISTANT, f"【听】这是第{i}轮回复，空调开着，车窗关着。")


def _load_cases(path: Optional[Path] = None) -> List[tuple]:
    env_path = os.environ.get("TEST_CASES_FILE")
    if path is None and env_path:
        path = Path(env_path)
    if path is None:
        path = TEST_DIR / "test_cases.json"
    if not path.is_absolute():
        path = TEST_DIR / path.name
    if not path.exists():
        path = TEST_DIR / "test_cases.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for c in raw.get("cases") or []:
            out.append((c["id"], c["cat"], c["q"], dict(c.get("expect") or {})))
        return out
    return []


def _run_compact_test(session_id: str, case_id: str = "C-01_force_compact") -> CompactRecord:
    store = get_session_store()
    sess = store.get(session_id)
    rec = CompactRecord(case_id=case_id)
    snap_before = _snapshot_profile(sess)

    msgs_before = sess.transcript.load()
    rec.transcript_msgs_before = len(msgs_before)
    rec.transcript_chars_before = store.compactor.total_chars(msgs_before)

    from app.llm.client import get_llm

    llm = get_llm("local")
    t0 = time.perf_counter()
    report = store.maybe_compact(sess, llm=llm, force=True)
    rec.wall_ms = int((time.perf_counter() - t0) * 1000)

    sess = store.get(session_id)
    msgs_after = sess.transcript.load()
    rec.transcript_msgs_after = len(msgs_after)
    rec.transcript_chars_after = store.compactor.total_chars(msgs_after)
    snap_after = _snapshot_profile(sess)

    if report:
        rec.layers = list(report.layers)
        rec.summary = str(report.summary or "")[:500]

    rec.persona_unchanged = snap_before["persona"] == snap_after["persona"]
    rec.memories_unchanged = snap_before["memories"] == snap_after["memories"]
    rec.preferences_unchanged = snap_before["preferences"] == snap_after["preferences"]

    checks = []
    failed = []
    if rec.transcript_chars_after < rec.transcript_chars_before:
        checks.append("字符数下降")
    else:
        failed.append("压缩后字符未减少")
    if rec.layers:
        checks.append(f"layers={rec.layers}")
    else:
        failed.append("未触发任何压缩层")
    if rec.persona_unchanged and rec.memories_unchanged and rec.preferences_unchanged:
        checks.append("三文件画像未变")
    else:
        failed.append("压缩意外修改了 persona/memories/preferences JSON")

    rec.passed = len(failed) == 0
    rec.pass_reason = "；".join(checks) if rec.passed else "；".join(failed)
    return rec


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = SESSION_PREFIX
    session_id = f"{run_id}_{uuid.uuid4().hex[:8]}"
    store = get_session_store()
    store.db.ensure_session(session_id, title=f"画像压缩测试 {run_id}")
    store.get(session_id)

    orch = Orchestrator()

    from app.llm.client import probe_local_llm

    probe = probe_local_llm(force=True)
    meta = {
        "run_id": run_id,
        "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "local_endpoint": config.VLLM_API_BASE,
        "local_model": config.VLLM_MODEL_NAME,
        "local_ok": probe.get("ok"),
        "local_error": probe.get("error"),
        "agent_enable_auto_memory": config.AGENT_ENABLE_AUTO_MEMORY,
        "soft_context_chars": config.AGENT_SOFT_CONTEXT_CHARS,
    }
    if not probe.get("ok"):
        (RESULTS_DIR / f"{run_id}_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("本地模型不可用:", probe.get("error"))
        return 1

    cases = _load_cases()
    if not cases:
        print("未找到 test_cases.json")
        return 1

    turn_records: List[TurnRecord] = []
    total_wall = 0
    total_tokens = 0

    print(f"Session: {session_id}")
    print(f"Local model: {config.VLLM_MODEL_NAME} @ {config.VLLM_API_BASE}")
    print("-" * 60)

    compact_records: List[CompactRecord] = []

    for case_id, cat, query, expect in cases:
        if cat == "compact_mid":
            print(f"[{case_id}] 注入超长 transcript + force compact ...")
            sess = store.get(session_id)
            _inject_bulk_transcript(sess, n_turns=40, tool_chars=1500)
            store.save(sess)
            compact_rec = _run_compact_test(session_id, case_id)
            compact_records.append(compact_rec)
            status = "PASS" if compact_rec.passed else "FAIL"
            print(
                f"  {status} | {compact_rec.wall_ms}ms | "
                f"chars {compact_rec.transcript_chars_before}->{compact_rec.transcript_chars_after} | "
                f"layers={compact_rec.layers} | {compact_rec.pass_reason}"
            )
            continue
        print(f"[{case_id}] {query} ...")
        rec = _run_turn(orch, session_id, case_id, cat, query, expect)
        turn_records.append(rec)
        total_wall += rec.wall_ms
        total_tokens += rec.total_tokens
        status = "PASS" if rec.passed else "FAIL"
        print(
            f"  {status} | {rec.wall_ms}ms | tokens={rec.total_tokens} "
            f"| P={rec.persona_updated} M={rec.memories_updated} F={rec.preferences_updated} "
            f"| {rec.pass_reason}"
        )
        if rec.error:
            print(f"  ERROR: {rec.error}")

    has_mid_compact = any(c[1] == "compact_mid" for c in cases)
    if not has_mid_compact:
        print("-" * 60)
        print("[C-01] 注入超长 transcript + force compact ...")
        sess = store.get(session_id)
        _inject_bulk_transcript(sess)
        store.save(sess)
        compact_rec = _run_compact_test(session_id, "C-01_force_compact")
        compact_records.append(compact_rec)
        status = "PASS" if compact_rec.passed else "FAIL"
        print(
            f"  {status} | {compact_rec.wall_ms}ms | "
            f"chars {compact_rec.transcript_chars_before}->{compact_rec.transcript_chars_after} | "
            f"layers={compact_rec.layers} | {compact_rec.pass_reason}"
        )
        print("-" * 60)
        print("[V-C01] 压缩后验证：打开空调 ...")
        vrec = _run_turn(orch, session_id, "V-C01", "verify", "打开空调", {"no_profile_update": True})
        turn_records.append(vrec)
        total_wall += vrec.wall_ms
        total_tokens += vrec.total_tokens
        print(f"  {'PASS' if vrec.passed else 'FAIL'} | {vrec.wall_ms}ms | tokens={vrec.total_tokens}")

    sess = store.get(session_id)
    session_path = sess.root
    snap_final = _snapshot_profile(sess)

    summary = {
        "meta": meta,
        "session_id": session_id,
        "session_path": str(session_path),
        "turns": [asdict(r) for r in turn_records],
        "compact": [asdict(c) for c in compact_records],
        "by_category": _category_stats(turn_records),
        "totals": {
            "turn_count": len(turn_records),
            "total_wall_ms": total_wall + sum(c.wall_ms for c in compact_records),
            "total_tokens": total_tokens,
            "turn_pass": sum(1 for r in turn_records if r.passed),
            "turn_fail": sum(1 for r in turn_records if not r.passed),
            "compact_pass": all(c.passed for c in compact_records),
        },
        "final_profile": snap_final,
        "finished_at": datetime.now().isoformat(),
    }

    out_json = RESULTS_DIR / f"{run_id}_results.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown 报告
    lines = [
        f"# 画像与压缩真实测试报告",
        f"",
        f"- **运行 ID**: `{run_id}`",
        f"- **会话 ID**: `{session_id}`",
        f"- **本地模型**: `{config.VLLM_MODEL_NAME}` @ `{config.VLLM_API_BASE}`",
        f"- **完成时间**: {summary['finished_at']}",
        f"",
        f"## 汇总",
        f"",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 对话轮次 | {len(turn_records)} |",
        f"| 通过 | {summary['totals']['turn_pass']} |",
        f"| 失败 | {summary['totals']['turn_fail']} |",
        f"| 总耗时 (ms) | {summary['totals']['total_wall_ms']} |",
        f"| 总 Token | {summary['totals']['total_tokens']} |",
        f"| 压缩测试 | {'PASS' if summary['totals']['compact_pass'] else 'FAIL'} |",
        f"",
        f"## 分类统计",
        f"",
        f"| 类别 | 通过 | 失败 | Token | 耗时ms |",
        f"|------|------|------|-------|--------|",
    ]
    for cat, st in (summary.get("by_category") or {}).items():
        lines.append(f"| {cat} | {st['pass']} | {st['fail']} | {st['tokens']} | {st['wall_ms']} |")
    lines.extend(
        [
            "",
            "## 每轮明细",
            "",
            "| ID | 输入 | 耗时ms | Token | P/M/F | 意图 | 结果 |",
            "|----|------|--------|-------|-------|------|------|",
        ]
    )
    for r in turn_records:
        pmf = f"{r.persona_updated}/{r.memories_updated}/{r.preferences_updated}"
        lines.append(
            f"| {r.case_id} | {r.query[:24]} | {r.wall_ms} | {r.total_tokens} | {pmf} | {r.intent} | "
            f"{'✓' if r.passed else '✗'} {r.pass_reason[:40]} |"
        )
    for cr in compact_records:
        lines.extend(
            [
                "",
                f"## 压缩测试 {cr.case_id}",
                "",
                f"- 消息数: {cr.transcript_msgs_before} → {cr.transcript_msgs_after}",
                f"- 字符数: {cr.transcript_chars_before} → {cr.transcript_chars_after}",
                f"- 压缩层: `{cr.layers}`",
                f"- 摘要预览: {cr.summary[:200] if cr.summary else '(无)'}",
                f"- 三文件未变: persona={cr.persona_unchanged} memories={cr.memories_unchanged} prefs={cr.preferences_unchanged}",
            ]
        )
    lines.extend(
        [
            "",
            "## 最终画像",
            "",
            "### persona.json",
            "```json",
            json.dumps(snap_final["persona"], ensure_ascii=False, indent=2),
            "```",
            "",
            "### memories.json (items)",
            "```json",
            json.dumps(snap_final["memories"].get("items") or [], ensure_ascii=False, indent=2),
            "```",
            "",
            "### preferences.json",
            "```json",
            json.dumps(snap_final["preferences"], ensure_ascii=False, indent=2),
            "```",
            "",
            f"完整 JSON: `{out_json}`",
            f"会话目录: `{session_path}`",
        ]
    )
    report_md = TEST_DIR / "REPORT.md"
    report_md.write_text("\n".join(lines), encoding="utf-8")

    print("-" * 60)
    print(f"报告: {report_md}")
    print(f"JSON: {out_json}")
    return 0 if summary["totals"]["turn_fail"] == 0 and summary["totals"]["compact_pass"] else 2


def _category_stats(records: List[TurnRecord]) -> Dict[str, Any]:
    stats: Dict[str, Dict[str, int]] = {}
    for r in records:
        s = stats.setdefault(r.category, {"pass": 0, "fail": 0, "tokens": 0, "wall_ms": 0})
        if r.passed:
            s["pass"] += 1
        else:
            s["fail"] += 1
        s["tokens"] += r.total_tokens
        s["wall_ms"] += r.wall_ms
    return stats


if __name__ == "__main__":
    raise SystemExit(main())
