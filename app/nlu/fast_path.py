# -*- coding: utf-8 -*-
"""仅处理确认门控的短指令，以及少数无歧义舱体/周边直达（不代替通用语义规划）。"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from app.models import IntentType, RouteResult, ToolCall


def try_confirm_utterance(query: str) -> Optional[RouteResult]:
    """座舱口头确认/取消（文本或语音），不是业务意图分类。"""
    text = (query or "").strip().lower()
    if text in {
        "确认",
        "确定",
        "好的",
        "好",
        "可以",
        "行",
        "执行",
        "是",
        "嗯",
        "读吧",
        "看着吧",
        "看一下",
        "yes",
        "y",
        "ok",
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
        "no",
        "n",
    }:
        return RouteResult(intent=IntentType.CANCEL, confidence=1.0, reason="用户取消")
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
    if re.search(r"(附近|周边).*(有什么|有哪些|推荐)", text):
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


def try_nav_candidate_utterance(query: str, candidates: Optional[list] = None) -> Optional[RouteResult]:
    """上一轮导航澄清后：用户说「第一个 / 去首钢园」→ 直接导航到候选。"""
    text = (query or "").strip()
    if not text or not candidates:
        return None
    cands = [c for c in candidates if isinstance(c, dict) and (c.get("name") or "").strip()]
    if not cands:
        return None

    picked = None
    # 第 N 个 / 选 N / 只要数字
    m = re.search(r"(?:第\s*)?([1-4一二三四])\s*(?:个|项|处|号)?", text)
    if m or re.fullmatch(r"[1-4]", text):
        raw = m.group(1) if m else text
        idx_map = {"1": 1, "2": 2, "3": 3, "4": 4, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4}
        n = idx_map.get(str(raw), 0)
        if 1 <= n <= len(cands):
            picked = cands[n - 1]
    if picked is None:
        # 完整点名候选
        for c in cands:
            name = str(c.get("name") or "")
            if name and name in text:
                picked = c
                break
    if picked is None and re.search(r"^(去|到|导航|走|行)\s*(吧|啊|呀)?$", text):
        # 「去吧」过短，不猜
        return None
    if picked is None:
        return None

    dest = str(picked.get("name") or "").strip()
    if not dest:
        return None
    return RouteResult(
        intent=IntentType.TOOL,
        confidence=0.99,
        reason="选择导航候选",
        tool_calls=[
            ToolCall(
                name="navigation.navigate_to",
                arguments={"destination": dest, "preference": "fastest"},
                reason=f"用户选定：{dest}",
            )
        ],
    )


def try_status_utterance(query: str) -> Optional[RouteResult]:
    """明确的车况询问直达 SEARCH，避免被判成闲聊后瞎说「看不到」。"""
    text = (query or "").strip()
    if not text:
        return None
    # 氛围灯/灯光开没开
    if re.search(r"(氛围灯|阅读灯|顶灯|灯光).{0,8}(开|关|亮|状态|怎样|怎么样)", text) or re.search(
        r"(开着|关着|开了|关了).{0,6}(氛围灯|阅读灯|顶灯|灯光)|(氛围灯|阅读灯|顶灯|灯光).{0,6}(开着|关着|开了吗|关了吗)",
        text,
    ):
        return RouteResult(intent=IntentType.SEARCH, confidence=0.98, reason="查询灯光状态")
    if re.search(r"(现在|当前).{0,4}(氛围灯|阅读灯|顶灯|灯光)", text):
        return RouteResult(intent=IntentType.SEARCH, confidence=0.97, reason="查询灯光状态")
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
    """偏好记忆：我坐副驾喜欢22度 → 写入记忆并由 runtime 执行温控。"""
    text = (query or "").strip()
    if not text:
        return None
    if not re.search(r"(我坐|坐在|我在|喜欢|偏好|记住|默认).{0,12}(副驾|主驾|左后|右后|中后|\d{2}\s*度)", text):
        if not re.search(r"(副驾|主驾).{0,8}(喜欢|偏好|调到|设为).{0,6}\d{2}\s*度", text):
            return None
    return RouteResult(
        intent=IntentType.TOOL,
        confidence=0.99,
        reason="记忆偏好并应用",
        tool_calls=[],
    )


def try_combo_cabin_utterance(query: str) -> Optional[RouteResult]:
    """一句话多工具：导航 + 空调 + 音乐，端到端改地图/中控/语音。"""
    text = (query or "").strip()
    if not text:
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
