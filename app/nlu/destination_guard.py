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
