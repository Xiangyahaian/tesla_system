#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 vLLM vs 云端百炼：能力/延迟/压力对照评测，输出 HTML 报告。

指标以客观可复现为主：
- 可用性、延迟（p50/p95）、吞吐（tok/s）
- 车载 NLU JSON 任务准确率（规则打分）
- 指令遵循（格式/字段）
- 并发压力（成功率、延迟分布）

用法（在项目根、tesla conda 环境）:
  python scripts/llm_capability_bench.py
"""
from __future__ import annotations

import html
import json
import math
import re
import statistics
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from app import config

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "reports"
OUT_JSON = OUT_DIR / "llm_capability_bench.json"
OUT_HTML = OUT_DIR / "llm_capability_report.html"

# —— 车载域客观用例（规则评分，不靠主观打分）——
NLU_CASES: List[Dict[str, Any]] = [
    {
        "id": "nav_landmark",
        "system": (
            "你是车载意图规划器。只返回 JSON："
            '{"intent":"tool","tool":"navigation.navigate_to","destination":"..."} '
            "具体地标直接导航，不要 search_nearby。"
        ),
        "user": "帮我导航到故宫博物馆",
        "expect": {"intent": "tool", "tool": "navigation.navigate_to", "dest_contains": ["故宫"]},
    },
    {
        "id": "nearby_food",
        "system": (
            "你是车载意图规划器。只返回 JSON："
            '{"intent":"tool","tool":"maps.search_nearby","keywords":"..."} '
            "附近美食用 search_nearby。"
        ),
        "user": "附近有什么好吃的",
        "expect": {"intent": "tool", "tool": "maps.search_nearby", "kw_any": ["美食", "餐厅", "饭店", "好吃"]},
    },
    {
        "id": "open_app",
        "system": (
            "你是车载意图规划器。只返回 JSON："
            '{"intent":"tool","tool":"apps.launch","app_name":"...","enable":true}'
        ),
        "user": "打开飞书",
        "expect": {"intent": "tool", "tool": "apps.launch", "app_any": ["飞书", "lark", "Lark"]},
    },
    {
        "id": "climate_on",
        "system": (
            "你是车载意图规划器。只返回 JSON："
            '{"intent":"tool","tool":"climate.set_power","enable":true}'
        ),
        "user": "打开空调",
        "expect": {"intent": "tool", "tool": "climate.set_power", "enable": True},
    },
    {
        "id": "chat_soft",
        "system": (
            "你是车载意图规划器。闲聊返回 JSON："
            '{"intent":"chat","tool":null} ；控车才用 tool。'
        ),
        "user": "今天心情不太好",
        "expect": {"intent": "chat"},
    },
    {
        "id": "status_where",
        "system": (
            "你是车载意图规划器。查状态返回 JSON："
            '{"intent":"search","tool":null}'
        ),
        "user": "我现在在哪里",
        "expect": {"intent": "search"},
    },
    {
        "id": "multi_tool",
        "system": (
            "你是车载意图规划器。无依赖多工具返回 JSON："
            '{"intent":"multi_tool","tools":["climate.set_power","media.play_music"]}'
        ),
        "user": "打开空调并放周杰伦的晴天",
        "expect": {
            "intent": "multi_tool",
            "tools_all": ["climate.set_power", "media.play_music"],
        },
    },
    {
        "id": "relative_nav_block",
        "system": (
            "你是车载意图规划器。「最近的充电站」不能直接 navigate_to，"
            "应返回 JSON："
            '{"intent":"tool","tool":"maps.search_nearby","keywords":"充电站"}'
        ),
        "user": "导航到最近的充电站",
        "expect": {"intent": "tool", "tool": "maps.search_nearby", "kw_any": ["充电"]},
    },
]

FOLLOW_CASES: List[Dict[str, Any]] = [
    {
        "id": "json_only",
        "system": "只输出一个 JSON 对象，不要 markdown，不要解释。",
        "user": '返回 {"ok": true, "n": 3}',
        "check": "pure_json",
    },
    {
        "id": "listen_tag",
        "system": "用中文回复，必须以【听】开头，不超过 40 字。",
        "user": "空调已打开，温度 22 度。请口语告诉用户。",
        "check": "listen_prefix",
    },
    {
        "id": "no_safety_lecture",
        "system": "你是车载助手。禁止提安全带、专注驾驶。1 句口语确认导航已启动。",
        "user": "导航去五道口已规划成功，ETA 12 分钟。",
        "check": "no_seatbelt",
    },
]


def _client(mode: str) -> Tuple[OpenAI, str, str]:
    if mode == "local":
        return (
            OpenAI(
                api_key=config.VLLM_API_KEY or "EMPTY",
                base_url=config.VLLM_API_BASE,
                timeout=60.0,
            ),
            config.VLLM_MODEL_NAME,
            config.VLLM_API_BASE,
        )
    return (
        OpenAI(
            api_key=config.BAILIAN_API_KEY or "EMPTY",
            base_url=config.BAILIAN_API_BASE,
            timeout=60.0,
        ),
        config.BAILIAN_MODEL_NAME,
        config.BAILIAN_API_BASE,
    )


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


def _chat(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 256,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    err = ""
    content = ""
    usage: Dict[str, Any] = {}
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        content = (resp.choices[0].message.content or "") if resp.choices else ""
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
    except Exception as e:
        err = str(e)
    ms = (time.perf_counter() - t0) * 1000
    return {"ok": not err, "error": err, "content": content, "latency_ms": ms, "usage": usage}


def _percentile(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    k = (len(ys) - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(ys[int(k)])
    return float(ys[f] * (c - k) + ys[c] * (k - f))


def score_nlu(case: Dict[str, Any], raw: str) -> Dict[str, Any]:
    data = _extract_json(raw)
    exp = case["expect"]
    checks: List[Tuple[str, bool]] = []
    intent = str(data.get("intent") or "").lower()
    tool = str(data.get("tool") or "")
    tools = data.get("tools") or []
    if not isinstance(tools, list):
        tools = []
    tools_s = [str(x) for x in tools]

    if "intent" in exp:
        checks.append(("intent", intent == str(exp["intent"]).lower()))
    if "tool" in exp:
        ok = tool == exp["tool"] or exp["tool"] in tools_s
        checks.append(("tool", ok))
    if "enable" in exp:
        checks.append(("enable", bool(data.get("enable")) is bool(exp["enable"])))
    if "dest_contains" in exp:
        dest = str(data.get("destination") or "")
        checks.append(("destination", any(x in dest for x in exp["dest_contains"])))
    if "kw_any" in exp:
        kw = str(data.get("keywords") or "")
        checks.append(("keywords", any(x in kw for x in exp["kw_any"])))
    if "app_any" in exp:
        app = str(data.get("app_name") or "")
        checks.append(("app_name", any(x.lower() in app.lower() for x in exp["app_any"])))
    if "tools_all" in exp:
        need = set(exp["tools_all"])
        have = set(tools_s)
        if tool:
            have.add(tool)
        checks.append(("tools_all", need.issubset(have)))

    passed = all(ok for _, ok in checks) if checks else False
    return {
        "pass": passed,
        "score": (sum(1 for _, ok in checks if ok) / max(1, len(checks))) if checks else 0.0,
        "checks": {k: v for k, v in checks},
        "parsed": data,
    }


def score_follow(case: Dict[str, Any], raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    kind = case["check"]
    ok = False
    detail = ""
    if kind == "pure_json":
        data = _extract_json(text)
        ok = bool(data) and text.lstrip().startswith("{") and "```" not in text
        detail = "纯 JSON" if ok else "含杂质或非 JSON"
    elif kind == "listen_prefix":
        ok = text.startswith("【听】") and len(text) <= 60
        detail = "【听】前缀且够短" if ok else "未按标记/过长"
    elif kind == "no_seatbelt":
        bad = re.search(r"安全带|专注驾驶|注意安全|先停车", text)
        ok = (not bad) and len(text) > 0
        detail = "无说教" if ok else "含安全说教"
    return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": detail}


def run_latency(client: OpenAI, model: str, rounds: int = 8) -> Dict[str, Any]:
    # warmup
    _chat(client, model, "简短回复。", "ping", max_tokens=8)
    rows = []
    for i in range(rounds):
        r = _chat(
            client,
            model,
            "你是车载助手，用一句话确认。",
            f"把空调打开到 22 度。（第{i+1}次）",
            max_tokens=64,
        )
        rows.append(r)
    ok_rows = [x for x in rows if x["ok"]]
    lats = [x["latency_ms"] for x in ok_rows]
    toks = []
    for x in ok_rows:
        ct = float((x.get("usage") or {}).get("completion_tokens") or 0)
        if ct > 0 and x["latency_ms"] > 0:
            toks.append(ct / (x["latency_ms"] / 1000.0))
    return {
        "rounds": rounds,
        "success": len(ok_rows),
        "errors": [x["error"] for x in rows if not x["ok"]],
        "latency_ms": {
            "mean": statistics.mean(lats) if lats else None,
            "p50": _percentile(lats, 50),
            "p95": _percentile(lats, 95),
            "min": min(lats) if lats else None,
            "max": max(lats) if lats else None,
        },
        "tok_per_s": {
            "mean": statistics.mean(toks) if toks else None,
            "p50": _percentile(toks, 50) if toks else None,
        },
        "samples": [
            {
                "ok": x["ok"],
                "latency_ms": round(x["latency_ms"], 1),
                "completion_tokens": (x.get("usage") or {}).get("completion_tokens"),
            }
            for x in rows
        ],
    }


def run_nlu(client: OpenAI, model: str) -> Dict[str, Any]:
    items = []
    for case in NLU_CASES:
        r = _chat(client, model, case["system"], case["user"], max_tokens=200)
        sc = score_nlu(case, r.get("content") or "") if r["ok"] else {
            "pass": False,
            "score": 0.0,
            "checks": {},
            "parsed": {},
        }
        items.append(
            {
                "id": case["id"],
                "user": case["user"],
                "ok_call": r["ok"],
                "error": r.get("error") or "",
                "latency_ms": round(r["latency_ms"], 1),
                "raw": (r.get("content") or "")[:400],
                **sc,
            }
        )
    scores = [x["score"] for x in items]
    return {
        "accuracy": sum(1 for x in items if x["pass"]) / max(1, len(items)),
        "avg_score": statistics.mean(scores) if scores else 0.0,
        "cases": items,
    }


def run_follow(client: OpenAI, model: str) -> Dict[str, Any]:
    items = []
    for case in FOLLOW_CASES:
        r = _chat(client, model, case["system"], case["user"], max_tokens=120)
        sc = score_follow(case, r.get("content") or "") if r["ok"] else {
            "pass": False,
            "score": 0.0,
            "detail": r.get("error") or "调用失败",
        }
        items.append(
            {
                "id": case["id"],
                "ok_call": r["ok"],
                "latency_ms": round(r["latency_ms"], 1),
                "raw": (r.get("content") or "")[:300],
                **sc,
            }
        )
    return {
        "accuracy": sum(1 for x in items if x["pass"]) / max(1, len(items)),
        "cases": items,
    }


def run_stress(
    mode: str,
    *,
    workers: int = 6,
    total: int = 24,
) -> Dict[str, Any]:
    """并发压力：每线程独立 client。"""

    def one(i: int) -> Dict[str, Any]:
        client, model, _ = _client(mode)
        return _chat(
            client,
            model,
            "只回一个短词：好的",
            f"确认收到 #{i}",
            max_tokens=16,
        )

    t0 = time.perf_counter()
    rows: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, i) for i in range(total)]
        for fut in as_completed(futs):
            try:
                rows.append(fut.result())
            except Exception as e:
                rows.append({"ok": False, "error": str(e), "latency_ms": 0, "content": "", "usage": {}})
    wall = (time.perf_counter() - t0) * 1000
    ok_rows = [x for x in rows if x.get("ok")]
    lats = [x["latency_ms"] for x in ok_rows]
    return {
        "workers": workers,
        "total": total,
        "success": len(ok_rows),
        "success_rate": len(ok_rows) / max(1, total),
        "wall_ms": wall,
        "qps": total / max(0.001, wall / 1000.0),
        "latency_ms": {
            "p50": _percentile(lats, 50),
            "p95": _percentile(lats, 95),
            "mean": statistics.mean(lats) if lats else None,
            "max": max(lats) if lats else None,
        },
        "errors": list({x.get("error") or "" for x in rows if not x.get("ok")})[:5],
    }


def probe(mode: str) -> Dict[str, Any]:
    client, model, base = _client(mode)
    t0 = time.perf_counter()
    try:
        models = client.models.list()
        ids = [m.id for m in (models.data or [])]
        ok = True
        err = ""
    except Exception as e:
        ids = []
        ok = False
        err = str(e)
    return {
        "mode": mode,
        "ok": ok,
        "error": err,
        "endpoint": base.split("/compatible")[0] if "aliyun" in base else base,
        "endpoint_host": re.sub(r"https?://", "", base).split("/")[0],
        "model": model,
        "served": ids,
        "probe_ms": (time.perf_counter() - t0) * 1000,
        "has_key": bool(config.BAILIAN_API_KEY) if mode == "remote" else True,
    }


def evaluate_mode(mode: str) -> Dict[str, Any]:
    info = probe(mode)
    out: Dict[str, Any] = {"info": info}
    if not info["ok"] and mode == "remote" and not info["has_key"]:
        out["skipped"] = "未配置云端密钥"
        return out
    if not info["ok"]:
        out["skipped"] = info.get("error") or "不可用"
        return out
    client, model, _ = _client(mode)
    print(f"[{mode}] latency…")
    out["latency"] = run_latency(client, model)
    print(f"[{mode}] nlu…")
    out["nlu"] = run_nlu(client, model)
    print(f"[{mode}] follow…")
    out["follow"] = run_follow(client, model)
    print(f"[{mode}] stress…")
    out["stress"] = run_stress(mode, workers=6, total=24)
    return out


def _fmt(v: Any, digits: int = 1) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.0f}%"


def build_html(report: Dict[str, Any]) -> str:
    local = report["results"].get("local") or {}
    remote = report["results"].get("remote") or {}
    li = (local.get("info") or {})
    ri = (remote.get("info") or {})

    def card_metric(label: str, a: str, b: str, note: str = "") -> str:
        return f"""
        <div class="metric">
          <div class="metric-label">{html.escape(label)}</div>
          <div class="metric-vals">
            <div><span class="tag local">本地</span><strong>{html.escape(a)}</strong></div>
            <div><span class="tag remote">云端</span><strong>{html.escape(b)}</strong></div>
          </div>
          {f'<div class="metric-note">{html.escape(note)}</div>' if note else ''}
        </div>"""

    ll = (local.get("latency") or {}).get("latency_ms") or {}
    rl = (remote.get("latency") or {}).get("latency_ms") or {}
    lt = (local.get("latency") or {}).get("tok_per_s") or {}
    rt = (remote.get("latency") or {}).get("tok_per_s") or {}
    ls = local.get("stress") or {}
    rs = remote.get("stress") or {}
    ln = local.get("nlu") or {}
    rn = remote.get("nlu") or {}
    lf = local.get("follow") or {}
    rf = remote.get("follow") or {}

    # case tables
    def cases_table(title: str, local_cases: List[Dict], remote_cases: List[Dict], kind: str) -> str:
        by_id_r = {c["id"]: c for c in remote_cases}
        rows = []
        for c in local_cases:
            r = by_id_r.get(c["id"], {})
            lp = "✓" if c.get("pass") else "✗"
            rp = "✓" if r.get("pass") else ("—" if not r else "✗")
            rows.append(
                f"<tr><td>{html.escape(c.get('id',''))}</td>"
                f"<td class='q'>{html.escape(c.get('user') or c.get('id',''))}</td>"
                f"<td class='{'ok' if c.get('pass') else 'bad'}'>{lp}</td>"
                f"<td class='{'ok' if r.get('pass') else ('mute' if not r else 'bad')}'>{rp}</td>"
                f"<td>{_fmt(c.get('latency_ms'))}</td>"
                f"<td>{_fmt(r.get('latency_ms'))}</td></tr>"
            )
        return f"""
        <section class="panel">
          <h2>{html.escape(title)}</h2>
          <table>
            <thead><tr><th>用例</th><th>输入</th><th>本地</th><th>云端</th><th>本地 ms</th><th>云端 ms</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </section>"""

    nlu_table = cases_table(
        "车载 NLU 任务（规则打分，可对比）",
        (ln.get("cases") or []),
        (rn.get("cases") or []),
        "nlu",
    )
    follow_table = cases_table(
        "指令遵循（格式/禁说教，可对比）",
        [{**c, "user": c["id"]} for c in (lf.get("cases") or [])],
        [{**c, "user": c["id"]} for c in (rf.get("cases") or [])],
        "follow",
    )

    # bars for latency compare
    def bar_row(label: str, a: Optional[float], b: Optional[float], unit: str = "ms") -> str:
        vals = [x for x in [a, b] if x is not None and x > 0]
        mx = max(vals) if vals else 1
        wa = (a / mx * 100) if a else 0
        wb = (b / mx * 100) if b else 0
        return f"""
        <div class="bar-row">
          <div class="bar-label">{html.escape(label)}</div>
          <div class="bars">
            <div class="bar local" style="width:{wa:.1f}%"><span>{_fmt(a)}{unit}</span></div>
            <div class="bar remote" style="width:{wb:.1f}%"><span>{_fmt(b)}{unit}</span></div>
          </div>
        </div>"""

    verdict_bits = []
    if ln.get("accuracy") is not None and rn.get("accuracy") is not None:
        if ln["accuracy"] > rn["accuracy"] + 0.05:
            verdict_bits.append("车载 NLU 准确率：本地略优")
        elif rn["accuracy"] > ln["accuracy"] + 0.05:
            verdict_bits.append("车载 NLU 准确率：云端略优")
        else:
            verdict_bits.append("车载 NLU 准确率：两者接近")
    if ll.get("p50") and rl.get("p50"):
        if ll["p50"] < rl["p50"] * 0.85:
            verdict_bits.append("单请求延迟：本地更快")
        elif rl["p50"] < ll["p50"] * 0.85:
            verdict_bits.append("单请求延迟：云端更快")
        else:
            verdict_bits.append("单请求延迟：同一量级")
    if ls.get("success_rate") is not None and rs.get("success_rate") is not None:
        if ls["success_rate"] >= 0.95 and rs["success_rate"] >= 0.95:
            verdict_bits.append("并发压力：两者均稳定")
        elif ls["success_rate"] < rs["success_rate"] - 0.1:
            verdict_bits.append("并发压力：本地成功率偏低")
        elif rs["success_rate"] < ls["success_rate"] - 0.1:
            verdict_bits.append("并发压力：云端成功率偏低")

    css = """
    :root {
      --bg: #0f1419;
      --panel: #171d25;
      --line: rgba(255,255,255,.08);
      --text: #e8eef6;
      --mute: #8b98a8;
      --local: #3dd6c6;
      --remote: #6ea8fe;
      --ok: #3ecf8e;
      --bad: #ff6b7a;
      --warn: #f0b429;
      --radius: 14px;
      --font: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: var(--font); color: var(--text);
      background:
        radial-gradient(900px 480px at 12% -10%, rgba(61,214,198,.16), transparent 55%),
        radial-gradient(800px 420px at 90% 0%, rgba(110,168,254,.14), transparent 50%),
        var(--bg);
      min-height: 100vh;
    }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 40px 22px 72px; }
    header.hero {
      display: grid; gap: 10px; margin-bottom: 28px;
      padding: 28px 28px 24px; border: 1px solid var(--line);
      border-radius: 20px; background: linear-gradient(160deg, rgba(255,255,255,.04), transparent 60%), var(--panel);
    }
    header.hero h1 { margin: 0; font-size: 28px; letter-spacing: .02em; }
    header.hero p { margin: 0; color: var(--mute); line-height: 1.55; max-width: 72ch; }
    .meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }
    .chip {
      font-size: 12px; color: var(--mute); border: 1px solid var(--line);
      padding: 6px 10px; border-radius: 999px; background: rgba(0,0,0,.2);
    }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }
    @media (max-width: 800px) { .grid { grid-template-columns: 1fr; } }
    .panel {
      background: var(--panel); border: 1px solid var(--line);
      border-radius: var(--radius); padding: 18px 18px 14px; margin-bottom: 16px;
    }
    .panel h2 { margin: 0 0 12px; font-size: 16px; font-weight: 700; }
    .panel h3 { margin: 14px 0 8px; font-size: 13px; color: var(--mute); font-weight: 600; }
    .endpoint {
      font-size: 13px; color: var(--mute); display: grid; gap: 6px;
    }
    .endpoint strong { color: var(--text); font-size: 18px; }
    .tag {
      display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 7px;
      border-radius: 6px; margin-right: 6px; letter-spacing: .04em;
    }
    .tag.local { background: rgba(61,214,198,.15); color: var(--local); }
    .tag.remote { background: rgba(110,168,254,.15); color: var(--remote); }
    .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    @media (max-width: 900px) { .metrics { grid-template-columns: 1fr; } }
    .metric {
      border: 1px solid var(--line); border-radius: 12px; padding: 12px;
      background: rgba(255,255,255,.02);
    }
    .metric-label { font-size: 12px; color: var(--mute); margin-bottom: 8px; }
    .metric-vals { display: grid; gap: 6px; font-size: 14px; }
    .metric-vals strong { font-variant-numeric: tabular-nums; }
    .metric-note { margin-top: 8px; font-size: 11px; color: var(--mute); }
    .bar-row { display: grid; grid-template-columns: 110px 1fr; gap: 10px; align-items: center; margin: 8px 0; }
    .bar-label { font-size: 12px; color: var(--mute); }
    .bars { display: grid; gap: 4px; }
    .bar {
      height: 22px; border-radius: 6px; min-width: 8%;
      display: flex; align-items: center; padding: 0 8px;
      font-size: 11px; font-variant-numeric: tabular-nums; color: #041016;
    }
    .bar.local { background: linear-gradient(90deg, #2bbfaf, #6ff0e0); }
    .bar.remote { background: linear-gradient(90deg, #4d8df5, #9dc4ff); }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 8px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
    th { color: var(--mute); font-weight: 600; font-size: 12px; }
    td.q { color: var(--mute); max-width: 280px; }
    td.ok { color: var(--ok); font-weight: 700; }
    td.bad { color: var(--bad); font-weight: 700; }
    td.mute { color: var(--mute); }
    .verdict {
      display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px;
    }
    .verdict span {
      background: rgba(61,214,198,.1); border: 1px solid rgba(61,214,198,.25);
      color: #b7fff6; padding: 8px 12px; border-radius: 999px; font-size: 13px;
    }
    footer { margin-top: 28px; color: var(--mute); font-size: 12px; line-height: 1.5; }
    .legend { display: flex; gap: 14px; font-size: 12px; color: var(--mute); margin-bottom: 8px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 5px; }
    .dot.local { background: var(--local); }
    .dot.remote { background: var(--remote); }
    """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LLM 能力对照报告 · 本地 vLLM vs 云端百炼</title>
  <style>{css}</style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1>LLM 能力对照报告</h1>
      <p>对照对象：本地 <code>{html.escape(str(li.get('model') or 'qwen-4b-tesla'))}</code>
         vs 云端 <code>{html.escape(str(ri.get('model') or 'qwen3.5-flash'))}</code>。
         以车载 NLU / 指令遵循 / 延迟吞吐 / 并发压力等客观指标为主；主观智力不做玄学对比。</p>
      <div class="meta">
        <span class="chip">生成时间 {html.escape(report.get('generated_at',''))}</span>
        <span class="chip">评测脚本 scripts/llm_capability_bench.py</span>
        <span class="chip">压力：6 并发 × 24 请求</span>
      </div>
      <div class="verdict">
        {''.join(f'<span>{html.escape(v)}</span>' for v in verdict_bits) or '<span>详见下方分项</span>'}
      </div>
    </header>

    <div class="grid">
      <section class="panel">
        <h2><span class="tag local">本地</span> vLLM</h2>
        <div class="endpoint">
          <strong>{html.escape(str(li.get('model') or '—'))}</strong>
          <div>主机 {html.escape(str(li.get('endpoint_host') or '—'))}</div>
          <div>探测 {'可用' if li.get('ok') else '不可用'} · {_fmt(li.get('probe_ms'))} ms</div>
        </div>
      </section>
      <section class="panel">
        <h2><span class="tag remote">云端</span> 百炼 API</h2>
        <div class="endpoint">
          <strong>{html.escape(str(ri.get('model') or '—'))}</strong>
          <div>主机 {html.escape(str(ri.get('endpoint_host') or '—'))}</div>
          <div>探测 {'可用' if ri.get('ok') else '不可用'} · {_fmt(ri.get('probe_ms'))} ms</div>
        </div>
      </section>
    </div>

    <section class="panel">
      <h2>核心指标对照</h2>
      <div class="legend"><span><i class="dot local"></i>本地</span><span><i class="dot remote"></i>云端</span></div>
      <div class="metrics">
        {card_metric('NLU 准确率', _pct(ln.get('accuracy')), _pct(rn.get('accuracy')), '8 个车载意图用例，规则匹配')}
        {card_metric('指令遵循率', _pct(lf.get('accuracy')), _pct(rf.get('accuracy')), 'JSON/【听】/禁说教')}
        {card_metric('延迟 p50', _fmt(ll.get('p50'))+' ms', _fmt(rl.get('p50'))+' ms', '串行短回复 8 轮')}
        {card_metric('延迟 p95', _fmt(ll.get('p95'))+' ms', _fmt(rl.get('p95'))+' ms')}
        {card_metric('生成吞吐', _fmt(lt.get('mean'),1)+' tok/s', _fmt(rt.get('mean'),1)+' tok/s', 'completion tokens / 耗时')}
        {card_metric('压力成功率', _pct(ls.get('success_rate')), _pct(rs.get('success_rate')), '6 并发共 24 请求')}
        {card_metric('压力 QPS', _fmt(ls.get('qps'),2), _fmt(rs.get('qps'),2), '墙钟吞吐')}
        {card_metric('压力延迟 p95', _fmt((ls.get('latency_ms') or {}).get('p95'))+' ms', _fmt((rs.get('latency_ms') or {}).get('p95'))+' ms')}
        {card_metric('串行成功率', f"{(local.get('latency') or {}).get('success',0)}/8", f"{(remote.get('latency') or {}).get('success',0)}/8")}
      </div>
      <h3>延迟条形对照</h3>
      {bar_row('p50', ll.get('p50'), rl.get('p50'))}
      {bar_row('p95', ll.get('p95'), rl.get('p95'))}
      {bar_row('压力 p95', (ls.get('latency_ms') or {}).get('p95'), (rs.get('latency_ms') or {}).get('p95'))}
    </section>

    {nlu_table}
    {follow_table}

    <section class="panel">
      <h2>不对比 / 说明</h2>
      <p style="margin:0;color:var(--mute);font-size:13px;line-height:1.6">
        未做开放域常识竞赛、长文创作审美、工具真实执行成功率（那依赖网关/地图，不是纯模型）。
        云端模型更大更强时，开放域可能占优，但本报告聚焦<strong>座舱可复现任务</strong>与<strong>工程性能</strong>。
        压力测试反映当前链路（含网络到 192.168.x / 公网）的综合表现，不单是 GPU 算力。
      </p>
    </section>

    <footer>
      原始数据：{html.escape(str(OUT_JSON))} · 本页：{html.escape(str(OUT_HTML))}<br/>
      密钥与完整 endpoint 未写入报告正文。重新评测：<code>python scripts/llm_capability_bench.py</code>
    </footer>
  </div>
</body>
</html>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results: Dict[str, Any] = {}
    for mode in ("local", "remote"):
        print(f"==== evaluating {mode} ====")
        try:
            results[mode] = evaluate_mode(mode)
        except Exception:
            results[mode] = {
                "info": {"mode": mode, "ok": False, "error": traceback.format_exc()[-500:]},
                "skipped": "评测异常",
            }

    report = {
        "generated_at": generated_at,
        "results": results,
        "methodology": {
            "nlu_cases": len(NLU_CASES),
            "follow_cases": len(FOLLOW_CASES),
            "latency_rounds": 8,
            "stress": {"workers": 6, "total": 24},
            "scoring": "rule-based JSON/field match; no LLM-as-judge",
        },
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(build_html(report), encoding="utf-8")
    print(f"JSON -> {OUT_JSON}")
    print(f"HTML -> {OUT_HTML}")


if __name__ == "__main__":
    main()
