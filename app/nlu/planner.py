# -*- coding: utf-8 -*-
"""结构化 NLU：逐步规划（每步可并行一批无依赖工具；有依赖则拆步）。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient
from app.models import IntentType, RouteResult, ToolCall, ToolResult
from app.nlu.destination_guard import is_relative_or_category_destination
from app.nlu.seat_context import SEAT_CN, apply_active_seat_defaults, normalize_active_seat
from app.tools.registry import ToolRegistry, get_registry


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


INTENT_SYSTEM = """你是 Tesla 车载语音助手的**逐步**意图与工具规划器。
不要用关键词死板匹配；结合历史摘要与「已执行工具观察」决策。

## 核心原则（必须遵守）
1. 你每次只规划**当前这一步**要执行的工具，不要把整句里所有事一次列完。
2. **无依赖**的多个操作可以在同一步并行（tool_calls 里放多个）→ intent=multi_tool。
3. **有依赖**必须拆步：先做前置工具，设 done=false；看观察结果后再规划下一步。
4. 用户整句已满足、或需要用户从候选里选点/确认后才能继续 → done=true，且通常 tool_calls=[]。
5. 禁止取消「一句话多能力」；禁止用一次性堆工具代替串行推理。

## 意图
1) search —— 读本车实时状态（音量/空调/定位等），tool_calls=[]
2) tool —— 本步只执行**一个**工具
3) multi_tool —— 本步并行执行**多个无依赖**工具（最多3个）
4) knowledge —— 手册知识问答，tool_calls=[]
5) chat —— 闲聊/影讯推荐等非车控，tool_calls=[]
6) done —— （仅在观察后续步）请求已完成，无需再调工具；intent 也可用 chat 且 done=true、tool_calls=[]

## 地点规则（系统性，不是特例）
- 「附近/最近/找个 + 类别」且用户只是打听 → 只调 maps.search_nearby，done=true（等人选；不要同轮 navigate）。
- 「导航到最近的X / 带我去附近Y / 最近的X怎么走」→ 第一步只 search_nearby，**done=false**；
  看到观察里的周边 POI 后，第二步用**距离最近或列表第 1 个的具体店名**调用 navigation.navigate_to，done=true。
  禁止把「最近的X」原样塞进 navigate_to。
- navigation.navigate_to 的 destination **必须是具体店名或地址**，禁止相对短语。
- 打开地图 App 与搜周边无依赖 → 可同步 multi_tool：search_nearby + apps.launch。
- 「搜商场并导航 + 打开高德 + 问电影」→ 第一步地点发现（+可并行开 App，done=false 若还要导航）；电影留到工具结束后。

## 其它易错点
- 状态查询 → search；控车 → tool；手册用法 → knowledge
- 「打开空调并放周杰伦」无依赖 → multi_tool，done=true
- 周边生活服务禁止 chat 空口报店名

## 工具目录
{catalog}

## 输出（只返回 JSON）
{{
  "intent": "search|tool|multi_tool|knowledge|chat",
  "confidence": 0.0到1.0,
  "reason": "简短原因",
  "done": true或false,
  "tool_calls": [
    {{"name": "maps.search_nearby", "arguments": {{"keywords": "商场", "radius": 5000}}, "reason": "..."}}
  ]
}}
说明：done=false 表示执行完本步 tool_calls 后还要再规划；search/knowledge/chat 时 tool_calls 必须为 [] 且通常 done=true。
"""


def _format_observations(prior_results: List[ToolResult], prior_calls: Optional[List[ToolCall]] = None) -> str:
    if not prior_results:
        return "无"
    lines = []
    for i, r in enumerate(prior_results):
        name = r.tool or (prior_calls[i].name if prior_calls and i < len(prior_calls) else "?")
        bit = f"{i+1}. {name} → {'OK' if r.success else 'FAIL'}: {r.message}"
        if isinstance(r.data, dict):
            if r.data.get("need_clarify"):
                cands = r.data.get("candidates") or []
                names = [str(c.get("name") or "") for c in cands[:4] if isinstance(c, dict)]
                bit += f" | 待选候选: {names}"
            pois = r.data.get("pois") or r.data.get("recommend_pois") or []
            if pois:
                bits = []
                for p in pois[:5]:
                    if not isinstance(p, dict) or not p.get("name"):
                        continue
                    dist = p.get("distance")
                    label = str(p.get("name"))
                    if dist not in (None, ""):
                        label += f"({dist}m)"
                    bits.append(label)
                if bits:
                    bit += f" | 周边POI(已读入过程依据，按距离优先选最近): {bits}"
            dest = (r.data.get("destination") if isinstance(r.data.get("destination"), str) else None) or (
                (r.data.get("destination") or {}).get("name") if isinstance(r.data.get("destination"), dict) else None
            )
            if dest:
                bit += f" | 导航目的地: {dest}"
        lines.append(bit)
    return "\n".join(lines)


def sanitize_tool_calls(calls: List[ToolCall]) -> List[ToolCall]:
    """硬门禁：相对/类别 destination 的 navigate 一律丢掉（逼回 search 路径）。"""
    out: List[ToolCall] = []
    for c in calls:
        if c.name in {"navigation.navigate_to", "navigation.start"}:
            dest = str((c.arguments or {}).get("destination") or "")
            if is_relative_or_category_destination(dest):
                continue
        out.append(c)
    return out


_CATEGORY_FROM_TEXT = [
    (r"商场|购物中心|商场", "商场"),
    (r"充电站|超充|充电桩", "充电站"),
    (r"加油站", "加油站"),
    (r"停车场|车位", "停车场"),
    (r"咖啡", "咖啡"),
    (r"美食|餐厅|饭店|吃饭", "美食"),
    (r"厕所|卫生间", "公共厕所"),
    (r"超市|便利店", "超市"),
]


def recover_nearby_from_relative_nav(query: str, stripped: List[ToolCall], original: List[ToolCall]) -> List[ToolCall]:
    """若相对导航被剥光且无其它工具，自动改为 search_nearby。"""
    if stripped:
        return stripped
    had_relative_nav = False
    for c in original:
        if c.name in {"navigation.navigate_to", "navigation.start"}:
            dest = str((c.arguments or {}).get("destination") or "")
            if is_relative_or_category_destination(dest):
                had_relative_nav = True
                break
    if not had_relative_nav:
        return stripped
    text = (query or "") + " " + " ".join(
        str((c.arguments or {}).get("destination") or "") for c in original
    )
    keywords = "生活服务"
    for pat, kw in _CATEGORY_FROM_TEXT:
        if re.search(pat, text):
            keywords = kw
            break
    return [
        ToolCall(
            name="maps.search_nearby",
            arguments={"keywords": keywords, "radius": 5000},
            reason="相对导航降级为周边搜索",
        )
    ]


class StructuredNLU:
    def __init__(self, llm: LLMClient, registry: ToolRegistry | None = None):
        self.llm = llm
        self.registry = registry or get_registry()

    def plan(
        self,
        query: str,
        vehicle_state: dict,
        memory_hint: str = "",
        active_seat: str = "front_left",
        *,
        prior_results: Optional[List[ToolResult]] = None,
        prior_calls: Optional[List[ToolCall]] = None,
        step_index: int = 1,
    ) -> RouteResult:
        catalog = self.registry.prompt_catalog()
        seat = normalize_active_seat(active_seat)
        seat_cn = SEAT_CN.get(seat, seat)
        seats = vehicle_state.get("seats", {})
        climate = vehicle_state.get("climate", {}) or {}
        cabin = vehicle_state.get("cabin", {}) or {}
        slim = {
            "dynamics": vehicle_state.get("dynamics"),
            "climate": {
                "power": climate.get("power"),
                "mode": climate.get("mode"),
                "recirculation": climate.get("recirculation"),
                "zones": climate.get("zones") or {},
                "active_zone": (climate.get("zones") or {}).get(seat),
            },
            "media": vehicle_state.get("media"),
            "seats": {
                "heat": seats.get("heat") or {},
                "ventilation": seats.get("ventilation") or {},
                "massage": seats.get("massage") or {},
                "heat_active": (seats.get("heat") or {}).get(seat),
                "vent_active": (seats.get("ventilation") or {}).get(seat),
                "massage_active": (seats.get("massage") or {}).get(seat),
                "steering_wheel_heat": seats.get("steering_wheel_heat"),
            },
            "cabin": {
                "windows": cabin.get("windows") or {},
                "doors": cabin.get("doors") or {},
                "windows_active": (cabin.get("windows") or {}).get(
                    seat if seat != "rear_middle" else "rear_left"
                ),
                "doors_active": (cabin.get("doors") or {}).get(
                    seat if seat != "rear_middle" else "rear_left"
                ),
            },
            "navigation": vehicle_state.get("navigation"),
            "apps": vehicle_state.get("apps"),
            "active_seat": seat,
            "active_seat_cn": seat_cn,
        }
        system = INTENT_SYSTEM.format(catalog=catalog)
        obs = _format_observations(prior_results or [], prior_calls)
        user = (
            f"当前规划步序: 第 {step_index} 步\n"
            f"当前说话人座位: {seat_cn} ({seat})\n"
            f"说明: 未点名座位时 zones/positions 用 [{seat}]；天窗用 sunroof。\n\n"
            f"当前车况摘要:\n{json.dumps(slim, ensure_ascii=False)}\n\n"
            f"历史摘要:\n{memory_hint or '无'}\n\n"
            f"已执行工具观察:\n{obs}\n\n"
            f"用户原话: {query}\n"
            f"请只规划下一步；有依赖就拆步；无依赖可并行；相对地点禁止 navigate。"
        )
        try:
            raw = self.llm.chat(system, user, temperature=0.0)
            data = _extract_json(raw)
        except Exception as e:
            return RouteResult(intent=IntentType.CHAT, confidence=0.2, reason=f"NLU失败:{e}", done=True)

        intent_str = str(data.get("intent", "chat")).lower().strip()
        intent_map = {
            "knowledge": IntentType.KNOWLEDGE,
            "tool": IntentType.TOOL,
            "multi_tool": IntentType.MULTI_TOOL,
            "search": IntentType.SEARCH,
            "chat": IntentType.CHAT,
            "done": IntentType.CHAT,
        }
        intent = intent_map.get(intent_str, IntentType.CHAT)
        done = data.get("done")
        if done is None:
            # 无工具时默认结束；有工具时若未声明，保守为还有后续可能→False 仅当显式多步场景难判，默认 True
            done = True
        else:
            done = bool(done)

        calls: List[ToolCall] = []
        if intent in {IntentType.TOOL, IntentType.MULTI_TOOL}:
            for item in data.get("tool_calls") or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if not name or not self.registry.get(name):
                    continue
                calls.append(
                    ToolCall(
                        name=name,
                        arguments=item.get("arguments") or {},
                        reason=item.get("reason") or "",
                    )
                )
                if len(calls) >= 3:
                    break
            orig_calls = list(calls)
            calls = sanitize_tool_calls(apply_active_seat_defaults(calls, seat))
            calls = recover_nearby_from_relative_nav(query, calls, orig_calls)
            recovered_from_relative = bool(calls) and any(
                c.name.startswith("navigation.")
                and is_relative_or_category_destination(str((c.arguments or {}).get("destination") or ""))
                for c in orig_calls
            )
            if not calls:
                intent = IntentType.CHAT
                done = True
            elif len(calls) > 1:
                intent = IntentType.MULTI_TOOL
                if recovered_from_relative and any(c.name == "maps.search_nearby" for c in calls):
                    # 用户要导航到最近的X：先搜，再读结果后导航
                    done = False
            else:
                intent = IntentType.TOOL
                if recovered_from_relative and calls[0].name == "maps.search_nearby":
                    done = False
                elif calls[0].name == "maps.search_nearby" and any(
                    c.name.startswith("navigation.") for c in orig_calls
                ):
                    done = False
        else:
            calls = []
            done = True

        return RouteResult(
            intent=intent,
            confidence=float(data.get("confidence", 0.7) or 0.7),
            reason=str(data.get("reason", "llm-semantic")),
            tool_calls=calls,
            done=done,
        )
