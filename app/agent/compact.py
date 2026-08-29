# -*- coding: utf-8 -*-
"""追加式上下文压缩：不覆盖历史，只在末尾追加 compaction 摘要。

读上下文时：最新一条 compaction + 最近 N 轮对话（默认 5 轮）。
一轮 = 从一条 user 起到下一条 user 之前（含 assistant/tool）。
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

from app.agent.types import CompactReport, MessageRole, TranscriptMessage
from app.llm.client import LLMClient

SUMMARY_SYSTEM = """你是车载智能座舱的会话归档员。请把对话整理成「精简且完整」的中文摘要。

必须覆盖（有则写，无则跳过）：
1) 用户身份与关系：姓名/称呼、家人、住址、公司/职业
2) 人设约定：语气、回复风格、禁忌
3) 车上偏好：常坐座位、温度/风量、音乐口味、导航习惯
4) 已执行操作与结果：空调、座椅、车窗、灯光、导航、媒体、ADAS 等
5) 未完成事项、待确认操作、关键地点与实体名称
6) 若提供了「既有摘要」，必须合并进新摘要，保留旧信息并吸收新内容，不要只写本段

格式：短句或「- 条目」，信息密度高，禁止套话与猜测；控制在 400 字以内。"""


def is_compaction(m: TranscriptMessage) -> bool:
    return m.role == MessageRole.COMPACTION


def last_compaction(msgs: List[TranscriptMessage]) -> Optional[TranscriptMessage]:
    for m in reversed(msgs):
        if is_compaction(m):
            return m
    return None


def index_after_last_compaction(msgs: List[TranscriptMessage]) -> int:
    idx = -1
    for i, m in enumerate(msgs):
        if is_compaction(m):
            idx = i
    return idx + 1


def messages_since_last_compaction(msgs: List[TranscriptMessage]) -> List[TranscriptMessage]:
    return msgs[index_after_last_compaction(msgs) :]


def count_user_turns(msgs: List[TranscriptMessage]) -> int:
    return sum(1 for m in msgs if m.role == MessageRole.USER)


def split_keep_recent_turns(
    msgs: List[TranscriptMessage], keep_turns: int
) -> Tuple[List[TranscriptMessage], List[TranscriptMessage]]:
    """把消息拆成 (更早需压缩, 最近 keep_turns 轮)。compaction 行不计入轮次。"""
    if keep_turns <= 0:
        return list(msgs), []
    user_idxs = [i for i, m in enumerate(msgs) if m.role == MessageRole.USER]
    if len(user_idxs) <= keep_turns:
        return [], list(msgs)
    cut = user_idxs[-keep_turns]
    return list(msgs[:cut]), list(msgs[cut:])


def select_context_window(
    msgs: List[TranscriptMessage], keep_turns: int = 5
) -> List[TranscriptMessage]:
    """供模型使用的窗口：最新 compaction（若有）+ 最近 N 轮非 compaction 对话。"""
    latest = last_compaction(msgs)
    dialogue = [m for m in msgs if not is_compaction(m)]
    _, recent = split_keep_recent_turns(dialogue, keep_turns)
    out: List[TranscriptMessage] = []
    if latest is not None:
        out.append(latest)
    out.extend(recent)
    return out


def _format_blob(msgs: List[TranscriptMessage], per_msg: int = 360) -> str:
    lines = []
    for m in msgs:
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        tool = ""
        if m.role == MessageRole.TOOL and isinstance(m.meta, dict):
            name = m.meta.get("tool")
            if name:
                tool = f"({name})"
        lines.append(f"{role}{tool}: {(m.content or '')[:per_msg]}")
    return "\n".join(lines)


class ContextCompactor:
    def __init__(
        self,
        soft_limit_chars: int = 24_000,
        hard_limit_chars: int = 40_000,
        keep_recent_turns: int = 5,
        keep_recent: int = 0,  # 兼容旧参数：若 >0 且未显式传 turns，当作消息条数近似
        tool_max_chars: int = 800,
        max_auto_fail: int = 3,
    ):
        self.soft_limit = soft_limit_chars
        self.hard_limit = hard_limit_chars
        if keep_recent_turns and keep_recent_turns > 0:
            self.keep_recent_turns = keep_recent_turns
        elif keep_recent and keep_recent > 0:
            # 旧 keep_recent 是消息条数；约 2 条/轮
            self.keep_recent_turns = max(1, (keep_recent + 1) // 2)
        else:
            self.keep_recent_turns = 5
        self.keep_recent = keep_recent or (self.keep_recent_turns * 2)
        self.tool_max_chars = tool_max_chars
        self.max_auto_fail = max_auto_fail
        self._fail_streak = 0

    def total_chars(self, msgs: List[TranscriptMessage]) -> int:
        return sum(m.approx_chars() for m in msgs)

    def active_segment_chars(self, msgs: List[TranscriptMessage]) -> int:
        """自上一条 compaction 以来的字符量（触发压缩用）。"""
        return self.total_chars(messages_since_last_compaction(msgs))

    def should_compact(self, msgs: List[TranscriptMessage], force: bool = False) -> bool:
        if force:
            return True
        return self.active_segment_chars(msgs) >= self.soft_limit

    def build_append_compaction(
        self,
        messages: List[TranscriptMessage],
        llm: Optional[LLMClient] = None,
        force: bool = False,
    ) -> Tuple[Optional[TranscriptMessage], CompactReport]:
        """生成一条应追加到文件末尾的 compaction；不改写既有消息。

        返回 (compaction_msg|None, report)。
        """
        msgs = list(messages)
        report = CompactReport(before_chars=self.active_segment_chars(msgs))
        if not force and not self.should_compact(msgs, force=False):
            report.after_chars = report.before_chars
            return None, report

        segment = messages_since_last_compaction(msgs)
        older, recent = split_keep_recent_turns(segment, self.keep_recent_turns)
        # 没有可压缩的「更早」内容则跳过（除非 force 且存在既有摘要可刷新——仍要求有 older）
        if not older:
            report.after_chars = report.before_chars
            report.layers.append("skipped_no_older")
            return None, report

        prior = last_compaction(msgs)
        if llm is None:
            report.after_chars = report.before_chars
            self._fail_streak += 1
            report.thrash_count = self._fail_streak
            return None, report

        if self._fail_streak >= self.max_auto_fail and not force:
            report.after_chars = report.before_chars
            report.thrash_count = self._fail_streak
            return None, report

        summary = self._summarize(llm, prior.content if prior else "", older)
        if not summary:
            self._fail_streak += 1
            report.thrash_count = self._fail_streak
            report.after_chars = report.before_chars
            return None, report

        self._fail_streak = 0
        compact_msg = TranscriptMessage(
            role=MessageRole.COMPACTION,
            content=summary,
            ts=time.time(),
            meta={
                "layer": "append_compact",
                "compressed_msgs": len(older),
                "kept_turns": self.keep_recent_turns,
                "kept_msgs": len(recent),
                "prior_compaction": bool(prior),
            },
        )
        report.layers.append("append_compact")
        report.summary = summary
        # after：上下文窗口估算 = 新摘要 + 最近轮
        window = ([compact_msg] + recent)
        report.after_chars = self.total_chars(window)
        return compact_msg, report

    def _summarize(self, llm: LLMClient, prior_summary: str, older: List[TranscriptMessage]) -> str:
        blob = _format_blob(older)
        # 控制送入长度，避免一次压爆
        if len(blob) > 12000:
            blob = blob[:6000] + "\n…\n" + blob[-6000:]
        user = (
            f"【既有摘要】\n{(prior_summary or '（无）').strip()}\n\n"
            f"【待压缩对话】\n{blob}\n\n"
            "请输出合并后的完整精简摘要（不要标题）："
        )
        try:
            raw = llm.chat(SUMMARY_SYSTEM, user, temperature=0.0, max_tokens=512, retries=1) or ""
        except Exception:
            return ""
        summary = (raw or "").strip()
        summary = summary.replace("```", "").strip()
        if len(summary) > 800:
            summary = summary[:800].rstrip() + "…"
        return summary

    # ---- 兼容旧测试接口：不再破坏性 rewrite，只返回「全量+新摘要」视图 ----
    def compact(
        self,
        messages: List[TranscriptMessage],
        llm: Optional[LLMClient] = None,
        force_auto: bool = False,
    ) -> Tuple[List[TranscriptMessage], CompactReport]:
        msg, report = self.build_append_compaction(messages, llm=llm, force=force_auto)
        if msg is None:
            return list(messages), report
        return list(messages) + [msg], report
