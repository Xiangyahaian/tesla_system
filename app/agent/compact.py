# -*- coding: utf-8 -*-
"""分层上下文压缩（对齐 Claude Code 五层思路，成本从低到高）。

1) budget_reduction — 截断超长单条（尤其 tool 输出）
2) snip — 丢掉过旧消息，保留最近窗口
3) microcompact — 旧 tool 结果改成短 stub
4) context_collapse — 中间段投影为摘要行（非破坏性视图由 assemble 使用；
   此处对持久 transcript 做轻度折叠）
5) auto_compact — LLM 语义摘要，写入 compaction 消息并裁剪历史
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.agent.types import CompactReport, MessageRole, TranscriptMessage
from app.llm.client import LLMClient


class ContextCompactor:
    def __init__(
        self,
        soft_limit_chars: int = 24_000,
        hard_limit_chars: int = 40_000,
        keep_recent: int = 16,
        tool_max_chars: int = 800,
        max_auto_fail: int = 3,
    ):
        self.soft_limit = soft_limit_chars
        self.hard_limit = hard_limit_chars
        self.keep_recent = keep_recent
        self.tool_max_chars = tool_max_chars
        self.max_auto_fail = max_auto_fail
        self._fail_streak = 0

    def total_chars(self, msgs: List[TranscriptMessage]) -> int:
        return sum(m.approx_chars() for m in msgs)

    def compact(
        self,
        messages: List[TranscriptMessage],
        llm: Optional[LLMClient] = None,
        force_auto: bool = False,
    ) -> Tuple[List[TranscriptMessage], CompactReport]:
        report = CompactReport(before_chars=self.total_chars(messages))
        msgs = list(messages)

        msgs, used = self._budget_reduction(msgs)
        if used:
            report.layers.append("budget_reduction")

        if self.total_chars(msgs) > self.soft_limit or force_auto:
            msgs, used = self._snip(msgs)
            if used:
                report.layers.append("snip")

        if self.total_chars(msgs) > self.soft_limit or force_auto:
            msgs, used = self._microcompact(msgs)
            if used:
                report.layers.append("microcompact")

        if self.total_chars(msgs) > self.soft_limit or force_auto:
            msgs, used = self._context_collapse(msgs)
            if used:
                report.layers.append("context_collapse")

        need_auto = force_auto or self.total_chars(msgs) > self.soft_limit
        if need_auto and llm is not None and self._fail_streak < self.max_auto_fail:
            msgs2, summary, ok = self._auto_compact(msgs, llm)
            if ok:
                msgs = msgs2
                report.layers.append("auto_compact")
                report.summary = summary
                self._fail_streak = 0
            else:
                self._fail_streak += 1
                report.thrash_count = self._fail_streak

        report.after_chars = self.total_chars(msgs)
        return msgs, report

    def _budget_reduction(self, msgs: List[TranscriptMessage]) -> Tuple[List[TranscriptMessage], bool]:
        changed = False
        out = []
        for m in msgs:
            if m.role == MessageRole.TOOL and len(m.content) > self.tool_max_chars:
                out.append(
                    TranscriptMessage(
                        role=m.role,
                        content=m.content[: self.tool_max_chars] + "…[truncated]",
                        ts=m.ts,
                        meta={**m.meta, "truncated": True},
                    )
                )
                changed = True
            elif len(m.content) > 4000:
                out.append(
                    TranscriptMessage(
                        role=m.role,
                        content=m.content[:4000] + "…[truncated]",
                        ts=m.ts,
                        meta={**m.meta, "truncated": True},
                    )
                )
                changed = True
            else:
                out.append(m)
        return out, changed

    def _snip(self, msgs: List[TranscriptMessage]) -> Tuple[List[TranscriptMessage], bool]:
        if len(msgs) <= self.keep_recent + 2:
            return msgs, False
        # 保留最早的 compaction 摘要 + 最近 N 条
        head = [m for m in msgs if m.role == MessageRole.COMPACTION][-1:]
        tail = msgs[-self.keep_recent :]
        # 去重
        ids = set(id(x) for x in head)
        merged = head + [m for m in tail if id(m) not in ids]
        return merged, True

    def _microcompact(self, msgs: List[TranscriptMessage]) -> Tuple[List[TranscriptMessage], bool]:
        if len(msgs) <= self.keep_recent:
            return msgs, False
        cut = len(msgs) - self.keep_recent
        changed = False
        out = []
        for i, m in enumerate(msgs):
            if i < cut and m.role == MessageRole.TOOL:
                tool = m.meta.get("tool", "tool")
                out.append(
                    TranscriptMessage(
                        role=m.role,
                        content=f"[{tool} 结果已折叠]",
                        ts=m.ts,
                        meta={**m.meta, "microcompact": True},
                    )
                )
                changed = True
            else:
                out.append(m)
        return out, changed

    def _context_collapse(self, msgs: List[TranscriptMessage]) -> Tuple[List[TranscriptMessage], bool]:
        if len(msgs) <= self.keep_recent + 4:
            return msgs, False
        head_n = 2
        tail_n = self.keep_recent
        mid = msgs[head_n:-tail_n]
        if not mid:
            return msgs, False
        lines = []
        for m in mid:
            lines.append(f"- {m.role.value}: {m.content[:80]}")
        collapsed = TranscriptMessage(
            role=MessageRole.COMPACTION,
            content="[context_collapse]\n" + "\n".join(lines[:40]),
            ts=mid[-1].ts if mid else 0,
            meta={"layer": "context_collapse"},
        )
        return msgs[:head_n] + [collapsed] + msgs[-tail_n:], True

    def _auto_compact(
        self, msgs: List[TranscriptMessage], llm: LLMClient
    ) -> Tuple[List[TranscriptMessage], str, bool]:
        recent = msgs[-min(len(msgs), 30) :]
        blob = "\n".join(f"{m.role.value}: {m.content[:300]}" for m in recent)
        try:
            summary = llm.chat(
                "你是会话压缩器。把对话压缩成简洁中文摘要，保留："
                "用户偏好、未完成事项、最近车控结果、待确认操作、关键实体。"
                "不超过 250 字，不要废话。",
                blob,
                temperature=0.0,
            )
            summary = (summary or "").strip()
            if not summary:
                return msgs, "", False
        except Exception:
            return msgs, "", False

        keep = msgs[-max(6, self.keep_recent // 2) :]
        compact_msg = TranscriptMessage(
            role=MessageRole.COMPACTION,
            content=summary,
            ts=keep[0].ts if keep else 0,
            meta={"layer": "auto_compact"},
        )
        return [compact_msg] + keep, summary, True
