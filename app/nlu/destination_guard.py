# -*- coding: utf-8 -*-
"""地点目的地类型门禁：相对/类别短语禁止直接进 navigate_to。"""
from __future__ import annotations

import re
from typing import Optional


# 「最近的商场」「附近充电站」「找个咖啡厅」等：只能走周边发现，不能当店名全市搜
_RELATIVE_DEST_RE = re.compile(
    r"("
    r"最近|附近|周边|旁边|四周|就近|顺路|"
    r"找个|找一家|随便|任意|"
    r"有什么|有哪些|哪儿有|哪里有"
    r")"
)

# 纯类别词（无具体店名）也不应直接导航
_CATEGORY_ONLY_RE = re.compile(
    r"^("
    r"商场|购物中心|超市|便利店|美食|餐厅|饭店|咖啡|咖啡馆|咖啡厅|"
    r"充电站|超充|加油站|停车场|厕所|卫生间|药店|医院|景点|公园"
    r")$"
)


def is_relative_or_category_destination(destination: Optional[str]) -> bool:
    """True = 不可作为 navigation.navigate_to 的 destination。"""
    text = (destination or "").strip()
    if not text:
        return True
    if _RELATIVE_DEST_RE.search(text):
        return True
    # 去掉口语前缀后再判纯类别
    stripped = re.sub(r"^(去|到|导航到|带我去|我想去)+", "", text).strip()
    if _CATEGORY_ONLY_RE.match(stripped):
        return True
    return False


def relative_destination_block_message(destination: str) -> str:
    return (
        f"「{destination}」不是具体地点名，不能直接导航。"
        f"请先 maps.search_nearby 按当前定位搜索，再根据结果里的店名导航，"
        f"或等用户选定「第几个 / 完整店名」。"
    )


# 复合句里其它能力子句误并入 destination 时的截断（LLM/正则兜底）
_COMPOUND_DEST_TAIL_RES = [
    re.compile(r"[，,；;]\s*(副驾|主驾|驾驶位|后排|左后|右后|中后).*$", re.I),
    re.compile(r"[，,；;]\s*(空调|温度|制冷|制热|风量).*$", re.I),
    re.compile(r"[，,；;]\s*(\d{2})\s*度.*$"),
    re.compile(r"[，,；;]\s*(播放|放首|放一首|来首|听一下|听首|播).*$", re.I),
    re.compile(r"[，,；;]\s*(顺便|并且|同时|还要|再).*$"),
]


def strip_compound_tail_from_destination(destination: Optional[str]) -> str:
    """去掉误并入导航目的地的空调/音乐等后半句。"""
    text = (destination or "").strip()
    if not text:
        return ""
    prev = None
    while prev != text:
        prev = text
        for pat in _COMPOUND_DEST_TAIL_RES:
            text = pat.sub("", text).strip()
    return text.rstrip("，,；; ").strip()


_DOMAIN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("navigation", re.compile(r"导航|带我去|我想去|开导航|目的地", re.I)),
    ("climate", re.compile(r"空调|温度|制冷|制热|风量|内循环|外循环|\d{2}\s*度", re.I)),
    ("media", re.compile(r"播放|放首|放一首|来首|听一下|听首|音乐|电台|音量|下一首|上一首", re.I)),
    ("maps", re.compile(r"附近|周边|旁边|充电站|加油站|停车场|美食|餐厅", re.I)),
    ("cabin", re.compile(r"车窗|天窗|后备箱|前备箱|氛围灯|阅读灯", re.I)),
    ("apps", re.compile(r"打开.{0,6}(飞书|微信|地图|高德|美团|应用)", re.I)),
]


def detect_utterance_domains(text: Optional[str]) -> set[str]:
    """识别原话涉及的能力域（用于判断是否复合多工具句）。"""
    q = (text or "").strip()
    if not q:
        return set()
    found: set[str] = set()
    for name, pat in _DOMAIN_PATTERNS:
        if pat.search(q):
            found.add(name)
    return found


def is_compound_multi_tool_utterance(text: Optional[str]) -> bool:
    """一句里同时涉及导航与其它控车/媒体域 → 禁止正则抽 destination，交 LLM 规划。"""
    domains = detect_utterance_domains(text)
    if len(domains) < 2:
        return False
    if "navigation" not in domains:
        return False
    return bool(domains - {"navigation"})


# 超过此长度视为复杂句，跳过正则快路径，交 StructuredNLU
COMPLEX_UTTERANCE_MIN_CHARS = 10


def is_complex_utterance(text: Optional[str]) -> bool:
    """字符数大于 COMPLEX_UTTERANCE_MIN_CHARS 视为复杂句。"""
    q = (text or "").strip()
    return len(q) > COMPLEX_UTTERANCE_MIN_CHARS


def should_skip_code_fast_path(text: Optional[str]) -> bool:
    """复合多工具或超长句：不走代码匹配，一律 LLM 规划。"""
    return is_complex_utterance(text) or is_compound_multi_tool_utterance(text)
