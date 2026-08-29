# -*- coding: utf-8 -*-
"""仅处理确认门控的短指令，以及少数无歧义舱体/周边直达（不代替通用语义规划）。"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from app.gateway.apps_catalog import INSTALLED_APPS, normalize_app_name
from app.models import IntentType, RouteResult, ToolCall
from app.nlu.destination_guard import (
    is_relative_or_category_destination,
    should_skip_code_fast_path,
)


def try_confirm_utterance(query: str) -> Optional[RouteResult]:
    """座舱口头确认/取消（文本或语音），不是业务意图分类。"""
    text = (query or "").strip().lower().rstrip("！!。.?？~～")
    if text in {
        "确认",
        "确定",
        "好的",
        "好的呀",
        "好呀",
        "好啊",
        "好",
        "可以",
        "可以的",
        "行",
        "行啊",
        "执行",
        "是",
        "是的",
        "嗯",
        "嗯嗯",
        "读吧",
        "看着吧",
        "看一下",
        "同意",
        "没问题",
        "继续",
        "yes",
        "y",
        "ok",
        "okay",
    }:
        return RouteResult(intent=IntentType.CONFIRM, confidence=1.0, reason="用户确认")
    if text in {
        "取消",
        "不要",
        "算了",
        "否",
        "不用了",
        "先别",
        "别读了",
        "不看了",
        "别了",
        "停",
        "停下",
        "no",
        "n",
    }:
        return RouteResult(intent=IntentType.CANCEL, confidence=1.0, reason="用户取消")
    return None


def is_pending_hold_utterance(query: str) -> bool:
    """短糊糊话：保留 pending，不要当成新指令覆盖。"""
    raw = (query or "").strip().lower()
    if not raw:
        return True
    if raw in {"嗯？", "啊？", "哦？", "什么？", "啥？", "？", "?", "…", "..."}:
        return True
    text = raw.rstrip("！!。.~～")
    if not text:
        return True
    if len(text) <= 2 and text in {"啊", "哦", "噢", "额", "呃"}:
        return True
    return text in {"什么", "啥", "再说", "再说一遍", "什么意思"}


def try_greeting_reply(query: str) -> Optional[str]:
    """纯寒暄直接回，不进 NLU / 不灌车况。"""
    text = (query or "").strip()
    if not text or len(text) > 24:
        return None
    t = text.lower().rstrip("！!。.?？~～")
    greetings = {
        "你好",
        "您好",
        "嗨",
        "哈喽",
        "hello",
        "hi",
        "hey",
        "在吗",
        "在不在",
        "你在吗",
        "小特",
        "小特你好",
        "你好小特",
        "早上好",
        "中午好",
        "下午好",
        "晚上好",
    }
    if t in greetings or re.fullmatch(r"(小特[，,\s]*)?(你好|您好|在吗|嗨)", t):
        return "【听】在呢，有事直接说就行。"
    return None


def _nearby_keywords(text: str) -> Optional[Tuple[str, str]]:
    """命中周边检索时返回 (keywords, reason)。"""
    if not re.search(r"(附近|周边|旁边|四周|这附近|我附近)", text):
        # 也允许「有哪些充电站」这类省略「附近」但强烈指向本地服务
        if not re.search(r"(充电站|超充|加油站).*(哪|有|推荐)|(哪|有|推荐).*(充电站|超充|加油站)", text):
            return None

    rules = [
        (r"(好吃|美食|餐厅|饭店|小吃|晚饭|午饭|早餐|宵夜|火锅|烧烤)", "美食", "附近美食"),
        (r"(咖啡|咖啡厅|喝咖啡)", "咖啡", "附近咖啡"),
        (r"(充电站|超充|充电桩|补能)", "充电站", "附近充电站"),
        (r"(加油站|加油)", "加油站", "附近加油站"),
        (r"(停车场|停车|泊车位)", "停车场", "附近停车场"),
        (r"(厕所|卫生间|洗手间)", "公共厕所", "附近卫生间"),
        (r"(景点|好玩|逛逛|公园)", "风景名胜", "附近景点"),
        (r"(药店|医院|诊所)", "药店", "附近药店"),
        (r"(便利店|超市)", "便利店", "附近便利店"),
    ]
    for pat, kw, reason in rules:
        if re.search(pat, text):
            return kw, reason
    # 只接「附近/周边有什么」打听店，不接「去周边转转你推荐哪」这种陪聊
    if re.search(r"(附近|周边|旁边).{0,8}(有什么|有哪些)", text):
        return "生活服务", "附近推荐"
    return None


def try_nearby_utterance(query: str) -> Optional[RouteResult]:
    """周边生活服务直达高德检索，避免被判成纯闲聊。"""
    text = (query or "").strip()
    if not text:
        return None
    hit = _nearby_keywords(text)
    if not hit:
        return None
    keywords, reason = hit
    return RouteResult(
        intent=IntentType.TOOL,
        confidence=0.98,
        reason=reason,
        tool_calls=[
            ToolCall(
                name="maps.search_nearby",
                arguments={"keywords": keywords, "radius": 3000},
                reason=reason,
            )
        ],
    )


_WEB_CMD = re.compile(
    r"^(?:请|麻烦|帮我|给我)?"
    r"(?:在网上|网上|用百度|百度|谷歌|google)?"
    r"(?:搜(?:索|一下|一搜|搜)?|查(?:一下|一查)?|百度一下)\s*(.+)$",
    re.I,
)
_WEB_BAIDU = re.compile(r"^(?:请|麻烦|帮我|给我)?百度一下\s*(.+)$", re.I)
_NEARBY_STEAL = re.compile(r"(附近|周边|旁边).{0,8}(餐厅|美食|充电|加油|停车|咖啡|酒店|厕所)")


def extract_web_query(text: str) -> Optional[str]:
    q = (text or "").strip()
    if not q or len(q) > 80:
        return None
    q = re.sub(r"[吧啊呀哦呢嘛～~]+$", "", q).strip()
    q = re.sub(r"[。.!！？?\s]+$", "", q).strip()
    if looks_like_vehicle_knowledge(q):
        return None
    if looks_like_smalltalk(q):
        return None
    if _NEARBY_STEAL.search(q) or re.search(r"(搜|找|查).{0,4}(附近|周边)", q):
        return None
    m = _WEB_BAIDU.match(q) or _WEB_CMD.match(q)
    if not m:
        # 「今天有什么新闻 / 今日热点」也视为检索
        if re.search(
            r"(昨天|昨日|今天|今日|最近|本周|这一周|一周).{0,16}(新闻|热点|头条|大事)",
            q,
        ) or re.search(r"(总结|梳理).{0,16}(新闻|热点|大事)", q):
            if not re.search(r"(附近|导航|手册|怎么用)", q):
                return q
        return None
    rest = (m.group(1) or "").strip()
    rest = re.sub(r"^(一下|下|这个|那个)\s*", "", rest).strip()
    rest = re.sub(r"[。.!！？?\s]+$", "", rest).strip()
    if not rest or len(rest) < 2:
        return None
    if re.match(r"^(附近|周边|旁边)", rest):
        return None
    if re.search(r"(电量|续航|胎压|音量|空调|温度|车窗|座椅|正在播|在听什么)", rest):
        return None
    return rest


def try_web_search_utterance(query: str) -> Optional[RouteResult]:
    """明确「搜一下 / 百度一下 / 网上查」直达网页搜索。"""
    rest = extract_web_query(query)
    if not rest:
        return None
    return RouteResult(
        intent=IntentType.TOOL,
        confidence=0.96,
        reason="网页检索",
        tool_calls=[
            ToolCall(
                name="web.search",
                arguments={"query": rest, "count": 5},
                reason="网页检索",
            )
        ],
        done=True,
    )


_CHAT_WEB_TOPIC = re.compile(
    r"(电影|影片|片子|片单|影讯|上映|院线|豆瓣|想看片|好看的片|电视剧|剧集|综艺)"
)
_CHAT_WEB_FOLLOW = re.compile(
    r"(这个|这部|那部|刚才(?:说|提)的).{0,12}(电影|片子|片|剧)|"
    r"(好看在哪|为什么好看|值不值得看|剧情怎么样|口碑怎么样|评分怎么样)"
)


def _recent_user_lines(recent: str, limit: int = 2) -> list[str]:
    lines: list[str] = []
    for m in re.finditer(r"(?:^|\n)(?:user|用户)[:：]\s*(.+)", recent or "", re.I):
        t = (m.group(1) or "").strip()
        if t:
            lines.append(t)
    return lines[-limit:]


def chat_web_query(query: str, recent: str = "") -> Optional[str]:
    """闲聊需要网上事实时给出检索词（电影推荐/追问「这个电影」等），否则 None。"""
    q = (query or "").strip()
    if not q or looks_like_vehicle_knowledge(q):
        return None
    if _NEARBY_STEAL.search(q) or re.search(r"(搜|找|查).{0,4}(附近|周边)", q):
        return None
    if re.search(r"(打开|关掉|关闭).{0,6}(空调|车窗|天窗|导航|音乐)", q):
        return None
    if _CHAT_WEB_FOLLOW.search(q):
        prev = _recent_user_lines(recent)
        blob = " ".join([*prev, q]).strip()
        return (blob or q)[:80]
    if _CHAT_WEB_TOPIC.search(q):
        return q[:80]
    return None


def try_app_utterance(query: str) -> Optional[RouteResult]:
    """打开/关闭已安装 App 直达，不经 NLU。"""
    text = (query or "").strip()
    if not text or len(text) > 36:
        return None
    m = re.search(r"(打开|开启|启动|关掉|关闭|退出)\s*(.+)$", text)
    if not m:
        return None
    action, raw = m.group(1), m.group(2).strip()
    raw = re.sub(r"[吧啊呀哦呢嘛～~。.!！？?\s]+$", "", raw).strip()
    raw = re.sub(r"^(一下|下|这个|那个)", "", raw).strip()
    if not raw or re.search(r"(空调|天窗|车窗|导航|音乐|歌|电台|座椅|门|锁)", raw):
        return None
    enable = action in {"打开", "开启", "启动"}
    # 长名优先，避免「音乐」吃掉「网易云音乐」
    candidates: list[str] = []
    for app in INSTALLED_APPS:
        candidates.append(str(app["name"]))
        for a in app.get("aliases") or []:
            candidates.append(str(a))
    candidates.sort(key=len, reverse=True)
    hit = ""
    low = raw.lower()
    for c in candidates:
        if low == c.lower() or low.startswith(c.lower()) or c.lower() in low:
            hit = c
            break
    if not hit:
        return None
    name = normalize_app_name(hit)
    verb = "打开" if enable else "关闭"
    return RouteResult(
        intent=IntentType.TOOL,
        confidence=0.98,
        reason=f"{verb}应用",
        tool_calls=[
            ToolCall(
                name="apps.launch",
                arguments={"app_name": name, "enable": enable},
                reason=f"{verb}{name}",
            )
        ],
        done=True,
    )


def try_fast_path_route(query: str, nav_candidates: Optional[list] = None) -> Optional[RouteResult]:
    """快路径总入口：澄清选点保留；复杂/复合句跳过代码匹配，交 StructuredNLU。"""
    cand = try_nav_candidate_utterance(query, nav_candidates)
    if cand is not None:
        return cand
    if should_skip_code_fast_path(query):
        return None
    return (
        try_app_utterance(query)
        or try_status_utterance(query)
        or try_direct_cabin_utterance(query)
        or try_nearby_utterance(query)
        or try_web_search_utterance(query)
    )


def try_navigate_utterance(query: str) -> Optional[RouteResult]:
    """已废弃主路径：导航目的地一律交 StructuredNLU。仅保留供单测/离线脚本引用。"""
    return None


def try_nav_candidate_utterance(query: str, candidates: Optional[list] = None) -> Optional[RouteResult]:
    """上一轮导航澄清后：仅在候选集合内选定；选中则直达导航。"""
    from app.nlu.nav_resolve import resolve_nav_selection

    sel = resolve_nav_selection(query, candidates)
    if sel.action != "navigate" or not sel.destination:
        return None
    args: dict = {"destination": sel.destination, "preference": "fastest"}
    loc = (sel.location or "").strip()
    if loc and "," in loc:
        args["destination_location"] = loc
    return RouteResult(
        intent=IntentType.TOOL,
        confidence=0.99,
        reason="选择导航候选",
        tool_calls=[
            ToolCall(
                name="navigation.navigate_to",
                arguments=args,
                reason=f"用户选定：{sel.destination}",
            )
        ],
        done=True,
    )


def try_status_utterance(query: str) -> Optional[RouteResult]:
    """明确的车况询问直达 SEARCH，避免被判成闲聊后瞎说「看不到」。"""
    text = (query or "").strip()
    if not text:
        return None
    # 氛围灯/灯光开没开（灯光秀是手册功能，不要当成读灯状态）
    if "灯光秀" not in text and (
        re.search(r"(氛围灯|阅读灯|顶灯|(?<!秀)灯光).{0,8}(开了吗|关了吗|开着|关着|亮着|亮不亮|状态)", text)
        or re.search(
            r"(开着|关着|开了|关了).{0,6}(氛围灯|阅读灯|顶灯|灯光)|(氛围灯|阅读灯|顶灯|灯光).{0,6}(开着|关着|开了吗|关了吗)",
            text,
        )
        or re.search(r"(现在|当前).{0,4}(氛围灯|阅读灯|顶灯|灯光)", text)
    ):
        return RouteResult(intent=IntentType.SEARCH, confidence=0.98, reason="查询灯光状态")
    # 在哪 / 位置（含「哪儿 / 哪啊」口语）。不要把「好看在哪里」当成定位。
    if re.search(
        r"(我|我们|这辆车|车子).{0,8}(现在|当前)?.{0,4}(在哪|在哪里|在哪儿|什么地方|哪个位置|啥地方)"
        r"|(现在|当前).{0,4}(在哪|在哪里|在哪儿|位置|定位)"
        r"|(到哪了|到哪儿了)",
        text,
    ):
        return RouteResult(intent=IntentType.SEARCH, confidence=0.98, reason="查询当前位置")
    if re.fullmatch(
        r"(我|我们)?(现在|当前)?(在哪|在哪里|在哪儿|什么地方|哪个位置)[儿啊呀呢吧哦噢～~？?。！!\s]*$",
        text,
    ):
        return RouteResult(intent=IntentType.SEARCH, confidence=0.99, reason="查询当前位置")
    # 导航剩余时间/里程
    if re.search(
        r"(还差|还有|剩余|还要).{0,6}(几分钟|多久|多远|几公里|多少公里|多少分钟)"
        r"|(多久|几点).{0,4}(到|到达)|(ETA|预计).{0,4}(到达|时间)"
        r"|还差几分钟|还有多久|还有多远|还要多久",
        text,
        re.I,
    ):
        return RouteResult(intent=IntentType.SEARCH, confidence=0.98, reason="查询导航进度")
    if re.search(r"^(还差多少|还有多久|还有多远|还要多久|预计到达|什么时候到)[？?]?$", text):
        return RouteResult(intent=IntentType.SEARCH, confidence=0.99, reason="查询导航进度")
    return None


def try_direct_cabin_utterance(query: str) -> Optional[RouteResult]:
    """天窗等无歧义指令直达工具，避免被判成闲聊。"""
    text = (query or "").strip()
    if not text:
        return None

    # 读消息（Agent 侧需确认门控；无「授权」模型。旧话术「授权读取」也落到朗读确认）
    if re.search(
        r"(授权|允许|可以).*(读|看|查).*(消息|微信|短信)|(读|看|查).*(消息|微信|短信).*(授权|允许)"
        r"|^(授权读取消息|授权消息|可以读消息|允许读消息)$"
        r"|(哪些|什么|有没有|收到|未读).*(消息|微信|短信)|(消息|微信|短信).*(哪些|什么|未读|一下)|读一下.*(消息|微信|短信)",
        text,
    ):
        unread_only = bool(re.search(r"未读", text))
        return RouteResult(
            intent=IntentType.TOOL,
            confidence=0.97,
            reason="查询消息（需确认）",
            tool_calls=[
                ToolCall(
                    name="notifications.list_messages",
                    arguments={"unread_only": unread_only, "mark_read": True},
                    reason="朗读消息",
                )
            ],
        )
    if re.search(r"(全部已读|都已读|标成已读|标记已读)", text):
        return RouteResult(
            intent=IntentType.TOOL,
            confidence=0.97,
            reason="消息全部已读",
            tool_calls=[
                ToolCall(
                    name="notifications.mark_read",
                    arguments={"all_unread": True},
                    reason="消息全部已读",
                )
            ],
        )

    # Wi‑Fi
    if re.search(r"(开|打开|开启).*(wifi|Wi‑?Fi|无线网|热点)", text, re.I):
        return RouteResult(
            intent=IntentType.TOOL,
            confidence=0.96,
            reason="打开 Wi‑Fi",
            tool_calls=[ToolCall(name="connectivity.set_wifi", arguments={"enable": True}, reason="打开 Wi‑Fi")],
        )
    if re.search(r"(关|关闭|断开).*(wifi|Wi‑?Fi|无线网|热点)", text, re.I):
        return RouteResult(
            intent=IntentType.TOOL,
            confidence=0.96,
            reason="关闭 Wi‑Fi",
            tool_calls=[ToolCall(name="connectivity.set_wifi", arguments={"enable": False}, reason="关闭 Wi‑Fi")],
        )

    # 打开/关闭空调（座位与温度由 memory + active_seat 补全）
    if re.search(r"^(帮我)?(把)?空调(打开|开启|开一下|开着)?$|^(打开|开启)空调$|把空调打开", text):
        return RouteResult(
            intent=IntentType.TOOL,
            confidence=0.97,
            reason="打开空调（记忆座位/温度）",
            tool_calls=[
                ToolCall(name="climate.set_power", arguments={"enable": True}, reason="打开空调"),
            ],
        )
    if re.search(r"^(帮我)?(把)?空调(关掉|关闭|关上)$|^(关闭|关掉)空调$", text):
        return RouteResult(
            intent=IntentType.TOOL,
            confidence=0.97,
            reason="关闭空调",
            tool_calls=[
                ToolCall(name="climate.set_power", arguments={"enable": False}, reason="关闭空调"),
            ],
        )

    if "天窗" not in text:
        return None

    if re.search(r"(关|收起|合上|关上)", text):
        percent = 0
        reason = "关闭天窗"
    elif re.search(r"(开|打开|开启|升起|全开)", text):
        percent = 100
        reason = "打开天窗"
    else:
        return None

    return RouteResult(
        intent=IntentType.TOOL,
        confidence=0.99,
        reason=reason,
        tool_calls=[
            ToolCall(
                name="cabin.set_windows",
                arguments={"percent": percent, "positions": ["sunroof"]},
                reason=reason,
            )
        ],
    )


def try_preference_utterance(query: str) -> Optional[RouteResult]:
    """已废弃：记忆意图改由轮初 LLM 抽取 + primary_memory_turn 处理。"""
    return None


def try_combo_cabin_utterance(query: str) -> Optional[RouteResult]:
    """一句话多工具：导航 + 空调 + 音乐（仅非复合句兜底；复合句交 StructuredNLU）。"""
    text = (query or "").strip()
    if not text or should_skip_code_fast_path(text):
        return None
    has_nav = bool(re.search(r"导航到|(导航|开导航).{0,16}(软件园|五道口|西单|西站)", text))
    has_climate = bool(re.search(r"(空调|温度).{0,10}\d{2}\s*度|\d{2}\s*度.{0,6}(空调|温度)", text))
    has_music = bool(re.search(r"(播放|放首|放一?首|听).{0,16}(晴天|歌|音乐|周杰伦)", text))
    if sum([has_nav, has_climate, has_music]) < 2:
        return None

    calls = []
    if has_nav:
        dest = "中关村软件园"
        if "五道口" in text:
            dest = "五道口地铁站"
        elif "西单" in text:
            dest = "西单大悦城"
        elif "西站" in text:
            dest = "北京西站"
        calls.append(
            ToolCall(
                name="navigation.navigate_to",
                arguments={"destination": dest, "preference": "fastest"},
                reason="一句话导航",
            )
        )
    if has_climate:
        m = re.search(r"(\d{2})\s*度", text)
        temp = float(m.group(1)) if m else 22.0
        temp = min(30.0, max(16.0, temp))
        zone = "front_right" if "副驾" in text else ("front_left" if "主驾" in text else None)
        pargs = {"enable": True}
        if zone:
            pargs["zones"] = [zone]
        calls.append(ToolCall(name="climate.set_power", arguments=pargs, reason="一句话开空调"))
        targs = {"temperature": temp}
        if zone:
            targs["zones"] = [zone]
        calls.append(ToolCall(name="climate.set_temperature", arguments=targs, reason="一句话设温度"))
    if has_music:
        artist = "周杰伦" if "周杰伦" in text else None
        title = "晴天" if "晴天" in text else None
        calls.append(
            ToolCall(
                name="media.play_music",
                arguments={"artist": artist, "title": title},
                reason="一句话播放音乐",
            )
        )
    if len(calls) < 2:
        return None
    return RouteResult(
        intent=IntentType.MULTI_TOOL,
        confidence=0.98,
        reason="一句话多工具联动",
        tool_calls=calls[:6],
    )


_VEHICLE_TERMS = (
    r"(充电|超充|充电桩|充电口|充电器|充电设备|充电枪|"
    r"泊车|自动泊车|智能泊车|哨兵|玩具箱|灯光秀|"
    r"后备箱|前备箱|车窗|天窗|车门|方向盘|座椅|"
    r"摄像头|前撞|碰撞预警|预警|制动|能量回收|宠物模式|营地模式|"
    r"手机钥匙|行车记录|胎压|电池图标|电池|电量|"
    r"Model\s*[SXY3]|车辆|车主|用车|手册|"
    r"雨刮|雨刷|除雾|除霜|冷凝|总质量|超时占用|"
    r"音频内容|超级充电|仪表盘|故障灯|指示灯)"
)
_HOWTO = r"(怎么|如何|怎样|咋|怎么办|该如何|用哪些方式|怎样才能|要怎么|该怎么|如何操作)"
_WHY = r"(为什么|为啥|为何)"
_WHAT = r"(什么意思|代表着什么|是什么意思|什么情况|什么状况|哪些东西|包含哪些|能不能|可以监测|哪种情况)"
_TROUBLE = r"(无法|不能|充不了|充不上|充不进|不正常|故障|报警|坏了|没电|耗尽|打不开|关不上|充不进去)"
_KNOWLEDGE_REASON_POS = re.compile(
    r"(应调用\s*knowledge|intent\s*[:=]\s*[\"']?knowledge|查手册|手册问法|"
    r"车主手册|功能操作咨询|知识库问法)",
    re.I,
)
_KNOWLEDGE_REASON_NEG = re.compile(
    r"(禁止.{0,16}knowledge|不是\s*knowledge|不要.{0,12}knowledge|"
    r"符合\s*chat|属于.{0,8}(寒暄|闲聊)|而非.{0,6}闲聊)",
    re.I,
)


def looks_like_vehicle_knowledge(query: str) -> bool:
    """车主手册问法：怎么用 / 故障怎么办 / 图标什么意思。"""
    text = (query or "").strip()
    if not text:
        return False
    if looks_like_smalltalk(text):
        return False
    if re.search(r"(附近|周边|旁边).{0,10}(充电站|超充|加油站|停车场|餐厅|美食|咖啡)", text):
        return False
    if re.search(
        r"(现在|当前).{0,8}(多少度|音量|在听|播放|开了吗|关了吗|电量多少|剩余续航)|"
        r"(空调|温度|音量).{0,4}(现在|当前)?.{0,4}(多少|几度|开了吗|关了吗)",
        text,
    ):
        return False
    if re.search(
        r"^(帮我|请)?(把)?(打开|关闭|关掉|开启|设置|调到|播放|导航到|导航去)",
        text,
    ) and not re.search(_HOWTO, text) and not re.search(_TROUBLE, text):
        return False

    vehicle = bool(re.search(_VEHICLE_TERMS, text, re.I))
    howto = bool(re.search(_HOWTO, text))
    why = bool(re.search(_WHY, text))
    what = bool(re.search(_WHAT, text))
    trouble = bool(re.search(_TROUBLE, text))

    if re.search(r"(无法充电|充不了电|充不上电|充不进电|不能充电|没法充电)", text):
        return True
    if trouble and (vehicle or howto or "怎么办" in text):
        return True
    if howto and vehicle:
        return True
    if why and vehicle:
        return True
    if what and vehicle:
        return True
    if howto and re.search(r"(清洁|操作|使用|设置|开启|关闭|寻找|停车|搜索)", text) and re.search(
        r"(车|摄像头|后备箱|充电|制动|音频)", text
    ):
        return True
    return False


def looks_like_smalltalk(query: str) -> bool:
    """寒暄、问助手身份、陪聊吐槽：走 chat，不是查车辆识别码。"""
    text = (query or "").strip()
    if not text:
        return False
    t = re.sub(r"[！!。.?？~～\s]+$", "", text)
    t = re.sub(r"[啊呀哦呢吧嘛呀]+$", "", t).strip()
    if re.fullmatch(
        r"(小特[，,\s]*)?(你|您)(是谁|谁呀|谁啊|叫什么|叫啥|是什么|什么人|什么来头)",
        t,
    ):
        return True
    if re.search(
        r"(介绍一下你自己|你是人工智能|你是机器人|你是ai|who are you|what are you)",
        text,
        re.I,
    ):
        return True
    if t in {
        "你好",
        "您好",
        "嗨",
        "哈喽",
        "在吗",
        "谢谢",
        "谢谢你",
        "感谢",
        "再见",
        "拜拜",
        "bye",
        "小特",
    }:
        return True
    if re.search(r"(心情|烦躁|孤独|吐槽|陪我聊|放松一下|脑子很乱|不顺心|好无聊|讲个笑话)", text):
        return True
    return False


def reason_wants_knowledge(reason: str) -> bool:
    text = reason or ""
    if not text or _KNOWLEDGE_REASON_NEG.search(text):
        return False
    return bool(_KNOWLEDGE_REASON_POS.search(text))


def coerce_planned_intent(intent: IntentType, query: str, reason: str = "") -> IntentType:
    """闲聊/身份问被标成 knowledge 时纠回去；手册意图只信 LLM 的 intent/reason，不用 query 正则。"""
    if looks_like_smalltalk(query) or looks_like_entertainment_chat(query):
        return IntentType.CHAT if intent == IntentType.KNOWLEDGE else intent
    if intent == IntentType.CHAT and reason_wants_knowledge(reason):
        return IntentType.KNOWLEDGE
    return intent


def try_knowledge_utterance(query: str) -> Optional[RouteResult]:
    """已废弃运行时快路径：手册问法一律走 StructuredNLU，不在此做正则直达。"""
    return None


def try_chat_utterance(query: str) -> Optional[RouteResult]:
    """已不再作为运行时快路径；保留给纠偏测试。身份/陪聊走 StructuredNLU。"""
    return None


def looks_like_entertainment_chat(query: str) -> bool:
    """歌曲创作故事/娱乐闲谈：不应走进车主手册 knowledge 路径。"""
    text = (query or "").strip()
    if not text:
        return False
    if re.search(
        r"(这首歌|那首歌|这曲|那曲|歌词|专辑|创作背景|作曲|作词|谁唱的|歌手|"
        r"有什么故事|什么故事|背后的故事|为什么叫这个名字)",
        text,
    ):
        return True
    if re.search(r"(电影|影讯|八卦|明星|剧情|冷知识|猜谜|讲个故事|笑话)", text):
        return True
    return False
