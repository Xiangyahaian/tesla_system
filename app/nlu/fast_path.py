# -*- coding: utf-8 -*-
"""仅处理确认门控的短指令；意图分类不走关键词。"""
from __future__ import annotations

from typing import Optional

from app.models import IntentType, RouteResult


def try_confirm_utterance(query: str) -> Optional[RouteResult]:
    """用户对高风险操作的确认/取消（不是业务意图分类）。"""
    text = (query or "").strip().lower()
    if text in {"确认", "确定", "好的", "执行", "是", "yes", "y"}:
        return RouteResult(intent=IntentType.CONFIRM, confidence=1.0, reason="用户确认")
    if text in {"取消", "不要", "算了", "否", "no", "n"}:
        return RouteResult(intent=IntentType.CANCEL, confidence=1.0, reason="用户取消")
    return None
