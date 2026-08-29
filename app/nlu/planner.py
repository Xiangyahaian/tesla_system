# -*- coding: utf-8 -*-
"""结构化 NLU：逐步规划（每步可并行一批无依赖工具；有依赖则拆步）。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient, classify_llm_error
from app.models import IntentType, ProfileUpdatePlan, RouteResult, ToolCall, ToolResult
from app.nlu.destination_guard import is_relative_or_category_destination, strip_compound_tail_from_destination
from app.nlu.react_guard import coerce_step_done
from app.nlu.fast_path import coerce_planned_intent
from app.nlu.seat_context import SEAT_CN, apply_active_seat_defaults, normalize_active_seat
from app.tools.registry import ToolRegistry, get_registry


def _infer_tool_domains(
    query: str,
    *,
    prior_calls: Optional[List[ToolCall]] = None,
) -> Optional[List[str]]:
    """根据原话/已调用工具收窄工具说明；看不出域就返回 None（全量）。"""
    found: List[str] = []

    def add(d: str) -> None:
        if d not in found:
            found.append(d)

    for c in prior_calls or []:
        name = (c.name or "").split(".")[0]
        if name:
            add(name)

    q = query or ""
    rules = [
        (r"(空调|温度|制冷|制热|风量|内循环|外循环|调温)", ["climate"]),
        (r"(座椅|加热|通风|按摩|方向盘热)", ["seat"]),
        (r"(音乐|歌|电台|音量|静音|播放|暂停|下一首|上一首|合唱)", ["media"]),
        (r"(导航|目的地|取消导航|结束导航|去.{0,12}|到.{0,12})", ["navigation", "maps"]),
        (r"(附近|周边|旁边|充电站|加油站|停车场|美食|餐厅|咖啡)", ["maps", "navigation"]),
        (r"(车窗|天窗|门锁|后备箱|前备箱|充电口|灯光|氛围灯|阅读灯|顶灯|屏幕亮度)", ["cabin"]),
        (r"(车速|巡航|ACC|自动驾驶|自动泊车|儿童锁|驾驶模式)", ["driving"]),
        (r"(打开|关掉|关闭).{0,8}(飞书|微信|地图|高德|美团|应用|App)", ["apps"]),
        (r"(Wi-?Fi|wifi|热点|蜂窝)", ["connectivity"]),
        (r"(消息|通知|未读|短信)", ["notifications"]),
        (
            r"(网上|百度一下|谷歌|google|搜一下|搜索一下|今日新闻|今天新闻|热点新闻|大新闻|油价|汇率|股价|比分|大事|电影|影片|片子|上映|影评)",
            ["web"],
        ),
    ]
    for pat, doms in rules:
        if re.search(pat, q, re.I):
            for d in doms:
                add(d)
    return found or None


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
6. 观察里工具已 OK、用户指令已落地（开关、设温度、调音量等无后续依赖）→ done=true, tool_calls=[]。禁止用同一 name+arguments 再调。done=false 只用于「本步结果决定下一步」，例如 maps.search_nearby 后再导航。

## 意图
1) search —— 读本车实时状态（音量/空调/定位/正在播什么歌等），tool_calls=[]
2) tool —— 本步只执行**一个**工具
3) multi_tool —— 本步并行执行**多个无依赖**工具（最多3个）
4) knowledge —— 车主手册：功能怎么用、故障/报警怎么办、图标什么意思、限制条件、充电与保养注意事项。tool_calls=[]
   例：「自动泊车怎么用」「无法充电怎么办」「电池图标变黄什么意思」「为什么停车也要插充电器」
5) chat —— 寒暄、讲笑话、陪聊吐槽、歌曲故事/明星八卦、想看电影等轻松闲谈。不是「不会控车就闲聊」。
   车辆不会用 / 出故障 / 手册内容 **禁止 chat**。
   **特例**：闲聊若需要网上实时信息（最近有什么电影、这部片子怎么样、刚才说的那部好看在哪），intent 仍用 **chat**，可同时带 tool_calls=[web.search]；没有工具时上层闲聊路径也会补搜。禁止空口编片单/评分/新闻。
6) done —— （仅在观察后续步）请求已完成，无需再调工具；若本步其实是手册问法，intent 必须用 knowledge 而不是 chat。

## 地点规则（系统性，不是特例）
- 「导航到故宫博物馆 / 去首都机场 / 带我去五道口」等**具体地标、店名、地址** → 直接 navigation.navigate_to，done=true。
  **禁止**对具体地点先调 maps.search_nearby。
- 「附近/最近/找个 + 类别」且用户只是打听 → 只调 maps.search_nearby，done=true（等人选；不要同轮 navigate）。
- 「导航到最近的X / 带我去附近Y / 最近的X怎么走」→ 第一步**只** search_nearby，**done=false**；
  看到观察里的周边 POI 后，第二步用**距离最近或列表第 1 个的具体店名**调用 navigation.navigate_to，done=true。
  禁止把「最近的X」原样塞进 navigate_to。
  **禁止**在导航/搜周边流程里顺手 apps.launch 打开高德/地图；车内导航不依赖打开地图 App。
- navigation.navigate_to 的 destination **必须是具体店名或地址**，禁止相对短语。
- **apps.launch 仅当用户明确说**「打开高德/打开地图/打开飞书」等时才调用。
  「导航到附近的酒吧」≠「打开高德」；不要自作主张开 App。
- 仅当用户同句明确「导航到附近酒店，并打开高德」→ 才可 multi_tool：search_nearby + apps.launch（地图）。
- 「搜商场并导航 + 明确打开高德 + 问电影」→ 第一步地点发现（+仅在用户点名开 App 时可并行），电影留到工具结束后。

## 其它易错点
- 状态查询 → search；控车指令 → tool；**手册问法 → knowledge，禁止 chat**
- 「你是谁 / 你叫什么 / 谢谢 / 陪我聊聊」→ chat，禁止 knowledge（那是助手身份，不是查车辆识别码）
- 「无法充电怎么办 / 充不了电 / 充电故障 / 图标变黄」→ knowledge（不是打开充电口，也不是闲聊）
- 「我在听什么歌」→ search（读媒体状态）；「这首歌有什么故事 / 谁唱的背景」→ **chat**（娱乐闲谈，禁止 knowledge）
- 「我最近想看电影 / 有什么好看的电影 / 这个电影好看在哪」→ **chat**，并调用 web.search（query 结合历史，例如上一轮推荐了某部，本轮「好看在哪里」要带上片名）。
- 历史里刚问过手册，本轮仍是手册问法 → 继续 knowledge，不要因为「聊过」改成 chat
- reason 里如果认为该查手册，intent 字段必须是 "knowledge"
- 「打开空调并放周杰伦」无依赖 → multi_tool，done=true
- **一句多能力（导航+空调+音乐等）** → intent=multi_tool，各工具参数只取各自子句：
  例：「导航到中关村软件园，副驾空调22度，播放周杰伦的晴天」
  → navigation.navigate_to destination=「中关村软件园」；climate 副驾 22°C；media.play_music artist=周杰伦 title=晴天
  **禁止**把歌曲名（如「晴天」）、温度、播放/空调指令整句塞进 destination。
- 「音量调小/调大」用 media.set_volume 的 delta 一次（如 -10/+10），done=true。禁止为了更安静而连续多次改绝对 volume。
- 周边生活服务禁止 chat 空口报店名
- **网页搜索 web.search（不要空口编网上事实）**
  下列情况必须调用 web.search，done=true：
  1) 用户明说要上网/搜索：如「搜一下」「网上搜」「百度一下」——即使搜的内容嵌在前后半句里 → intent=tool；
  2) 油价汇率股价比分、新闻热点、百科时事等明确检索 → intent=tool + web.search；
  3) **闲聊特例**：想看电影、这部片子怎么样、刚才说的那部好看在哪 → **intent=chat** 且 tool_calls=[web.search]，query 结合历史把片名/主题写全。
  **禁止**空口编片单、评分、新闻。
  **禁止**用 web.search 回答车主手册、车上怎么用、故障怎么办（那是 knowledge）。
  **禁止**用 web.search 找附近的店/充电站（那是 maps.search_nearby）。
  **禁止**用 web.search 替代 navigation.navigate_to。
  若观察里刚有导航候选待选，但用户明确改口要搜网/换题 → 不要再 navigate；本步改调 web.search（或 done 后由上层释放候选）。
- 结合历史摘要：用户刚问完「在听什么歌」又问「这首歌…」→ 指当前曲目，用 chat，不要去手册里搜

## 五座分区（climate / seat 工具的 zones/positions 只能用下列英文 key）
- front_left = 主驾 / 驾驶位 / 司机位
- front_right = 副驾 / 副驾驶（**不是** rear_right）
- rear_left = 左后 / 后排左
- rear_middle = 中后 / 后排中间
- rear_right = 右后 / 后排右
用户说「副驾」时 zones 必须是 ["front_right"]，禁止写成 rear_right。

## 工具目录
{catalog}

## 画像更新分拣（profile_update）

这是语义判断，**不是填表、不是关键词命中**。
不要因为没看到「座位 / 温度 / 称呼 / 住址」就认定没有可记的东西。
也不要因为出现了这几个词就自动打勾。

`profile_update` 与 `intent` **并行**：先定控车/问答主线，再问「这句话里有没有以后还用得上的信息」。
控车、查状态、闲聊都可以同时需要写笔记。

三份笔记只是三个篮子，篮子本身不限制内容：
1. **persona** — 用户在约束小特以后怎么说话（语气、长短、禁忌、口头禅、要不要开玩笑……任何说话方式）
2. **memory** — 用户在陈述关于自己的长期事实（是谁、和谁、在哪、做什么、经历过什么……任何身份/生活事实）
3. **preferences** — 用户在交代希望默认被怎样对待、车上默认怎么做（不限于座位温度；可以是导航习惯、媒体口味、提醒方式、称呼等）

判断方法：
- 读整句意思：这是一次性指令，还是希望以后都这样？
- 「现在打开空调」→ 全 false；「我一般喜欢车里凉一点」→ preferences true（不必已经有温度字段）
- 「别那么客服腔」→ persona true
- 「我下周要去见客户，我在做咨询」→ 若像长期身份/职业 memory true；若明显只是这一周的行程则 false
- 用户要求忘掉某类内容 → 对应 clear.* = true
- 拿不准但是明确在交代长期信息 → 宁可 true，让轮末改写模型再决定 UNCHANGED
- **禁止**用固定字段清单做过滤器

### 仅当以下情况 profile_update 全 false
- 纯一次性控车 / 查询 / 手册 / 寒暄，且没有长期有效的新信息

### clear
用户明确要求忘掉人设/记忆/偏好时，对应 clear 子字段 true

## 输出（只返回 JSON）
{{
  "intent": "search|tool|multi_tool|knowledge|chat",
  "confidence": 0.0到1.0,
  "reason": "简短原因",
  "done": true或false,
  "tool_calls": [
    {{"name": "maps.search_nearby", "arguments": {{"keywords": "商场", "radius": 5000}}, "reason": "..."}}
  ],
  "profile_update": {{
    "persona": false,
    "memory": false,
    "preferences": false,
    "clear": {{"persona": false, "memory": false, "preferences": false}}
  }}
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
            if r.data.get("correction_hint"):
                bit += f" | 纠参建议: {r.data.get('correction_hint')}"
            elif r.data.get("error_kind") == "validation" and r.data.get("errors"):
                bit += " | 请按工具 schema 修正参数后重试，勿重复相同坏参数"
            if r.data.get("need_clarify"):
                cands = r.data.get("candidates") or []
                names = [str(c.get("name") or "") for c in cands[:4] if isinstance(c, dict)]
                bit += f" | 待选候选: {names}"
                bit += (
                    " | 若用户已改口要上网搜索/问攻略好玩/否定候选，"
                    "禁止再 navigate；应 web.search 或 new 目的地规划"
                )
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
            if r.data.get("retryable") is False:
                bit += " | 不可盲目重试同参，请换策略或结束并口语说明"
        lines.append(bit)
    fails = [r for r in prior_results if not r.success]
    if fails:
        lines.append(
            "约束：若上一步参数校验失败，必须改参数或改工具，禁止原样重发；"
            "若业务失败，换策略或 done=true 并让上层口语解释，不要空转。"
        )
    oks = [r for r in prior_results if r.success]
    if oks:
        lines.append(
            "约束：已 OK 的工具禁止用同一 name+arguments 再调；"
            "用户请求已执行完成则 done=true 且 tool_calls=[]；"
            "仅当还需要基于观察做下一步（如周边检索后导航）才 done=false。"
        )
    return "\n".join(lines)


_MAP_APP_NAMES = {
    "高德地图",
    "高德",
    "amap",
    "地图",
    "车载地图",
    "腾讯地图",
    "百度",
}


def _user_asked_open_map_app(query: str) -> bool:
    """用户是否明确要求打开地图/高德类 App（不是「导航到…」）。"""
    text = query or ""
    if not re.search(r"(打开|开启|启动|关掉|关闭).{0,8}(高德|地图|amap|腾讯地图|百度地图)", text, re.I):
        return False
    # 「打开导航去X」不算打开地图 App
    if re.search(r"(打开|开启).{0,4}导航", text) and not re.search(
        r"(打开|开启).{0,6}(高德|地图App|地图应用|地图软件)", text, re.I
    ):
        return False
    return True


def sanitize_tool_calls(calls: List[ToolCall], query: str = "") -> List[ToolCall]:
    """硬门禁：相对导航剥掉；未点名则禁止顺手打开地图 App。"""
    out: List[ToolCall] = []
    allow_map_app = _user_asked_open_map_app(query)
    for c in calls:
        if c.name in {"navigation.navigate_to", "navigation.start"}:
            dest = str((c.arguments or {}).get("destination") or "")
            dest = strip_compound_tail_from_destination(dest)
            if dest and dest != str((c.arguments or {}).get("destination") or ""):
                args = dict(c.arguments or {})
                args["destination"] = dest
                c = ToolCall(name=c.name, arguments=args, reason=c.reason)
            if is_relative_or_category_destination(dest):
                continue
        if c.name == "apps.launch" and not allow_map_app:
            app = str((c.arguments or {}).get("app_name") or "").strip()
            app_norm = app.lower()
            if app in _MAP_APP_NAMES or app_norm in {x.lower() for x in _MAP_APP_NAMES}:
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
        from app.agent.context import slim_vehicle_for_query

        domains = _infer_tool_domains(query, prior_calls=prior_calls)
        catalog = self.registry.prompt_catalog(domains)
        seat = normalize_active_seat(active_seat)
        seat_cn = SEAT_CN.get(seat, seat)
        slim = slim_vehicle_for_query(vehicle_state, query)
        # 规划仍需要当前座位标注；曲库/折线已在 slim 里剔除
        seats = slim.get("seats") or {}
        climate = slim.get("climate") or {}
        cabin = slim.get("cabin") or {}
        zones = climate.get("zones") or {}
        plan_view = {
            "dynamics": slim.get("dynamics"),
            "climate": {
                **{k: climate.get(k) for k in ("power", "mode", "recirculation", "zones") if k in climate or k == "zones"},
                "active_zone": zones.get(seat),
            }
            if climate
            else None,
            "media": slim.get("media"),
            "seats": {
                **seats,
                "heat_active": (seats.get("heat") or {}).get(seat),
                "vent_active": (seats.get("ventilation") or {}).get(seat),
                "massage_active": (seats.get("massage") or {}).get(seat),
            }
            if seats
            else None,
            "cabin": {
                **cabin,
                "windows_active": (cabin.get("windows") or {}).get(
                    seat if seat != "rear_middle" else "rear_left"
                ),
                "doors_active": (cabin.get("doors") or {}).get(
                    seat if seat != "rear_middle" else "rear_left"
                ),
            }
            if cabin
            else None,
            "navigation": slim.get("navigation"),
            "apps": slim.get("apps"),
            "driving": slim.get("driving"),
            "active_seat": seat,
            "active_seat_cn": seat_cn,
        }
        plan_view = {k: v for k, v in plan_view.items() if v is not None}
        system = INTENT_SYSTEM.format(catalog=catalog)
        obs = _format_observations(prior_results or [], prior_calls)
        user = (
            f"当前规划步序: 第 {step_index} 步\n"
            f"当前说话人座位: {seat_cn} ({seat})\n"
            f"说明: 未点名座位时 zones/positions 用 [{seat}]；天窗用 sunroof。\n"
            f"分区对照: 主驾=front_left 副驾=front_right 左后=rear_left 中后=rear_middle 右后=rear_right。\n\n"
            f"当前车况摘要:\n{json.dumps(plan_view, ensure_ascii=False)}\n\n"
            f"历史摘要:\n{memory_hint or '无'}\n\n"
            f"已执行工具观察:\n{obs}\n\n"
            f"用户原话: {query}\n"
            + (
                "第1步须按语义判断本轮有没有长期有效信息再填 profile_update；"
                "三个篮子只是分类，不要靠座位/温度/称呼/住址等字段命中。\n"
                if step_index <= 1
                else ""
            )
            + f"请只规划下一步；有依赖就拆步；无依赖可并行；相对地点禁止 navigate。"
        )
        try:
            raw = self.llm.chat(system, user, temperature=0.0, max_tokens=480, retries=1)
            data = _extract_json(raw)
        except Exception as e:
            info = classify_llm_error(e, mode=getattr(self.llm, "mode", "remote"))
            return RouteResult(
                intent=IntentType.CHAT,
                confidence=0.2,
                reason=f"NLU失败:{info['kind']} | {info['error'][:1200]}",
                done=True,
            )

        intent_str = str(data.get("intent", "chat")).lower().strip()
        intent_map = {
            "knowledge": IntentType.KNOWLEDGE,
            "手册": IntentType.KNOWLEDGE,
            "查手册": IntentType.KNOWLEDGE,
            "知识": IntentType.KNOWLEDGE,
            "tool": IntentType.TOOL,
            "multi_tool": IntentType.MULTI_TOOL,
            "search": IntentType.SEARCH,
            "chat": IntentType.CHAT,
            "done": IntentType.CHAT,
        }
        intent = intent_map.get(intent_str, IntentType.CHAT)
        reason = str(data.get("reason", "llm-semantic") or "llm-semantic")
        intent = coerce_planned_intent(intent, query, reason)
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
            calls = sanitize_tool_calls(apply_active_seat_defaults(calls, seat), query)
            calls = recover_nearby_from_relative_nav(query, calls, orig_calls)
            recovered_from_relative = bool(calls) and any(
                c.name.startswith("navigation.")
                and is_relative_or_category_destination(str((c.arguments or {}).get("destination") or ""))
                for c in orig_calls
            )
            if not calls:
                intent = coerce_planned_intent(IntentType.CHAT, query, reason)
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

        intent = coerce_planned_intent(intent, query, reason)
        done = coerce_step_done(calls, done)
        profile_update = ProfileUpdatePlan()
        if step_index <= 1:
            profile_update = ProfileUpdatePlan.from_nlu_dict(data.get("profile_update"))
        return RouteResult(
            intent=intent,
            confidence=float(data.get("confidence", 0.7) or 0.7),
            reason=reason,
            tool_calls=calls,
            done=done,
            profile_update=profile_update,
        )
