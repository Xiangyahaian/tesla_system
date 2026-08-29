# -*- coding: utf-8 -*-
"""编排：Agent 运行时 + 车载专用路径。

每轮：
  1) 写入 user transcript
  2) 分层 compact（如需要）
  3) assemble context（人设 / 记忆 / 偏好 / vehicle / recent）
  4) NLU 逐步规划（每步可并行无依赖工具；有依赖则拆步）
  5) tool → AgentLoop（observe 后再规划）；其它路径专用 handler
  6) 写入 assistant/tool transcript + 持久化 session
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Tuple

from app import config
from app.agent.hooks import HookBus
from app.agent.loop import AgentLoop
from app.agent.persona import (
    CHAT_STYLE,
    KNOWLEDGE_EMPTY,
    KNOWLEDGE_STYLE,
    SEARCH_STYLE,
    TOOL_WRAP_STYLE,
)
from app.agent.speech_guard import (
    DEFAULT_SPOKEN,
    classify_and_speak,
    looks_like_raw_error,
    public_error_text,
    sanitize_spoken,
)
from app.agent.trace import StepType, TurnTrace
from app.agent.types import MessageRole
from app.llm.client import LLMClient, classify_llm_error, compose_llm_fail_reply, get_llm
from app.models import IntentType, PendingAction, ProfileUpdatePlan, RouteResult, ToolCall, ToolResult
from app.nlu.fast_path import (
    chat_web_query,
    is_pending_hold_utterance,
    try_app_utterance,
    try_confirm_utterance,
    try_direct_cabin_utterance,
    try_fast_path_route,
    try_greeting_reply,
    try_nearby_utterance,
    try_status_utterance,
    try_web_search_utterance,
)
from app.nlu.nav_resolve import format_clarify_speech, resolve_nav_selection
from app.nlu.planner import StructuredNLU
from app.nlu.seat_context import (
    SEAT_CN,
    apply_active_seat_defaults,
    apply_memory_climate_defaults,
    normalize_active_seat,
)
from app.policy.engine import PolicyEngine
from app.rag.service import RagService, get_rag_service
from app.session.store import SessionData, get_session_store
from app.tools.registry import get_registry

_log = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    type: str
    data: Any = None


@dataclass
class TurnMetrics:
    llm_calls: int = 0
    intent: str = ""
    tools: List[str] = field(default_factory=list)
    compact_layers: List[str] = field(default_factory=list)
    context_chars: int = 0
    loop_iters: int = 0
    turn_id: str = ""
    llm_used: bool = False
    prompt_chars: int = 0
    completion_chars: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_elapsed_ms: int = 0
    token_source: str = "none"
    prompts: List[Dict[str, Any]] = field(default_factory=list)
    llm: Any = field(default=None, repr=False, compare=False)
    profile_plan: ProfileUpdatePlan = field(default_factory=ProfileUpdatePlan)


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _absorb_llm(m: TurnMetrics) -> None:
    llm = m.llm
    extra: List[Dict[str, Any]] = []
    if llm is not None and hasattr(llm, "drain_usage"):
        try:
            extra = list(llm.drain_usage() or [])
        except Exception:
            extra = []
    if extra:
        m.prompts.extend(extra)
    if m.prompts:
        m.llm_used = True
        m.llm_calls = len(m.prompts)
        m.prompt_chars = sum(int(c.get("prompt_chars") or 0) for c in m.prompts)
        m.completion_chars = sum(int(c.get("completion_chars") or 0) for c in m.prompts)
        m.prompt_tokens = sum(int(c.get("prompt_tokens") or 0) for c in m.prompts)
        m.completion_tokens = sum(int(c.get("completion_tokens") or 0) for c in m.prompts)
        m.total_tokens = sum(int(c.get("total_tokens") or 0) for c in m.prompts)
        m.llm_elapsed_ms = sum(int(c.get("elapsed_ms") or 0) for c in m.prompts)
        sources = {str(c.get("token_source") or "none") for c in m.prompts}
        m.token_source = next(iter(sources)) if len(sources) == 1 else "mixed"
        m.context_chars = m.prompt_chars
    else:
        m.llm_used = False
        m.llm_calls = 0
        m.prompt_chars = 0
        m.completion_chars = 0
        m.prompt_tokens = 0
        m.completion_tokens = 0
        m.total_tokens = 0
        m.llm_elapsed_ms = 0
        m.token_source = "none"
        m.context_chars = 0


def _metrics_dict(m: TurnMetrics) -> Dict[str, Any]:
    _absorb_llm(m)
    return {
        "llm_used": m.llm_used,
        "llm_calls": m.llm_calls,
        "loop_iters": m.loop_iters,
        "compact_layers": m.compact_layers,
        "prompt_chars": m.prompt_chars,
        "completion_chars": m.completion_chars,
        "prompt_tokens": m.prompt_tokens,
        "completion_tokens": m.completion_tokens,
        "total_tokens": m.total_tokens,
        "llm_elapsed_ms": m.llm_elapsed_ms,
        "token_source": m.token_source,
        "prompts": m.prompts,
        "context_chars": m.prompt_chars,
        "tools": m.tools,
    }


class Orchestrator:
    def __init__(self):
        self.store = get_session_store()
        self.registry = get_registry()
        self.policy = PolicyEngine(self.registry)
        self.hooks = HookBus()
        self.agent_loop = AgentLoop(
            self.registry, self.policy, max_iterations=config.AGENT_MAX_LOOP_ITERS
        )
        self._rag: Optional[RagService] = None
        self._session_locks: Dict[str, threading.Lock] = {}
        self._session_locks_guard = threading.Lock()

    def _get_session_lock(self, session_id: str) -> threading.Lock:
        key = str(session_id or "default")
        with self._session_locks_guard:
            lock = self._session_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[key] = lock
            return lock

    def _get_rag(self) -> RagService:
        if self._rag is None:
            self._rag = get_rag_service()
        return self._rag

    def finalize_open_turn(self, session_id: str, error: str = "") -> bool:
        """上一轮若只写下用户句就中断，补一条助手说明，避免历史缺回复。"""
        try:
            sess = self.store.get(session_id, touch=False)
        except Exception:
            return False
        msgs = sess.transcript.load()
        if not msgs or msgs[-1].role != MessageRole.USER:
            return False
        raw = (error or "").strip().replace("\n", " ")
        if raw.lower() in {"cancelled", "canceled", "generator exit"}:
            raw = ""
        if raw and "中断" in raw:
            note = "刚才这句我没答完，刷新或下一条会接上。"
        elif raw:
            note = public_error_text(raw)
        else:
            note = "刚才这句我没答完，刷新或下一条会接上。"
        sess.transcript.append(MessageRole.ASSISTANT, sanitize_spoken(f"【听】{note}"))
        self.store.save(sess)
        return True

    def handle(
        self,
        query: str,
        session_id: str = "default",
        model: str = "remote",
        confirm: Optional[bool] = None,
        active_seat: Optional[str] = None,
    ) -> Generator[StreamEvent, None, TurnMetrics]:
        lock = self._get_session_lock(session_id)
        if not lock.acquire(blocking=False):
            metrics = TurnMetrics()
            msg = "【听】上一句还在处理，稍等一下再发就行，不用重置会话。"
            yield StreamEvent("status", "busy")
            yield from self._emit_text(msg)
            yield StreamEvent(
                "final",
                {
                    "busy": True,
                    "cite_pages": [],
                    "related_images": [],
                    "state": {},
                },
            )
            return metrics
        try:
            return (yield from self._handle_locked(query, session_id, model, confirm, active_seat))
        except Exception as e:
            yield from self._emit_uncaught_failure(session_id, e, model)
            return TurnMetrics()
        finally:
            try:
                lock.release()
            except RuntimeError:
                pass

    def _emit_uncaught_failure(self, session_id: str, exc: BaseException, model: str):
        mode = model if model in {"remote", "local"} else "remote"
        info = classify_and_speak(exc, mode=mode)
        msg = info.get("spoken") or DEFAULT_SPOKEN
        _log.exception("uncaught turn failure session=%s", session_id)
        try:
            sess = self.store.get(session_id, touch=False)
            turn = TurnTrace(session_id=session_id, query="", model=model)
            yield from self._trace(turn, StepType.ERROR, "本轮未捕获异常", info, status="error")
            turn.finish(status="error", answer_preview=msg)
            sess.traces.append_turn(turn)
            last = (sess.transcript.load() or [None])[-1]
            if last is not None and last.role == MessageRole.USER:
                sess.transcript.append(MessageRole.ASSISTANT, msg)
            self.store.save(sess)
        except Exception:
            _log.exception("uncaught failure persist failed session=%s", session_id)
        yield from self._emit_text(msg)
        yield StreamEvent(
            "final",
            {"cite_pages": [], "related_images": [], "state": {}, "error": True},
        )

    def _handle_locked(
        self,
        query: str,
        session_id: str = "default",
        model: str = "remote",
        confirm: Optional[bool] = None,
        active_seat: Optional[str] = None,
    ) -> Generator[StreamEvent, None, TurnMetrics]:
        metrics = TurnMetrics()
        sess = self.store.get(session_id)
        self.finalize_open_turn(session_id, "上一轮回答中断了。")
        llm = get_llm(model)
        metrics.llm = llm
        q = (query or "").strip()

        seat, seat_src = sess.memory.resolve_active_seat(active_seat or sess.slots.get("active_seat"), q)
        sess.slots["active_seat"] = seat
        turn = TurnTrace(session_id=session_id, query=q, model=model)
        metrics.turn_id = turn.turn_id

        if str(model or "remote") == "local":
            ping = llm.ping()
            if not ping.get("ok"):
                info = classify_and_speak(str(ping.get("error") or "本地模型未就绪"), mode="local")
                msg = info.get("spoken") or "【听】本地模型这会儿还没就绪。请先在 GPU 电脑启动 vLLM。"
                yield from self._trace(turn, StepType.ERROR, "本地模型不可用", info, status="error")
                yield StreamEvent("status", "本地模型不可用")
                sess.transcript.append(MessageRole.USER, q)
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                yield from self._emit_text(msg)
                yield StreamEvent(
                    "final",
                    {
                        "turn_id": turn.turn_id,
                        "cite_pages": [],
                        "related_images": [],
                        "state": self._state_summary(sess),
                    },
                )
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                return metrics

        yield StreamEvent("status", "Agent 上下文准备中...")
        yield StreamEvent(
            "active_seat",
            {"active_seat": seat, "active_seat_cn": SEAT_CN.get(seat, seat), "source": seat_src},
        )
        yield from self._trace(
            turn,
            StepType.SESSION,
            "加载会话",
            {
                "session_id": session_id,
                "turn_id": turn.turn_id,
                "active_seat": seat,
                "active_seat_cn": SEAT_CN.get(seat, seat),
                "seat_source": seat_src,
            },
        )
        yield from self._emit_text(
            f"> **[{_ts()}] 座舱编排** · turn `{turn.turn_id}` · session `{session_id}`"
            f" · seat `{SEAT_CN.get(seat, seat)}` ({seat_src})\n>\n"
        )

        # 0) pending confirmation
        if sess.pending is not None:
            confirm_route = try_confirm_utterance(q)
            do_confirm = confirm is True or (confirm_route and confirm_route.intent == IntentType.CONFIRM)
            do_cancel = confirm is False or (confirm_route and confirm_route.intent == IntentType.CANCEL)
            if do_confirm:
                pending = sess.pending
                privacy = (getattr(pending, "confirm_kind", None) or "safety") == "privacy"
                # 确认时车况可能已变：重新过策略，不允许就清 pending 并说明
                try:
                    live_state = sess.gateway.snapshot()
                except Exception:
                    live_state = {}
                recheck = self.policy.evaluate(pending.tool_calls, live_state)
                if not recheck.allowed:
                    sess.pending = None
                    sess.transcript.append(MessageRole.USER, q, kind="confirm")
                    msg = f"【听】{recheck.message or recheck.blocked_reason or '当前车况下不能执行刚才那步，先不做了。'}"
                    sess.transcript.append(MessageRole.ASSISTANT, msg)
                    yield from self._trace(
                        turn,
                        StepType.CONFIRM,
                        "确认后策略重检拦截",
                        {
                            "summary": pending.summary,
                            "blocked_reason": recheck.blocked_reason,
                        },
                        status="warn",
                    )
                    yield from self._commit_turn(sess, turn, metrics, "blocked", msg)
                    yield from self._persist_turn(sess, llm, q, metrics, turn)
                    yield from self._emit_text(msg)
                    yield StreamEvent(
                        "final",
                        {
                            "turn_id": turn.turn_id,
                            "blocked": True,
                            "cite_pages": [],
                            "related_images": [],
                            "state": self._state_summary(sess),
                        },
                    )
                    return metrics
                sess.pending = None
                sess.transcript.append(MessageRole.USER, q, kind="confirm")
                yield from self._trace(
                    turn,
                    StepType.CONFIRM,
                    "用户确认读取消息" if privacy else "用户确认高风险操作",
                    {"summary": pending.summary, "confirm_kind": getattr(pending, "confirm_kind", "safety")},
                )
                yield from self._emit_text(
                    f"> **[{_ts()}] {'用户已确认读取消息' if privacy else '用户已确认高风险操作'}**\n>\n"
                    f"> 待执行: `{pending.summary}`\n\n---\n\n"
                )
                results = self._exec_tools(sess, pending.tool_calls)
                message_contexts: List[Dict[str, Any]] = []
                for call, result in zip(pending.tool_calls, results):
                    sess.transcript.append(
                        MessageRole.TOOL,
                        result.message,
                        tool=call.name,
                        success=result.success,
                    )
                    detail: Dict[str, Any] = {
                        "arguments": call.arguments,
                        "result": result.message,
                        "success": result.success,
                        "tool": call.name,
                    }
                    if call.name == "maps.search_nearby" and isinstance(result.data, dict):
                        pois = result.data.get("pois") or []
                        detail["source"] = result.data.get("source") or result.data.get("provider")
                        detail["tool_api"] = result.data.get("tool") or "maps_around_search"
                        detail["count"] = result.data.get("count", len(pois))
                        detail["pois"] = [
                            {
                                "name": p.get("name"),
                                "address": p.get("address"),
                                "distance": p.get("distance"),
                            }
                            for p in pois
                            if isinstance(p, dict)
                        ]
                        detail["result"] = (
                            f"高德检索完成，命中 {len(pois)} 家；口语仅推荐其中部分。"
                            if pois
                            else result.message
                        )
                    if call.name == "notifications.list_messages" and isinstance(result.data, dict):
                        cards, msg_detail = self._message_evidence(result.data)
                        detail.update(msg_detail)
                        message_contexts.extend(cards)
                    yield from self._trace(
                        turn,
                        StepType.TOOL,
                        f"执行 {call.name}",
                        detail,
                        status="ok" if result.success else "error",
                    )
                    # 过程/依据面板用 trace；工具原文绝不进对话流
                    if call.name in {
                        "notifications.list_messages",
                        "maps.search_nearby",
                        "navigation.navigate_to",
                        "navigation.start",
                    }:
                        continue
                    # 多行结果每一行都加 >，避免漏进对话框
                    dump = (result.message or "").strip() or "(无输出)"
                    if looks_like_raw_error(dump):
                        dump = "执行失败（原文已写入轨迹）"
                    for line in dump.splitlines() or ["(无输出)"]:
                        yield from self._emit_text(f"> `{call.name}` → {line}\n")
                if message_contexts:
                    yield StreamEvent("context", message_contexts)
                    yield from self._trace(
                        turn,
                        StepType.TOOL,
                        f"读入消息依据 {len(message_contexts)} 条",
                        {"doc_count": len(message_contexts), "kind": "message"},
                    )
                raw_msg = self._format_tool_results(results)
                msg = self._warm_tool_reply(llm, q, raw_msg, results=results, sess=sess)
                metrics.llm_calls += 1
                tool_names = [c.name for c in pending.tool_calls]
                self._sync_unread_nudge_after_notifications(sess, tool_names, results)
                skip_nudge = self._should_skip_unread_nudge(q, tool_names)
                msg, nudged = self._apply_unread_visual_nudge(sess, msg, skip=skip_nudge)
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                metrics.intent = "tool"
                metrics.tools = tool_names
                yield from self._commit_turn(sess, turn, metrics, "ok", msg)
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                yield from self._emit_text("\n" + msg)
                nudge = self._unread_nudge_payload(sess, nudged)
                yield StreamEvent(
                    "final",
                    {
                        "turn_id": turn.turn_id,
                        "tool_results": [r.model_dump() for r in results],
                        "cite_pages": [],
                        "related_images": [],
                        "contexts": message_contexts,
                        "state": self._state_summary(sess),
                        **({"visual_nudge": nudge} if nudge else {}),
                    },
                )
                return metrics
            if do_cancel:
                pending = sess.pending
                privacy = pending is not None and (getattr(pending, "confirm_kind", None) or "") == "privacy"
                sess.pending = None
                sess.transcript.append(MessageRole.USER, q, kind="cancel")
                msg = (
                    "好，那先不看消息了。"
                    if privacy
                    else "好，先不动。"
                )
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                yield from self._trace(
                    turn,
                    StepType.CONFIRM,
                    "用户取消读取消息" if privacy else "用户取消操作",
                    {"confirm_kind": "privacy" if privacy else "safety"},
                )
                yield from self._commit_turn(sess, turn, metrics, "cancelled", msg)
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                yield from self._emit_text(msg)
                yield StreamEvent(
                    "final",
                    {
                        "turn_id": turn.turn_id,
                        "cancelled": True,
                        "cite_pages": [],
                        "related_images": [],
                        "state": self._state_summary(sess),
                    },
                )
                return metrics
            # 短糊糊话：保留 pending，提示用户确认/取消
            if is_pending_hold_utterance(q):
                pending = sess.pending
                privacy = (getattr(pending, "confirm_kind", None) or "safety") == "privacy"
                sess.transcript.append(MessageRole.USER, q, kind="confirm_hold")
                tip = pending.message or (
                    "要不要我读一下消息？说「确认」或「取消」。"
                    if privacy
                    else "刚才那步需要你确认后才能动。可以说「确认」或「取消」。"
                )
                msg = f"【听】{tip}"
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                yield from self._trace(
                    turn,
                    StepType.CONFIRM,
                    "保留待确认动作",
                    {"summary": pending.summary, "confirm_kind": getattr(pending, "confirm_kind", "safety")},
                )
                yield from self._commit_turn(sess, turn, metrics, "await_confirm", msg)
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                yield from self._emit_text(msg)
                yield StreamEvent(
                    "final",
                    {
                        "turn_id": turn.turn_id,
                        "await_confirm": True,
                        "cite_pages": [],
                        "related_images": [],
                        "state": self._state_summary(sess),
                    },
                )
                return metrics
            # 明确新指令：覆盖 pending，并口语告知，避免「以为还在等确认」
            override_note = "刚才那步先不算了，按你这句新的来。"
            sess.pending = None
            yield from self._trace(turn, StepType.CONFIRM, "新指令覆盖未确认动作", status="warn")
            yield from self._emit_text(
                f"> **[{_ts()}] 新指令覆盖未确认动作**\n>\n> {override_note}\n\n---\n\n"
            )
            sess.slots["_pending_override_note"] = override_note

        # 1) append user turn
        sess.transcript.append(MessageRole.USER, q)

        greet = try_greeting_reply(q)
        if greet:
            metrics.intent = "chat"
            greet = self._with_continuity_prefix(sess, greet)
            sess.transcript.append(MessageRole.ASSISTANT, greet)
            yield from self._trace(turn, StepType.CHAT, "寒暄直达")
            yield from self._emit_text(greet)
            yield from self._commit_turn(sess, turn, metrics, "ok", greet)
            yield from self._persist_turn(sess, llm, q, metrics, turn)
            yield StreamEvent(
                "final",
                {
                    "turn_id": turn.turn_id,
                    "cite_pages": [],
                    "related_images": [],
                    "state": self._state_summary(sess),
                    "active_seat": seat,
                },
            )
            return metrics

        # 2) compact if needed
        report = self.store.maybe_compact(sess, llm=llm, force=False)
        if report and report.layers:
            metrics.compact_layers = list(report.layers)
            yield from self._trace(
                turn,
                StepType.COMPACT,
                "上下文压缩",
                {
                    "layers": report.layers,
                    "before_chars": report.before_chars,
                    "after_chars": report.after_chars,
                    "summary": report.summary[:200] if report.summary else "",
                },
            )
            yield from self._emit_text(
                f"> **[{_ts()}] Context Compact**: {', '.join(report.layers)} "
                f"({report.before_chars}→{report.after_chars} chars)\n\n---\n\n"
            )
            if "auto_compact" in report.layers:
                metrics.llm_calls += 1

        # 3) assemble context
        bundle = self.store.assemble_context(sess)
        yield from self._trace(
            turn,
            StepType.CONTEXT,
            "上下文组装",
            {"sources": bundle.sources, "chars": bundle.total_chars},
        )
        yield from self._emit_text(
            f"> **[{_ts()}] Context Assembly** sources={bundle.sources} "
            f"chars≈{bundle.total_chars}\n\n---\n\n"
        )

        # 4) NLU（无歧义舱体/周边/偏好/一句话多工具可直达）
        memory_hint = self.store.assembler.memory_hint(bundle, sess.transcript)

        # 系统性门禁：有待澄清导航候选时，只在候选集合内解释用户话，
        # 禁止 NLU 改写成新地名再全市检索（否则会二次歧义）。
        pending_nav = [
            c
            for c in (sess.slots.get("nav_candidates") or [])
            if isinstance(c, dict) and str(c.get("name") or "").strip()
        ]
        if pending_nav:
            sel = resolve_nav_selection(
                q,
                pending_nav,
                llm=llm,
                query_label=str(sess.slots.get("nav_clarify_query") or ""),
            )
            if sel.used_llm:
                metrics.llm_calls += 1
            if sel.action == "navigate":
                args: Dict[str, Any] = {
                    "destination": sel.destination,
                    "preference": "fastest",
                }
                loc = (sel.location or "").strip()
                if loc and "," in loc:
                    args["destination_location"] = loc
                direct = RouteResult(
                    intent=IntentType.TOOL,
                    confidence=0.99,
                    reason=f"选择导航候选·{sel.reason}",
                    tool_calls=[
                        ToolCall(
                            name="navigation.navigate_to",
                            arguments=args,
                            reason=f"用户选定：{sel.destination}",
                        )
                    ],
                    done=True,
                )
                yield from self._emit_text(f"> **[{_ts()}] FastPath**: 导航候选选定（跳过 NLU）\n>\n")
                metrics.intent = direct.intent.value
                metrics.tools = [c.name for c in direct.tool_calls]
                yield from self._trace(
                    turn,
                    StepType.INTENT,
                    "选择导航候选",
                    {
                        "intent": direct.intent.value,
                        "confidence": direct.confidence,
                        "reason": direct.reason,
                        "selection_reason": sel.reason,
                        "used_llm": sel.used_llm,
                        "tool_calls": [c.model_dump() for c in direct.tool_calls],
                    },
                )
                yield StreamEvent(
                    "intent",
                    {
                        "turn_id": turn.turn_id,
                        "type": direct.intent.value,
                        "confidence": direct.confidence,
                        "reason": direct.reason,
                        "active_seat": seat,
                        "tool_calls": [c.model_dump() for c in direct.tool_calls],
                    },
                )
                yield from self._handle_tools(
                    sess, q, direct, llm, memory_hint, metrics, turn, active_seat=seat
                )
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                return metrics

            if sel.action in {"narrow", "repeat"}:
                use_cands = sel.candidates or pending_nav
                if sel.action == "narrow":
                    sess.slots["nav_candidates"] = use_cands
                label = str(sess.slots.get("nav_clarify_query") or "那里")
                msg = f"【听】{format_clarify_speech(label, use_cands)}"
                metrics.intent = "tool"
                yield from self._trace(
                    turn,
                    StepType.INTENT,
                    "导航候选仍需澄清",
                    {
                        "action": sel.action,
                        "reason": sel.reason,
                        "used_llm": sel.used_llm,
                        "candidates": [
                            {"name": c.get("name"), "index": c.get("index")} for c in use_cands
                        ],
                    },
                )
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                yield from self._emit_text(msg)
                yield from self._commit_turn(sess, turn, metrics, "ok", msg)
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                yield StreamEvent(
                    "final",
                    {
                        "turn_id": turn.turn_id,
                        "cite_pages": [],
                        "related_images": [],
                        "state": self._state_summary(sess),
                        "active_seat": seat,
                    },
                )
                return metrics

            if sel.action == "clear":
                sess.slots.pop("nav_candidates", None)
                sess.slots.pop("nav_clarify_query", None)
            elif sel.action == "new_destination":
                # 明确换目的地：清掉旧候选，走正常导航规划
                sess.slots.pop("nav_candidates", None)
                sess.slots.pop("nav_clarify_query", None)

        direct = try_fast_path_route(q, sess.slots.get("nav_candidates"))

        if direct is not None:
            route = direct
            self._capture_profile_plan(metrics, route)
            metrics.intent = route.intent.value
            metrics.tools = [c.name for c in route.tool_calls]
            if route.intent == IntentType.SEARCH:
                fast_tag = "status"
            elif any(c.name.startswith("maps.") for c in route.tool_calls):
                fast_tag = "nearby"
            elif any(c.name.startswith("web.") for c in route.tool_calls):
                fast_tag = "web"
            elif any(c.name.startswith("navigation.") for c in route.tool_calls):
                fast_tag = "combo" if len(route.tool_calls) > 1 else "nav"
            else:
                fast_tag = "cabin"
            yield from self._trace(
                turn,
                StepType.INTENT,
                f"意图 {route.intent.value}",
                {
                    "intent": route.intent.value,
                    "confidence": route.confidence,
                    "reason": route.reason,
                    "active_seat": seat,
                    "tool_calls": [c.model_dump() for c in route.tool_calls],
                    "fast_path": fast_tag,
                    "profile_update": route.profile_update.model_dump(),
                },
            )
            yield from self._emit_text(
                f"> **[{_ts()}] 意图**: `{route.intent.value}` "
                f"(直达 {route.confidence:.2f}) · {route.reason}\n\n---\n\n"
            )
            yield StreamEvent(
                "intent",
                {
                    "turn_id": turn.turn_id,
                    "type": route.intent.value,
                    "confidence": route.confidence,
                    "reason": route.reason,
                    "active_seat": seat,
                    "tool_calls": [c.model_dump() for c in route.tool_calls],
                    "context_sources": bundle.sources,
                    "compact_layers": metrics.compact_layers,
                },
            )
            # 车况直达（在哪/空调开没开等）没有 tool_calls，必须走 SEARCH；
            # 不能当成「空工具 = 记偏好」，否则会回「偏好已记下来…再说空调」。
            if route.intent == IntentType.SEARCH:
                yield from self._handle_search(sess, q, llm, metrics, bundle, turn, active_seat=seat)
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                return metrics
            if route.intent == IntentType.KNOWLEDGE:
                yield from self._handle_knowledge(sess, q, llm, metrics, turn)
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                return metrics
            if route.intent == IntentType.CHAT:
                yield from self._handle_chat(sess, q, llm, metrics, bundle, turn)
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                return metrics
            if route.tool_calls:
                yield from self._handle_tools(sess, q, route, llm, memory_hint, metrics, turn, active_seat=seat)
            yield from self._persist_turn(sess, llm, q, metrics, turn)
            return metrics

        yield from self._emit_text(f"> **[{_ts()}] StructuredNLU（语义规划）...**\n>\n")
        yield StreamEvent("status", "规划中...")
        nlu = StructuredNLU(llm, self.registry)
        route = nlu.plan(q, sess.gateway.snapshot(), memory_hint, active_seat=seat)
        self._capture_profile_plan(metrics, route)
        metrics.llm_calls += 1
        metrics.intent = route.intent.value
        metrics.tools = [c.name for c in route.tool_calls]
        yield from self._trace(
            turn,
            StepType.INTENT,
            f"意图 {route.intent.value}",
            {
                "intent": route.intent.value,
                "confidence": route.confidence,
                "reason": route.reason,
                "active_seat": seat,
                "tool_calls": [c.model_dump() for c in route.tool_calls],
                "profile_update": route.profile_update.model_dump(),
            },
        )
        # NLU 断连/低置信闲聊：先试直达指令，避免闲聊瞎编「导航已启动」
        if route.intent == IntentType.CHAT and (
            str(route.reason).startswith("NLU失败") or route.confidence < 0.35
        ):
            from app.nlu.destination_guard import should_skip_code_fast_path

            recovery = None
            if not should_skip_code_fast_path(q):
                recovery = (
                    try_app_utterance(q)
                    or try_nearby_utterance(q)
                    or try_web_search_utterance(q)
                    or try_status_utterance(q)
                    or try_direct_cabin_utterance(q)
                )
            if recovery is not None:
                route = recovery
                metrics.intent = route.intent.value
                metrics.tools = [c.name for c in route.tool_calls]
                yield from self._trace(
                    turn,
                    StepType.INTENT,
                    f"断连恢复 {route.intent.value}",
                    {
                        "intent": route.intent.value,
                        "confidence": route.confidence,
                        "reason": route.reason,
                        "tool_calls": [c.model_dump() for c in route.tool_calls],
                    },
                )
            elif str(route.reason).startswith("NLU失败"):
                info = classify_llm_error(str(route.reason), mode=getattr(llm, "mode", "remote"))
                yield from self._trace(turn, StepType.ERROR, "意图规划失败", info, status="error")
                msg = compose_llm_fail_reply(info)
                metrics.intent = "chat"
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                yield from self._emit_text(msg)
                yield from self._commit_turn(sess, turn, metrics, "error", msg)
                yield from self._persist_turn(sess, llm, q, metrics, turn)
                yield StreamEvent(
                    "final",
                    {
                        "turn_id": turn.turn_id,
                        "cite_pages": [],
                        "related_images": [],
                        "state": self._state_summary(sess),
                        "active_seat": seat,
                    },
                )
                return metrics

        reason_shown = route.reason
        if looks_like_raw_error(reason_shown):
            reason_shown = reason_shown.split("|", 1)[0].strip() or "规划失败"
        yield from self._emit_text(
            f"> **[{_ts()}] 意图**: `{route.intent.value}` "
            f"(置信度 {route.confidence:.2f}) · {reason_shown}\n\n---\n\n"
        )
        yield StreamEvent(
            "intent",
            {
                "turn_id": turn.turn_id,
                "type": route.intent.value,
                "confidence": route.confidence,
                "reason": route.reason,
                "active_seat": seat,
                "tool_calls": [c.model_dump() for c in route.tool_calls],
                "context_sources": bundle.sources,
                "compact_layers": metrics.compact_layers,
            },
        )

        if route.intent in {IntentType.TOOL, IntentType.MULTI_TOOL}:
            yield from self._handle_tools(sess, q, route, llm, memory_hint, metrics, turn, active_seat=seat)
            yield from self._persist_turn(sess, llm, q, metrics, turn)
            return metrics

        if route.intent == IntentType.SEARCH:
            yield from self._handle_search(sess, q, llm, metrics, bundle, turn, active_seat=seat)
            yield from self._persist_turn(sess, llm, q, metrics, turn)
            return metrics

        if route.intent == IntentType.KNOWLEDGE:
            yield from self._handle_knowledge(sess, q, llm, metrics, turn)
            yield from self._persist_turn(sess, llm, q, metrics, turn)
            return metrics

        yield from self._handle_chat(sess, q, llm, metrics, bundle, turn)
        return metrics

    def _trace(
        self,
        turn: TurnTrace,
        step_type: StepType,
        title: str,
        detail: Optional[Dict[str, Any]] = None,
        status: str = "ok",
    ):
        step = turn.add(step_type, title, detail, status)
        yield StreamEvent("trace", step.model_dump())

    def _commit_turn(
        self,
        sess: SessionData,
        turn: TurnTrace,
        metrics: TurnMetrics,
        status: str,
        answer: str = "",
    ):
        turn.finish(
            status=status,
            intent=metrics.intent,
            metrics=_metrics_dict(metrics),
            answer_preview=sanitize_spoken(answer) if looks_like_raw_error(answer) else answer,
            tool_names=list(metrics.tools),
        )
        sess.traces.append_turn(turn)
        yield StreamEvent("turn", turn.summary())

    def _capture_profile_plan(self, metrics: TurnMetrics, route: RouteResult) -> None:
        metrics.profile_plan = route.profile_update

    def _persist_turn(
        self,
        sess: SessionData,
        llm: Optional[LLMClient],
        query: str,
        metrics: TurnMetrics,
        turn: Optional[TurnTrace] = None,
    ):
        """轮末：主干已结束；仅当首轮意图判定需更新时，加载现有记录并调 LLM 合并落盘。"""
        if llm and (query or "").strip() and config.AGENT_ENABLE_AUTO_MEMORY:
            assistant = ""
            try:
                for m in reversed(sess.transcript.load()):
                    if m.role == MessageRole.ASSISTANT:
                        assistant = re.sub(r"^【听】\s*", "", (m.content or "").strip())
                        break
                if not assistant:
                    for m in reversed(sess.transcript.load()):
                        if m.role == MessageRole.TOOL:
                            assistant = (m.content or "")[:400]
                            break
                from app.agent.profile_extract import profile_step_title

                report = sess.memory.extract_after_turn(
                    llm, query, assistant, profile_plan=metrics.profile_plan
                )
                metrics.llm_calls += report.llm_calls
                detail = {
                    "source": "intent_first_pass",
                    "intent_decision": report.intent_decision,
                    "persona_updated": report.persona_updated,
                    "memories_updated": report.memories_updated,
                    "preferences_updated": report.preferences_updated,
                    "notes": report.notes,
                    "update_steps": report.update_steps,
                }
                if report.persona_updated or report.memories_updated or report.preferences_updated:
                    if turn is not None:
                        turn.add(
                            StepType.MEMORY,
                            profile_step_title(
                                report.persona_updated,
                                report.memories_updated,
                                report.preferences_updated,
                            ),
                            detail,
                        )
                    yield StreamEvent(
                        "profile",
                        {
                            **detail,
                            "persona": sess.memory.load_persona(),
                            "memories": sess.memory.load_memories(),
                            "preferences": sess.memory.load_preferences(),
                        },
                    )
                elif report.intent_decision.get("source") and turn is not None:
                    if metrics.profile_plan.needs_work():
                        turn.add(
                            StepType.MEMORY,
                            profile_step_title(skipped=True),
                            detail,
                            status="warn",
                        )
                    # 首轮未触发：不写入轨迹，避免噪声步骤
            except Exception as e:
                _log.warning("profile extract failed session=%s query=%s: %s", sess.session_id, query[:80], e)
                if turn is not None:
                    from app.agent.profile_extract import profile_step_title

                    turn.add(
                        StepType.MEMORY,
                        profile_step_title(failed=True),
                        {"error": str(e)},
                        status="error",
                    )
        self.store.save(sess)

    def _handle_tools(
        self,
        sess: SessionData,
        query: str,
        route: RouteResult,
        llm: LLMClient,
        memory_hint: str,
        metrics: TurnMetrics,
        turn: TurnTrace,
        active_seat: str = "front_left",
    ):
        self._capture_profile_plan(metrics, route)
        yield from self._emit_text(f"> **[{_ts()}] Agent Loop（逐步规划 · 观察后再决策）...**\n\n---\n\n")
        yield from self._trace(turn, StepType.LOOP, "进入 Agent Loop", {"active_seat": active_seat})

        def _exec(call: ToolCall) -> ToolResult:
            filled = apply_active_seat_defaults([call], active_seat)[0]
            block = self.hooks.run_pre(filled, sess.gateway.snapshot())
            if block:
                return ToolResult(success=False, message=block, tool=filled.name)
            result = self.registry.execute(sess.gateway, filled)
            call.arguments = filled.arguments
            self.hooks.run_post(filled, result, sess.gateway.snapshot())
            return result

        # 进入 loop 前：按记忆补齐空调温度
        route.tool_calls = apply_memory_climate_defaults(
            apply_active_seat_defaults(list(route.tool_calls), active_seat),
            active_seat,
            sess.memory.preferred_temp_for(active_seat),
        )
        metrics.tools = [c.name for c in route.tool_calls]

        gen = self.agent_loop.run_tools(
            query=query,
            llm=llm,
            gateway=sess.gateway,
            vehicle_state=sess.gateway.snapshot(),
            memory_hint=memory_hint,
            initial_route=route,
            execute=_exec,
            on_persist_pending=lambda p: setattr(sess, "pending", p),
            active_seat=active_seat,
        )
        loop_result = None
        try:
            while True:
                ev = next(gen)
                if ev.type == "log":
                    yield from self._trace(turn, StepType.LOOP, str(ev.data))
                    log_line = str(ev.data or "")
                    if looks_like_raw_error(log_line):
                        log_line = "warn: 本步有异常，已记下，继续用上一帧车况"
                    yield from self._emit_text(f"> {log_line}\n")
                elif ev.type == "blocked":
                    msg = (ev.data or {}).get("message") or (ev.data or {}).get("blocked_reason") or "已拦截"
                    sess.transcript.append(MessageRole.ASSISTANT, msg)
                    yield from self._trace(turn, StepType.POLICY, "策略拦截", ev.data or {}, status="error")
                    yield from self._commit_turn(sess, turn, metrics, "blocked", msg)
                    yield from self._emit_text(msg)
                    yield StreamEvent(
                        "final",
                        {
                            "turn_id": turn.turn_id,
                            "blocked": True,
                            "policy": ev.data,
                            "cite_pages": [],
                            "related_images": [],
                            "state": self._state_summary(sess),
                        },
                    )
                    return
                elif ev.type == "confirm":
                    data = ev.data or {}
                    privacy = (data.get("confirm_kind") or "safety") == "privacy"
                    # 不弹窗：确认走座舱对话（文本/语音）
                    yield StreamEvent("confirm", {**data, "ui": "chat"})
                    if privacy:
                        # 用户已经在问消息了，只口头确认，不要说明书腔
                        text = "好，读消息前跟你确认一下——要我现在帮你看吗？"
                    else:
                        reason = (data.get("message") or "").strip()
                        # 去掉策略里堆砌的说明书句，只留一句人话
                        if "；" in reason:
                            reason = reason.split("；")[0].strip()
                        if reason and len(reason) < 40 and "确认" not in reason:
                            text = f"{reason}。要继续的话跟我说一声。"
                        else:
                            text = "这个我先跟你确认一下再动，要继续吗？"
                    sess.transcript.append(MessageRole.ASSISTANT, text)
                    yield from self._trace(
                        turn,
                        StepType.CONFIRM,
                        "等待口头确认",
                        {**data, "ui": "chat"},
                        status="warn",
                    )
                    yield from self._commit_turn(sess, turn, metrics, "need_confirm", text)
                    yield from self._emit_text(text)
                    yield StreamEvent(
                        "final",
                        {
                            "turn_id": turn.turn_id,
                            "need_confirm": True,
                            "cite_pages": [],
                            "related_images": [],
                            "state": self._state_summary(sess),
                        },
                    )
                    return
                elif ev.type == "final_tools":
                    pass
        except StopIteration as e:
            loop_result = e.value

        if loop_result is None:
            yield from self._trace(turn, StepType.ERROR, "工具循环异常结束", status="error")
            loop_fail = "【听】车上这步没走完。稍后再试一次，不用重置会话。"
            yield from self._commit_turn(sess, turn, metrics, "error", loop_fail)
            yield from self._emit_text(loop_fail)
            yield StreamEvent(
                "final",
                {"turn_id": turn.turn_id, "cite_pages": [], "related_images": [], "state": self._state_summary(sess)},
            )
            return

        metrics.llm_calls += loop_result.llm_calls
        metrics.loop_iters = loop_result.iterations
        metrics.profile_plan = loop_result.profile_update
        if loop_result.route:
            metrics.intent = loop_result.route.intent.value
        if loop_result.call_trace:
            metrics.tools = [c.name for c, _ in loop_result.call_trace]
        elif loop_result.route:
            metrics.tools = [c.name for c in loop_result.route.tool_calls]

        if loop_result.pending:
            return

        if loop_result.blocked_message:
            sess.transcript.append(MessageRole.ASSISTANT, loop_result.blocked_message)
            yield from self._commit_turn(sess, turn, metrics, "blocked", loop_result.blocked_message)
            yield from self._emit_text(loop_result.blocked_message)
            yield StreamEvent(
                "final",
                {
                    "turn_id": turn.turn_id,
                    "blocked": True,
                    "cite_pages": [],
                    "related_images": [],
                    "state": self._state_summary(sess),
                },
            )
            return

        results = loop_result.results
        pairs = list(loop_result.call_trace) if loop_result.call_trace else []
        if not pairs and loop_result.route:
            calls = loop_result.route.tool_calls[: len(results)]
            pairs = list(zip(calls, results))
        for call, result in pairs:
            sess.transcript.append(
                MessageRole.TOOL,
                result.message,
                tool=call.name,
                arguments=call.arguments,
                success=result.success,
            )
            detail: Dict[str, Any] = {
                "tool": call.name,
                "arguments": call.arguments,
                "result": result.message,
                "success": result.success,
            }
            # 周边检索：完整 POI 进过程面板；口语结果文案保持短候选
            if call.name == "maps.search_nearby" and isinstance(result.data, dict):
                pois = result.data.get("pois") or []
                detail["source"] = result.data.get("source") or result.data.get("provider")
                detail["tool_api"] = result.data.get("tool") or "maps_around_search"
                detail["count"] = result.data.get("count", len(pois))
                detail["pois"] = [
                    {
                        "name": p.get("name"),
                        "address": p.get("address"),
                        "distance": p.get("distance"),
                    }
                    for p in pois
                    if isinstance(p, dict)
                ]
                detail["result"] = (
                    f"高德检索完成，命中 {len(pois)} 家；口语仅推荐其中部分。"
                    if pois
                    else result.message
                )
                # 统一候选池：周边结果可供「第几个」导航
                if result.success and pois:
                    cands = []
                    for i, p in enumerate(pois[:8], 1):
                        if not isinstance(p, dict):
                            continue
                        cands.append(
                            {
                                "index": i,
                                "name": p.get("name"),
                                "address": (p.get("address") or "").strip(),
                                "location": p.get("location"),
                                "distance": p.get("distance"),
                                "source": "nearby",
                            }
                        )
                    if cands:
                        sess.slots["nav_candidates"] = cands
                        sess.slots["nav_clarify_query"] = call.arguments.get("keywords") or "周边地点"
            if call.name == "notifications.list_messages" and isinstance(result.data, dict):
                _cards, msg_detail = self._message_evidence(result.data)
                detail.update(msg_detail)
            if call.name in {"navigation.navigate_to", "navigation.start"} and isinstance(result.data, dict):
                if result.data.get("need_clarify"):
                    cands = result.data.get("candidates") or []
                    detail["need_clarify"] = True
                    detail["candidates"] = cands
                    detail["result"] = f"目的地不明确，待用户从 {len(cands)} 处中选择"
                    # 仅当没有更高优先级的 nearby 候选时，才用全市歧义列表
                    if not any(
                        isinstance(c, dict) and c.get("source") == "nearby"
                        for c in (sess.slots.get("nav_candidates") or [])
                    ):
                        sess.slots["nav_candidates"] = cands
                        sess.slots["nav_clarify_query"] = result.data.get("query")
                elif result.success:
                    sess.slots.pop("nav_candidates", None)
                    sess.slots.pop("nav_clarify_query", None)
            yield from self._trace(
                turn,
                StepType.TOOL,
                f"{call.name}",
                detail,
                status="ok" if result.success else "error",
            )
            if call.name.startswith("climate"):
                sess.slots["last_climate_zones"] = call.arguments.get("zones")
            if call.name == "media.play_music":
                sess.slots["last_music"] = call.arguments
            if call.name == "navigation.navigate_to":
                sess.slots["last_destination"] = call.arguments.get("destination")
            if call.name.startswith("seat"):
                sess.slots["last_seat"] = call.arguments

        # 周边 POI / 消息正文 →「依据」面板；口语另组织
        poi_cards = self._nearby_context_cards(results)
        message_cards = self._message_context_cards(results)
        web_cards = self._web_search_context_cards(results)
        evidence_cards = [*poi_cards, *message_cards, *web_cards]
        if poi_cards:
            yield StreamEvent("context", poi_cards)
            yield from self._trace(
                turn,
                StepType.TOOL,
                f"读入周边依据 {len(poi_cards)} 条",
                {"doc_count": len(poi_cards), "kind": "amap_poi"},
            )
        if message_cards:
            yield StreamEvent("context", message_cards)
            yield from self._trace(
                turn,
                StepType.TOOL,
                f"读入消息依据 {len(message_cards)} 条",
                {"doc_count": len(message_cards), "kind": "message"},
            )
        if web_cards:
            yield StreamEvent("context", web_cards)
            yield from self._trace(
                turn,
                StepType.TOOL,
                f"读入网页依据 {len(web_cards)} 条",
                {"doc_count": len(web_cards), "kind": "web"},
            )

        msg_raw = self._format_tool_results(results)
        detail = "；".join(
            f"{r.message} (`{c.name}` {json.dumps(c.arguments, ensure_ascii=False)})"
            for c, r in pairs
        )
        msg = self._warm_tool_reply(llm, query, msg_raw, results=results, sess=sess)
        metrics.llm_calls += 1

        # 工具阶段后的 residual（如同一句里的影讯/闲聊/手册）
        residual = loop_result.residual_route
        if residual and residual.intent == IntentType.KNOWLEDGE:
            yield from self._handle_knowledge(sess, query, llm, metrics, turn)
            return
        if residual and residual.intent == IntentType.SEARCH:
            bundle = self.store.assemble_context(sess)
            yield from self._handle_search(sess, query, llm, metrics, bundle, turn, active_seat=active_seat)
            return
        if residual and residual.intent == IntentType.CHAT:
            # 把工具结果与闲聊合并：先工具口语，再补非工具部分
            try:
                from app.agent.persona import CHAT_STYLE

                extra = llm.chat(
                    CHAT_STYLE,
                    f"用户原话里除车控/地图外还有闲聊或影讯等问题。工具侧已处理："
                    f"{msg}\n请只回答非工具部分（如电影推荐），不要重复导航/控车结果。用户原话：{query}",
                    temperature=0.5,
                )
                extra = (extra or "").strip()
                if extra:
                    msg = f"{msg}\n\n{extra}"
                    metrics.llm_calls += 1
            except Exception:
                pass

        tool_names = [c.name for c, _ in pairs]
        self._sync_unread_nudge_after_notifications(sess, tool_names, results)
        skip_nudge = self._should_skip_unread_nudge(query, tool_names)
        msg, nudged = self._apply_unread_visual_nudge(sess, msg, skip=skip_nudge)

        sess.transcript.append(MessageRole.ASSISTANT, msg)
        yield from self._trace(turn, StepType.RESPONSE, "工具执行完成", {"answer": msg[:200], "raw": detail or msg_raw})
        yield from self._commit_turn(sess, turn, metrics, "ok", msg)
        yield from self._emit_text("\n---\n\n" + msg)

        calls = [c for c, _ in pairs]
        if len(calls) == 1:
            c0 = calls[0]
            tool_payload: Dict[str, Any] = {
                "skill": c0.name.split(".")[0] if "." in c0.name else c0.name,
                "script": c0.name.split(".")[-1],
                "parameters": c0.arguments,
            }
        else:
            tool_payload = {
                "task_count": len(calls),
                "tasks": [{"skill": c.name, "script": c.name, "parameters": c.arguments} for c in calls],
            }

        nudge = self._unread_nudge_payload(sess, nudged)
        yield StreamEvent(
            "final",
            {
                "turn_id": turn.turn_id,
                "tool_result": tool_payload,
                "tool_results": [r.model_dump() for r in results],
                "cite_pages": [],
                "related_images": [],
                "contexts": evidence_cards,
                "state": self._state_summary(sess),
                "metrics": _metrics_dict(metrics),
                **({"visual_nudge": nudge} if nudge else {}),
            },
        )

    def _exec_tools(self, sess: SessionData, calls: List[ToolCall]) -> List[ToolResult]:
        out = []
        for call in calls:
            block = self.hooks.run_pre(call, sess.gateway.snapshot())
            if block:
                out.append(ToolResult(success=False, message=block, tool=call.name))
                continue
            result = self.registry.execute(sess.gateway, call)
            self.hooks.run_post(call, result, sess.gateway.snapshot())
            out.append(result)
        return out

    def _format_tool_results(self, results: List[ToolResult]) -> str:
        parts = []
        for r in results:
            msg = (r.message or "").strip()
            if not r.success and looks_like_raw_error(msg):
                msg = "这步没做成"
            parts.append(msg if r.success else f"失败：{msg}")
        return "；".join(parts) if parts else "已处理完成。"

    @staticmethod
    def _poi_recommend_count(query: str, available: int) -> int:
        """默认荐 3 家；用户说了几家则按其数量（上限 available）。"""
        q = (query or "").strip()
        n = 3
        m = re.search(r"(\d+)\s*家", q)
        if m:
            n = int(m.group(1))
        else:
            cn = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}
            m2 = re.search(r"([一二两三四五六七八])\s*家", q)
            if m2:
                n = cn.get(m2.group(1), 3)
        if available > 0:
            return max(1, min(n, available, 8))
        return max(1, min(n, 8))

    def _strip_oral_reply(self, text: str) -> str:
        """对话框只留口语：去掉 markdown、名单行、后台话。"""
        if not text:
            return ""
        t = text.replace("**", "").replace("__", "").replace("`", "")
        t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
        lines = []
        for raw in t.splitlines():
            line = raw.strip()
            if not line:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            # 工具/名单 dump
            if line.startswith(">"):
                continue
            if line in {"---", "—", "–"}:
                continue
            if re.match(r"^消息如下[:：]", line):
                continue
            if re.match(r"^(微信|短信|邮件|钉钉|企业微信|QQ|iMessage)\s*[·•.\-]", line):
                continue
            if re.match(r"^\d+[\.、\)]\s*\S+", line) and ("米" in line or "路" in line or "号" in line):
                continue
            if " · " in line and (re.search(r"(路|街|号|店|米)", line) or len(line) > 24):
                # 「店名 · 地址」清单行
                if not re.search(r"[吗呢吧啊噢哦～]$", line):
                    continue
            if re.search(r"想去哪家[，,]?跟我说导航", line):
                continue
            if re.search(r"用户也可以直接说|完整店名|第几个", line):
                continue
            if re.search(r"(依据面板|过程面板|检索成功|口语候选|勿念|尚未开始导航|不要擅自)", line):
                continue
            if re.search(r"请用口语列出|禁止编造|不要增加未列出", line):
                continue
            lines.append(line)
        out = "\n".join(lines)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        if out and looks_like_raw_error(out):
            return DEFAULT_SPOKEN
        return out

    def _current_unread_message_ids(self, sess: SessionData) -> List[str]:
        st = sess.gateway.snapshot()
        note = st.get("notifications") or {}
        msgs = [m for m in (note.get("messages") or []) if isinstance(m, dict)]
        return sorted(
            str(m.get("id"))
            for m in msgs
            if m.get("id") is not None and not m.get("read")
        )

    def _query_about_messages(self, query: str) -> bool:
        q = (query or "").strip()
        return bool(
            re.search(r"(消息|通知|未读|短信|微信消息|读一下|念一下|有没有.*消息)", q)
        )

    def _should_skip_unread_nudge(
        self, query: str, tool_names: Optional[List[str]] = None
    ) -> bool:
        if self._query_about_messages(query):
            return True
        for name in tool_names or []:
            if (name or "").startswith("notifications."):
                return True
        return False

    def _mark_unread_nudge_seen(self, sess: SessionData, message_ids: Optional[List[str]] = None) -> None:
        ids = message_ids if message_ids is not None else self._current_unread_message_ids(sess)
        if not ids:
            sess.slots.pop("unread_nudge_ids", None)
            return
        nudged = {str(x) for x in (sess.slots.get("unread_nudge_ids") or [])}
        nudged.update(str(x) for x in ids)
        sess.slots["unread_nudge_ids"] = sorted(nudged)

    def _apply_unread_visual_nudge(
        self, sess: SessionData, answer: str, *, skip: bool = False
    ) -> Tuple[str, bool]:
        """仅追加【看】未读提醒，不进入语音；同一批未读只提醒一次。"""
        text = (answer or "").strip()
        if skip:
            return text, False
        unread_ids = self._current_unread_message_ids(sess)
        if not unread_ids:
            sess.slots.pop("unread_nudge_ids", None)
            return text, False
        nudged = {str(x) for x in (sess.slots.get("unread_nudge_ids") or [])}
        current = {str(x) for x in unread_ids}
        if current.issubset(nudged):
            return text, False
        if re.search(r"【看】[\s\S]*未读", text):
            self._mark_unread_nudge_seen(sess, unread_ids)
            return text, False
        visual = f"\n【看】您有 {len(unread_ids)} 条未读消息，可在中控屏「消息」查看。"
        text = text.rstrip() + visual
        self._mark_unread_nudge_seen(sess, unread_ids)
        return text, True

    def _emit_unread_visual_suffix(self, streamed: str, final: str):
        streamed = (streamed or "").rstrip()
        final = (final or "").rstrip()
        if not final or final == streamed:
            return
        if final.startswith(streamed):
            suffix = final[len(streamed) :]
            if suffix:
                yield from self._emit_text(suffix)
            return
        if "\n【看】" in final and "\n【看】" not in streamed:
            yield from self._emit_text(final[final.index("\n【看】") :])

    def _unread_nudge_payload(self, sess: SessionData, nudged: bool) -> Optional[Dict[str, Any]]:
        if not nudged:
            return None
        unread_ids = self._current_unread_message_ids(sess)
        if not unread_ids:
            return None
        n = len(unread_ids)
        return {
            "kind": "unread_messages",
            "count": n,
            "text": f"您有 {n} 条未读消息，可在中控屏「消息」查看。",
        }

    def _sync_unread_nudge_after_notifications(
        self,
        sess: SessionData,
        tool_names: Optional[List[str]],
        results: Optional[List[ToolResult]],
    ) -> None:
        names = tool_names or []
        if any(n == "notifications.list_messages" for n in names):
            for r in results or []:
                if (r.tool or "") == "notifications.list_messages" and r.success:
                    self._mark_unread_nudge_seen(sess)
                    return
        if any(n == "notifications.mark_read" for n in names):
            if not self._current_unread_message_ids(sess):
                sess.slots.pop("unread_nudge_ids", None)

    def _nearby_wrap_payload(self, query: str, results: List[ToolResult]) -> Optional[str]:
        """周边检索：只给模型店名，不给地址清单（完整条目在依据面板）。"""
        chunks: List[str] = []
        hit = False
        for r in results:
            if (r.tool or "") != "maps.search_nearby" or not r.success or not isinstance(r.data, dict):
                continue
            pois = [p for p in (r.data.get("recommend_pois") or r.data.get("pois") or []) if isinstance(p, dict)]
            if not pois:
                continue
            hit = True
            k = self._poi_recommend_count(query, len(pois))
            names = [str(p.get("name") or "").strip() for p in pois[:k] if p.get("name")]
            if not names:
                continue
            navigated = any(
                (x.tool or "") in {"navigation.navigate_to", "navigation.start"}
                and x.success
                and isinstance(x.data, dict)
                and not x.data.get("need_clarify")
                for x in results
            )
            if navigated:
                chunks.append(
                    f"已开始导航。店名仅供口述：{names[0]}。"
                    "只说去哪，不要列地址名单，不要用 markdown。"
                )
            else:
                chunks.append(
                    "可读店名（禁止输出地址/距离/编号列表，禁止 markdown）："
                    + "、".join(names)
                    + "。用一两句口语推荐并问想去哪家或口味偏好。"
                )
        return "\n\n".join(chunks) if hit else None

    def _nearby_spoken_fallback(self, query: str, results: List[ToolResult]) -> str:
        """模型失败时的短口语，绝不回吐名单。"""
        for r in results:
            if (r.tool or "") != "maps.search_nearby" or not r.success or not isinstance(r.data, dict):
                continue
            pois = [p for p in (r.data.get("recommend_pois") or r.data.get("pois") or []) if isinstance(p, dict)]
            k = self._poi_recommend_count(query, len(pois))
            names = [str(p.get("name") or "").strip() for p in pois[:k] if p.get("name")]
            if not names:
                return "【听】附近这会儿没搜到合适的，换个词我再帮你找。"
            if len(names) == 1:
                return f"【听】附近有一家{names[0]}，要导航过去吗？"
            if len(names) == 2:
                return f"【听】附近可以看看{names[0]}和{names[1]}，想去哪家跟我说一声。"
            return (
                f"【听】附近有不少选择，像{names[0]}、{names[1]}和{names[2]}都在这附近。"
                "想直接导航，还是有口味偏好？"
            )
        return "【听】附近这会儿没搜到合适的。"

    def _nearby_context_cards(self, results: List[ToolResult]) -> List[Dict[str, Any]]:
        """周边 POI → 与手册 RAG 同结构的依据卡片，供过程面板展开。"""
        cards: List[Dict[str, Any]] = []
        idx = 0
        for r in results:
            if (r.tool or "") != "maps.search_nearby" or not r.success or not isinstance(r.data, dict):
                continue
            for p in r.data.get("pois") or []:
                if not isinstance(p, dict) or not p.get("name"):
                    continue
                idx += 1
                dist = p.get("distance")
                addr = str(p.get("address") or "").strip()
                content_bits = [str(p.get("name"))]
                if dist not in (None, ""):
                    content_bits.append(f"距离约 {dist} 米")
                if addr:
                    content_bits.append(addr)
                content = "\n".join(content_bits)
                preview = " · ".join(content_bits[1:] ) if len(content_bits) > 1 else content
                if len(preview) > 140:
                    preview = preview[:140] + "…"
                cards.append(
                    {
                        "index": idx,
                        "title": str(p.get("name")),
                        "page": None,
                        "content": content,
                        "preview": preview,
                        "kind": "amap_poi",
                    }
                )
                if idx >= 8:
                    return cards
        return cards

    def _web_search_hits(self, results: List[ToolResult]) -> List[Dict[str, Any]]:
        hits: List[Dict[str, Any]] = []
        for r in results:
            if (r.tool or "") != "web.search" or not r.success or not isinstance(r.data, dict):
                continue
            for item in r.data.get("results") or []:
                if isinstance(item, dict) and (item.get("title") or item.get("url")):
                    hits.append(item)
        return hits

    def _web_search_wrap_payload(self, query: str, results: List[ToolResult]) -> Optional[str]:
        hits = self._web_search_hits(results)
        answers = []
        for r in results:
            if (r.tool or "") == "web.search" and r.success and isinstance(r.data, dict):
                a = str(r.data.get("answer") or "").strip()
                if a:
                    answers.append(a)
        if not hits and not answers:
            if any((r.tool or "") == "web.search" for r in results):
                fails = [r for r in results if (r.tool or "") == "web.search" and not r.success]
                if fails:
                    return None
            return None
        parts: List[str] = [
            "请用两三句口语概括回答用户，不要念网址，不要编造未出现的数字。"
        ]
        if answers:
            parts.append("检索摘要（数字以这里为准）：\n" + answers[0][:600])
        if hits:
            lines = []
            for i, h in enumerate(hits[:5], 1):
                title = str(h.get("title") or "").strip()
                snippet = str(h.get("snippet") or "").strip()
                src = str(h.get("source") or "").strip()
                bit = f"{i}. {title}"
                if snippet:
                    bit += f"：{snippet[:120]}"
                if src:
                    bit += f"（{src}）"
                lines.append(bit)
            parts.append("网页来源：\n" + "\n".join(lines))
        return "\n".join(parts)

    def _web_search_spoken_fallback(self, results: List[ToolResult]) -> str:
        for r in results:
            if (r.tool or "") == "web.search" and r.success and isinstance(r.data, dict):
                a = str(r.data.get("answer") or "").strip()
                if a:
                    short = a.replace("\n", " ").strip()
                    if len(short) > 160:
                        short = short[:160] + "…"
                    return f"【听】{short}"
        hits = self._web_search_hits(results)
        if not hits:
            return "【听】网上这会儿没搜到靠谱结果，换个关键词我再帮你查。"
        titles = [str(h.get("title") or "").strip() for h in hits[:3] if h.get("title")]
        if not titles:
            return "【听】搜到一些网页，依据面板里可以点开看。"
        if len(titles) == 1:
            return f"【听】网上看到的是：{titles[0]}。详情在依据里。"
        return f"【听】网上主要提到{titles[0]}，另外还有{titles[1]}。详情可以看依据。"

    def _web_search_context_cards(self, results: List[ToolResult]) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        for i, h in enumerate(self._web_search_hits(results)[:8], 1):
            title = str(h.get("title") or f"网页 {i}").strip()
            url = str(h.get("url") or "").strip()
            snippet = str(h.get("snippet") or "").strip()
            src = str(h.get("source") or "").strip()
            content_bits = [p for p in (snippet, url) if p]
            content = "\n".join(content_bits) or title
            preview = snippet or url
            if len(preview) > 140:
                preview = preview[:140] + "…"
            cards.append(
                {
                    "index": i,
                    "title": title,
                    "page": src or None,
                    "content": content,
                    "preview": preview,
                    "kind": "web",
                    "url": url or None,
                }
            )
        return cards

    _MSG_URGENT_RE = re.compile(
        r"紧急|立刻|马上|尽快|会议|改期|改到|验证码|快递|到达|取件|欠费|停机|流量|报警|医院|逾期|到期"
    )

    def _message_evidence(self, data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """消息正文 → 依据卡片 + trace detail（完整内容不进口语）。"""
        msgs = [m for m in (data.get("messages") or []) if isinstance(m, dict)]
        cards: List[Dict[str, Any]] = []
        lines: List[str] = []
        urgent: List[str] = []
        unread_n = 0
        for i, m in enumerate(msgs[:12], 1):
            app = str(m.get("app") or "消息")
            sender = str(m.get("from") or "未知")
            text = str(m.get("text") or "").strip()
            unread = bool(m.get("unread") or (m.get("read") is False))
            if unread:
                unread_n += 1
            title = f"{app} · {sender}"
            flag = "未读" if unread else "已读"
            is_urgent = bool(self._MSG_URGENT_RE.search(text) or self._MSG_URGENT_RE.search(title))
            if is_urgent and unread:
                urgent.append(f"{title}：{text[:40]}{'…' if len(text) > 40 else ''}")
            cards.append(
                {
                    "index": i,
                    "title": title,
                    "page": flag + (" · 重点" if is_urgent else ""),
                    "content": text,
                    "preview": (text[:140] + "…") if len(text) > 140 else text,
                    "kind": "message",
                }
            )
            lines.append(f"消息 · [{flag}] {title}：{text}")
        detail = {
            "messages": [
                {
                    "app": m.get("app"),
                    "from": m.get("from"),
                    "text": m.get("text"),
                    "unread": bool(m.get("unread") or (m.get("read") is False)),
                }
                for m in msgs[:12]
            ],
            "unread_count": unread_n if msgs else int(data.get("unread_count") or 0),
            "count": len(msgs),
            "urgent": urgent,
            "result": (
                f"已读取 {len(msgs)} 条消息（未读 {unread_n}）；完整正文见依据面板。"
                if msgs
                else "没有消息"
            ),
            "message_lines": lines,
        }
        return cards, detail

    def _message_context_cards(self, results: List[ToolResult]) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        for r in results:
            if (r.tool or "") != "notifications.list_messages" or not r.success:
                continue
            if not isinstance(r.data, dict):
                continue
            part, _ = self._message_evidence(r.data)
            # 重新编号，避免与 POI 卡片撞号
            base = len(cards)
            for c in part:
                c = dict(c)
                c["index"] = base + int(c.get("index") or 1)
                cards.append(c)
        return cards

    def _messages_spoken_summary(self, results: List[ToolResult]) -> Optional[str]:
        """读消息后的口头摘要：不经 LLM，绝不把完整正文塞进对话框。"""
        for r in results:
            if (r.tool or "") != "notifications.list_messages" or not r.success:
                continue
            if not isinstance(r.data, dict):
                continue
            msgs = [m for m in (r.data.get("messages") or []) if isinstance(m, dict)]
            if not msgs:
                return "这会儿没有可看的消息。"
            unread = [m for m in msgs if m.get("unread") or m.get("read") is False]
            focus = unread or msgs

            def _gist(m: Dict[str, Any]) -> str:
                text = str(m.get("text") or "")
                sender = str(m.get("from") or "有人")
                if re.search(r"会议|改到|改期", text):
                    return f"{sender}说会议有变动"
                if re.search(r"包裹|快递|驿站|取件", text):
                    return "有快递到站了"
                if re.search(r"流量|欠费|套餐", text):
                    return "有条套餐或流量提醒"
                if re.search(r"验证码|校验码", text):
                    return f"{sender}发了验证码"
                if re.search(r"紧急|立刻|马上|尽快", text):
                    return f"{sender}有条比较急的消息"
                return f"{sender}有新消息"

            gists = []
            seen = set()
            for m in focus:
                g = _gist(m)
                if g in seen:
                    continue
                seen.add(g)
                gists.append(g)
                if len(gists) >= 3:
                    break

            n_unread = len(unread)
            if n_unread <= 0:
                return f"看过了，一共 {len(msgs)} 条，没有未读。"
            if len(gists) == 1:
                return f"有 {n_unread} 条未读，{gists[0]}。"
            if len(gists) == 2:
                return f"有 {n_unread} 条未读：{gists[0]}，另外{gists[1]}。"
            return f"有 {n_unread} 条未读：{gists[0]}，还有{gists[1]}等，详细的在依据里。"
        return None

    def _messages_wrap_payload(self, results: List[ToolResult]) -> Optional[str]:
        # 兼容旧调用点：直接返回口语摘要（无正文）
        return self._messages_spoken_summary(results)

    def _nav_clarify_spoken(self, results: List[ToolResult]) -> Optional[str]:
        """目的地歧义：直接生成用户口语，不经 LLM，避免开发者指令/无关店名泄漏。"""
        for r in results:
            if (r.tool or "") not in {"navigation.navigate_to", "navigation.start"}:
                continue
            if not isinstance(r.data, dict) or not r.data.get("need_clarify"):
                continue
            cands = [c for c in (r.data.get("candidates") or []) if isinstance(c, dict) and c.get("name")]
            if not cands:
                continue
            q = str(r.data.get("query") or "那里").strip() or "那里"
            names = [str(c.get("name")).strip() for c in cands[:4] if str(c.get("name") or "").strip()]
            if not names:
                continue
            if len(names) == 1:
                return f"找到了{names[0]}，要我现在带你过去吗？"
            if len(names) == 2:
                return f"「{q}」有两处，一个是{names[0]}，一个是{names[1]}。你想去哪个？"
            mid = "、".join(names[:-1])
            return f"「{q}」有好几处，分别是{mid}，还有{names[-1]}。你想去哪一个？"
        return None

    def _nav_clarify_payload(self, results: List[ToolResult]) -> Optional[str]:
        for r in results:
            if (r.tool or "") not in {"navigation.navigate_to", "navigation.start"}:
                continue
            if not isinstance(r.data, dict) or not r.data.get("need_clarify"):
                continue
            cands = [c for c in (r.data.get("candidates") or []) if isinstance(c, dict)]
            if not cands:
                continue
            q = r.data.get("query") or "那里"
            lines = []
            for c in cands[:4]:
                addr = (c.get("address") or "").strip()
                lines.append(
                    f"{c.get('index') or len(lines)+1}. {c.get('name')}"
                    + (f"（{addr}）" if addr else "")
                )
            return (
                f"目的地「{q}」有多处，还没开导航。候选人选：\n"
                + "\n".join(lines)
            )
        return None

    def _consume_override_note(self, sess: SessionData) -> str:
        note = str(sess.slots.pop("_pending_override_note", "") or "").strip()
        return note

    def _with_continuity_prefix(self, sess: SessionData, msg: str) -> str:
        note = self._consume_override_note(sess)
        text = (msg or "").strip()
        if not note:
            return text
        if text.startswith("【听】"):
            return f"【听】{note}{text[3:].lstrip('，, ')}"
        return f"【听】{note}{text}"

    def _warm_tool_reply(
        self,
        llm: LLMClient,
        query: str,
        tool_msg: str,
        results: Optional[List[ToolResult]] = None,
        sess: Optional[SessionData] = None,
    ) -> str:
        """把工具结果转成温暖口语；对话框只留口语，绝不回吐工具原文/名单。"""
        def _finish(text: str) -> str:
            oral = self._strip_oral_reply(text)
            if sess is not None:
                return self._with_continuity_prefix(sess, oral)
            return oral

        if results:
            map_fail = [
                r
                for r in results
                if (r.tool or "").startswith("maps.") and not r.success
            ]
            if map_fail:
                clean = []
                for r in map_fail:
                    m = (r.message or "").strip()
                    if m and not looks_like_raw_error(m):
                        clean.append(m)
                return _finish("；".join(clean) or "地图这会儿连不上。")
            spoken = self._messages_spoken_summary(results)
            if spoken:
                return _finish(spoken)
            nearby = self._nearby_wrap_payload(query, results)
            if nearby:
                try:
                    text = llm.chat(
                        TOOL_WRAP_STYLE,
                        f"用户原话：{query}\n可供口述的材料（禁止照抄成名单）：\n{nearby}",
                        temperature=0.35,
                        retries=1,
                    )
                    text = self._strip_oral_reply((text or "").strip())
                    if text and "【听】" not in text:
                        text = f"【听】{text}"
                    return _finish(text or self._nearby_spoken_fallback(query, results))
                except Exception:
                    return _finish(self._nearby_spoken_fallback(query, results))
            web = self._web_search_wrap_payload(query, results)
            if web:
                try:
                    text = llm.chat(
                        TOOL_WRAP_STYLE,
                        f"用户原话：{query}\n可供口述的材料（禁止念网址、禁止编造）：\n{web}",
                        temperature=0.35,
                        retries=1,
                    )
                    text = self._strip_oral_reply((text or "").strip())
                    if text and "【听】" not in text:
                        text = f"【听】{text}"
                    return _finish(text or self._web_search_spoken_fallback(results))
                except Exception:
                    return _finish(self._web_search_spoken_fallback(results))
            clarify_spoken = self._nav_clarify_spoken(results)
            if clarify_spoken:
                return _finish(f"【听】{clarify_spoken}")
            if all(not r.success for r in results):
                # 失败也给连续人话，避免用户以为会话坏了
                detail = "；".join(
                    (r.message or "").strip()
                    for r in results
                    if (r.message or "").strip() and not looks_like_raw_error(r.message or "")
                )
                if detail:
                    return _finish(
                        sanitize_spoken(
                            f"【听】这步没做成：{detail[:160]}。你可以换个说法再试，不用重置会话。"
                        )
                    )
                return _finish("【听】这步没做成，换个说法再试就行，不用重置会话。")
        try:
            text = llm.chat(
                TOOL_WRAP_STYLE,
                f"用户原话：{query}\n工具结果摘要（禁止照抄后台原文，禁止 markdown）：\n{tool_msg}",
                temperature=0.35,
                retries=1,
            )
            text = self._strip_oral_reply((text or "").strip())
            if text and "【听】" not in text:
                text = f"【听】{text}"
            return _finish(text or "【听】好，我这边处理好了。")
        except Exception as e:
            info = classify_llm_error(e, mode=getattr(llm, "mode", "remote"))
            return _finish(compose_llm_fail_reply(info, fact="【听】车上这步已经处理好了。"))

    def _handle_search(
        self,
        sess: SessionData,
        query: str,
        llm: LLMClient,
        metrics: TurnMetrics,
        bundle,
        turn: TurnTrace,
        active_seat: str = "front_left",
    ):
        yield StreamEvent("status", "查询车辆状态...")
        yield from self._trace(turn, StepType.SEARCH, "读取车辆状态", {"active_seat": active_seat})
        yield from self._emit_text(f"> **[{_ts()}] SEARCH: 读取车辆状态...**\n\n---\n\n")
        state = sess.gateway.snapshot()
        seat = normalize_active_seat(active_seat)
        from app.agent.context import (
            format_climate_status,
            format_lights_status,
            format_nav_status,
            slim_vehicle_for_query,
            spoken_vehicle_status,
            strip_vehicle_snapshot_block,
        )

        climate_view = format_climate_status(state, seat)
        nav_view = format_nav_status(state)
        lights_view = format_lights_status(state)
        slim = slim_vehicle_for_query(state, query)
        # 完整快照里常有正在播放的歌，会诱发「歌快完了要不要换」这类无关加戏
        user_context = strip_vehicle_snapshot_block(bundle.user_context)
        q = (query or "").strip()
        about_climate = any(k in q for k in ("空调", "温度", "制冷", "制热", "风量", "循环"))
        about_nav = any(
            k in q
            for k in (
                "导航",
                "在哪",
                "位置",
                "到哪",
                "目的地",
                "还要多久",
                "还差",
                "多久",
                "几分钟",
                "几公里",
                "多远",
                "剩余",
                "到达",
                "路况",
                "还有多",
            )
        )
        about_lights = any(k in q for k in ("氛围灯", "阅读灯", "顶灯", "灯光", "氛围", "车灯"))
        blocks = []
        if about_climate:
            blocks.append(f"分区空调一览（优先采信）:\n{climate_view}")
        if about_nav:
            blocks.append(f"导航定位一览（优先采信）:\n{nav_view}")
        if about_lights:
            blocks.append(f"灯光一览（优先采信）:\n{lights_view}")
        blocks.append(f"相关状态JSON:\n{json.dumps(slim, ensure_ascii=False)}")
        system = (
            bundle.system
            + "\n"
            + SEARCH_STYLE
            + "\n\n"
            + user_context
            + f"\n\n当前说话人座位：{SEAT_CN.get(seat, seat)}（{seat}）。"
            "若用户说「我这边/我的座位」等，优先回答该座位相关状态。"
            "下面的状态已按本轮问题裁剪：没出现的子系统不要提、不要反问。"
        )
        user = (
            f"最近对话:\n{bundle.recent_dialog}\n\n"
            + "\n\n".join(blocks)
            + f"\n\n当前座位: {seat}\n用户问: {query}"
        )
        full: List[str] = []
        llm_failed = False
        try:
            for token in llm.chat_stream(system, user, temperature=0.45):
                full.append(token)
                yield StreamEvent("token", token)
            metrics.llm_calls += 1
            ans = "".join(full).strip() or "这一块我暂时没读到，你再问具体一点我帮你看。"
        except Exception as e:
            llm_failed = True
            info = classify_llm_error(e, mode=getattr(llm, "mode", "remote"))
            yield from self._trace(turn, StepType.ERROR, "状态口语生成失败", info, status="error")
            if full:
                ans = "".join(full).strip()
            else:
                fact = spoken_vehicle_status(state, query, seat)
                ans = compose_llm_fail_reply(info, fact=fact)
                yield from self._emit_text(ans)
        raw_ans = ans
        skip_nudge = llm_failed or self._should_skip_unread_nudge(query, metrics.tools)
        ans, nudged = self._apply_unread_visual_nudge(sess, ans, skip=skip_nudge)
        if nudged:
            yield from self._emit_unread_visual_suffix(raw_ans, ans)
        sess.transcript.append(MessageRole.ASSISTANT, ans)
        yield from self._trace(turn, StepType.RESPONSE, "状态回答", {"answer": ans[:200]})
        yield from self._commit_turn(sess, turn, metrics, "warn" if llm_failed else "ok", ans)
        nudge = self._unread_nudge_payload(sess, nudged)
        yield StreamEvent(
            "final",
            {
                "turn_id": turn.turn_id,
                "cite_pages": [],
                "related_images": [],
                "state": self._state_summary(sess),
                **({"visual_nudge": nudge} if nudge else {}),
            },
        )

    def _handle_knowledge(
        self, sess: SessionData, query: str, llm: LLMClient, metrics: TurnMetrics, turn: TurnTrace
    ):
        yield StreamEvent("status", "检索手册知识库...")
        yield from self._emit_text(f"> **[{_ts()}] 知识查询，检索中...**\n>\n")
        rag = self._get_rag()
        docs = []
        retrieve_error = ""
        context_str, context_cards = "", []
        try:
            docs = rag.retrieve(query) or []
            if docs:
                context_str, context_cards = rag.build_context_cards(docs)
        except Exception as e:
            retrieve_error = str(e) or e.__class__.__name__
            yield from self._trace(
                turn,
                StepType.KNOWLEDGE,
                "检索手册失败",
                {"error": retrieve_error, "doc_count": 0, "docs": []},
                status="error",
            )
        else:
            yield from self._trace(
                turn,
                StepType.KNOWLEDGE,
                f"命中 {len(docs)} 篇文档" if docs else "未命中文档",
                {"doc_count": len(docs), "docs": context_cards},
                status="ok" if docs else "warn",
            )

        if retrieve_error or not docs:
            answer = (
                "【听】手册知识库这会儿连不上，我没法对照原文答。稍后再问一遍就行。"
                if retrieve_error
                else KNOWLEDGE_EMPTY
            )
            sess.transcript.append(MessageRole.ASSISTANT, answer)
            yield from self._trace(
                turn,
                StepType.RESPONSE,
                "知识回答",
                {
                    "answer": answer,
                    "reason": "rag_unavailable" if retrieve_error else "no_docs",
                },
            )
            yield from self._emit_text(answer)
            yield from self._commit_turn(
                sess, turn, metrics, "error" if retrieve_error else "ok", answer
            )
            yield StreamEvent(
                "final",
                {
                    "turn_id": turn.turn_id,
                    "cite_pages": [],
                    "related_images": [],
                    "state": self._state_summary(sess),
                },
            )
            return

        yield from self._emit_text(f"> **[{_ts()}] 检索到{len(docs)}篇文档，生成回答中...**\n\n---\n\n")
        yield StreamEvent("context", context_cards)
        system = KNOWLEDGE_STYLE + sess.memory.build_style_overlay()
        user = (
            f"用户问题: {query}\n\n参考文档:\n{context_str}\n\n"
            "请严格按系统要求的结构作答：先结论，再编号步骤，必要时用纯文字写「小提示：」。"
            "禁止 emoji、表情符号和装饰图标。"
            "只在真正引用到某篇参考文档的句子/步骤末尾标【n】；没有引用的句子不要标来源；"
            "最后「参考：」行只列实际用到的编号，未引用则不写该行。"
        )
        try:
            full = []
            for token in llm.chat_stream(system, user, temperature=0.35):
                full.append(token)
                yield StreamEvent("token", token)
            metrics.llm_calls += 1
            answer = "".join(full)
        except Exception as e:
            info = classify_llm_error(e, mode=getattr(llm, "mode", "remote"))
            yield from self._trace(turn, StepType.ERROR, "知识流式生成失败", info, status="error")
            try:
                answer = llm.chat(system, user, temperature=0.35, retries=1)
                metrics.llm_calls += 1
                yield from self._emit_text(answer)
            except Exception as e2:
                info2 = classify_llm_error(e2, mode=getattr(llm, "mode", "remote"))
                yield from self._trace(turn, StepType.ERROR, "知识回答生成失败", info2, status="error")
                answer = compose_llm_fail_reply(
                    info2,
                    fact="【听】手册检索已经有结果了，但这句没法生成。",
                )
                yield from self._emit_text(answer)

        raw_answer = answer
        skip_nudge = self._should_skip_unread_nudge(query, metrics.tools)
        answer, nudged = self._apply_unread_visual_nudge(sess, answer, skip=skip_nudge)
        if nudged:
            yield from self._emit_unread_visual_suffix(raw_answer, answer)

        sess.transcript.append(MessageRole.ASSISTANT, answer)
        post = rag.post_process(answer, docs)
        yield from self._trace(turn, StepType.RESPONSE, "知识回答", {"answer": answer[:200]})
        yield from self._commit_turn(sess, turn, metrics, "ok", answer)
        nudge = self._unread_nudge_payload(sess, nudged)
        yield StreamEvent(
            "final",
            {
                "turn_id": turn.turn_id,
                "cite_pages": post.get("cite_pages", []),
                "related_images": post.get("related_images", []),
                "contexts": context_cards,
                "state": self._state_summary(sess),
                "metrics": _metrics_dict(metrics),
                **({"visual_nudge": nudge} if nudge else {}),
            },
        )

    def _handle_chat(
        self, sess: SessionData, query: str, llm: LLMClient, metrics: TurnMetrics, bundle, turn: TurnTrace
    ):
        # 闲聊里若其实是周边生活问题，升格为地图工具（全能助手）
        nearby = try_nearby_utterance(query)
        if nearby is not None:
            memory_hint = self.store.assembler.memory_hint(bundle, sess.transcript)
            metrics.intent = nearby.intent.value
            metrics.tools = [c.name for c in nearby.tool_calls]
            yield from self._trace(turn, StepType.INTENT, "闲聊升级为周边检索", {"fast_path": "nearby_from_chat"})
            yield from self._handle_tools(
                sess, query, nearby, llm, memory_hint, metrics, turn, active_seat="front_left"
            )
            return

        web = try_web_search_utterance(query)
        if web is not None:
            memory_hint = self.store.assembler.memory_hint(bundle, sess.transcript)
            metrics.intent = web.intent.value
            metrics.tools = [c.name for c in web.tool_calls]
            yield from self._trace(turn, StepType.INTENT, "闲聊升级为网页检索", {"fast_path": "web_from_chat"})
            yield from self._handle_tools(
                sess, query, web, llm, memory_hint, metrics, turn, active_seat="front_left"
            )
            return

        yield StreamEvent("status", "思考中...")
        yield from self._trace(turn, StepType.CHAT, "闲聊路径")
        yield from self._emit_text(f"> **[{_ts()}] 闲聊（带上下文）...**\n\n---\n\n")
        if bundle.recent_dialog:
            yield from self._emit_text("> [Transcript] 已注入最近对话\n\n")
        st = sess.gateway.snapshot()
        nav = st.get("navigation") or {}
        pos = nav.get("position") or {}
        note = st.get("notifications") or {}
        msgs = [m for m in (note.get("messages") or []) if isinstance(m, dict)]
        unread_n = sum(1 for m in msgs if not m.get("read"))
        q_ask = (query or "").strip()
        about_loc = bool(
            re.search(r"(在哪|哪里|位置|定位|导航|目的地|还要多久|多远)", q_ask)
        )
        about_msg = bool(re.search(r"(消息|通知|未读|短信|微信消息|读一下|念一下)", q_ask))
        loc_hint = ""
        if about_loc and pos.get("lng") is not None and pos.get("lat") is not None:
            place = pos.get("name") or "行驶中"
            if nav.get("navigating"):
                remain = nav.get("remaining_m")
                remain_s = (
                    f"，剩余约 {remain / 1000:.1f} 公里"
                    if isinstance(remain, (int, float))
                    else ""
                )
                dest = nav.get("destination") or "目的地"
                loc_hint = (
                    f"\n当前车辆定位：{place}；导航已开启，前往 {dest}{remain_s}。"
                    "只回答与位置/导航相关的问题；勿提未读消息或其它子系统。"
                )
            else:
                loc_hint = (
                    f"\n当前车辆定位：{place}；导航未开启（navigating=false）。"
                    "用户问「在哪里」时只报当前位置路名，禁止说剩余公里、ETA、目的地。"
                    "勿提未读消息或其它子系统。"
                )
        sys_hint = ""
        if about_msg:
            sys_hint = (
                f"\n车机通知：未读消息 {unread_n} 条；电话={note.get('phone_status') or '空闲'}。"
                "用户要读消息时，调用 notifications.list_messages（会先隐私确认）；"
                "确认后口头只摘要未读与紧急项，完整正文在依据面板；不要编造正文。"
            )
        else:
            # 默认不把未读/Wi‑Fi塞进闲聊上下文，避免模型主动加戏
            sys_hint = (
                "\n约束：本轮未问消息/连接时，禁止主动提及未读消息、Wi‑Fi、电话状态。"
            )
        pref = sess.memory.format_preferences_block()
        style_overlay = sess.memory.build_style_overlay()
        system = CHAT_STYLE + style_overlay + "\n\n" + pref + loc_hint + sys_hint
        recent = bundle.recent_dialog or ""
        if len(recent) > 1200:
            recent = recent[-1200:]
        search_block = ""
        web_q = chat_web_query(query, recent)
        if web_q:
            yield StreamEvent("status", "网上查一下...")
            call = ToolCall(name="web.search", arguments={"query": web_q, "count": 5}, reason="闲聊联网")
            result = self.registry.execute(sess.gateway, call)
            metrics.tools = ["web.search"]
            yield from self._trace(
                turn,
                StepType.TOOL,
                "闲聊调用网页搜索",
                {"query": web_q, "success": result.success, "provider": (result.data or {}).get("provider")},
            )
            web_cards = self._web_search_context_cards([result])
            if web_cards:
                yield StreamEvent("context", web_cards)
                yield from self._trace(
                    turn,
                    StepType.TOOL,
                    f"读入网页依据 {len(web_cards)} 条",
                    {"doc_count": len(web_cards), "kind": "web"},
                )
            wrap = self._web_search_wrap_payload(query, [result])
            search_block = wrap or (result.message or "")
            ans = str((result.data or {}).get("answer") or "").strip()
            if ans and "检索摘要" not in search_block:
                search_block = f"检索摘要：{ans[:500]}\n" + (search_block or "")
            yield from self._emit_text(f"> [web.search] {web_q}\n\n")
        user = f"最近对话:\n{recent}\n\n用户: {query}"
        if search_block:
            user = (
                f"最近对话:\n{recent}\n\n"
                f"网上检索材料（供闲聊引用，禁止编造材料外事实）：\n{search_block}\n\n"
                f"用户: {query}"
            )
        llm_failed = False
        try:
            full = []
            for token in llm.chat_stream(system, user, temperature=0.45):
                full.append(token)
                yield StreamEvent("token", token)
            metrics.llm_calls += 1
            answer = "".join(full)
        except Exception as e:
            llm_failed = True
            info = classify_llm_error(e, mode=getattr(llm, "mode", "remote"))
            yield from self._trace(turn, StepType.ERROR, "闲聊生成失败", info, status="error")
            fact = ""
            if about_loc:
                place = str(pos.get("name") or "").strip()
                if place and nav.get("navigating"):
                    dest = str(nav.get("destination") or "目的地").strip() or "目的地"
                    fact = f"【听】你现在在{place}，正往{dest}开。"
                elif place:
                    fact = f"【听】你现在在{place}。"
            answer = compose_llm_fail_reply(info, fact=fact)
            yield from self._emit_text(answer)
        raw_answer = answer
        skip_nudge = about_msg or llm_failed
        answer, nudged = self._apply_unread_visual_nudge(sess, answer, skip=skip_nudge)
        if nudged:
            yield from self._emit_unread_visual_suffix(raw_answer, answer)
        sess.transcript.append(MessageRole.ASSISTANT, answer)
        yield from self._trace(turn, StepType.RESPONSE, "闲聊回答", {"answer": answer[:200]})
        yield from self._persist_turn(sess, llm, query, metrics, turn)
        yield from self._commit_turn(sess, turn, metrics, "warn" if llm_failed else "ok", answer)
        nudge = self._unread_nudge_payload(sess, nudged)
        yield StreamEvent(
            "final",
            {
                "turn_id": turn.turn_id,
                "cite_pages": [],
                "related_images": [],
                "state": self._state_summary(sess),
                **({"visual_nudge": nudge} if nudge else {}),
            },
        )

    def _state_summary(self, sess: SessionData) -> Dict[str, Any]:
        st = sess.gateway.snapshot()
        climate = st.get("climate", {})
        seat = normalize_active_seat(sess.slots.get("active_seat"))
        zone = (climate.get("zones") or {}).get(seat) or (climate.get("zones") or {}).get("front_left") or {}
        media = st.get("media", {})
        prefs = sess.memory.load_preferences()
        persona = sess.memory.load_persona()
        memories = sess.memory.load_memories()
        mem_count = len((memories.get("items") or []))
        unread_n = len(self._current_unread_message_ids(sess))
        from app.agent.user_profile import md_preview

        return {
            "climate_power": climate.get("power"),
            "temp": zone.get("temp"),
            "fan": zone.get("fan"),
            "active_seat": seat,
            "active_seat_cn": SEAT_CN.get(seat, seat),
            "preferences": {
                "text": md_preview(prefs.get("text") or ""),
                "preferred_seat": prefs.get("preferred_seat"),
                "climate_temp_c": prefs.get("climate_temp_c"),
                "climate_apply_all": prefs.get("climate_apply_all"),
            },
            "persona": {"text": md_preview(persona.get("text") or "")},
            "memories_preview": md_preview(memories.get("text") or ""),
            "memory_count": mem_count,
            "unread_messages": unread_n,
            "volume": media.get("volume"),
            "music": media.get("music"),
            "navigation": st.get("navigation"),
            "speed_kmh": st.get("dynamics", {}).get("speed_kmh"),
            "gear": st.get("dynamics", {}).get("gear"),
            "pending": bool(sess.pending),
            "session_id": sess.session_id,
            "transcript_chars": sess.transcript.total_chars(),
            "turn_count": len(sess.traces.list_turns(limit=1000)),
        }

    def _emit_text(self, text: str):
        if not text:
            return
        # 过程面板用 > 开头；口语一旦夹带堆栈/接口原文，整段换成兜底
        head = text.lstrip()
        if head and not head.startswith(">") and looks_like_raw_error(text):
            text = DEFAULT_SPOKEN
        yield StreamEvent("token", text)


_ORCH: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    global _ORCH
    if _ORCH is None:
        _ORCH = Orchestrator()
    return _ORCH
