# -*- coding: utf-8 -*-
"""编排：Claude Code 风格 Agent Harness + 车载专用路径。

每轮：
  1) 写入 user transcript
  2) 分层 compact（如需要）
  3) assemble context（CABIN.md / MEMORY / vehicle / recent）
  4) NLU 逐步规划（每步可并行无依赖工具；有依赖则拆步）
  5) tool → AgentLoop（observe 后再规划）；其它路径专用 handler
  6) 写入 assistant/tool transcript + 持久化 session
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

from app import config
from app.agent.hooks import HookBus
from app.agent.loop import AgentLoop
from app.agent.persona import (
    CHAT_FALLBACK,
    CHAT_STYLE,
    KNOWLEDGE_EMPTY,
    KNOWLEDGE_STYLE,
    SEARCH_STYLE,
    TOOL_WRAP_STYLE,
)
from app.agent.trace import StepType, TurnTrace
from app.agent.types import MessageRole
from app.llm.client import LLMClient, get_llm
from app.models import IntentType, PendingAction, RouteResult, ToolCall, ToolResult
from app.nlu.fast_path import (
    try_combo_cabin_utterance,
    try_confirm_utterance,
    try_direct_cabin_utterance,
    try_nearby_utterance,
    try_nav_candidate_utterance,
    try_preference_utterance,
    try_status_utterance,
)
from app.nlu.planner import StructuredNLU
from app.nlu.seat_context import (
    SEAT_CN,
    apply_active_seat_defaults,
    apply_memory_climate_defaults,
    normalize_active_seat,
)
from app.agent.memory import build_preference_tool_calls
from app.policy.engine import PolicyEngine
from app.rag.service import RagService, get_rag_service
from app.session.store import SessionData, get_session_store
from app.tools.registry import get_registry


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


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _metrics_dict(m: TurnMetrics) -> Dict[str, Any]:
    return {
        "llm_calls": m.llm_calls,
        "loop_iters": m.loop_iters,
        "compact_layers": m.compact_layers,
        "context_chars": m.context_chars,
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

    def _get_rag(self) -> RagService:
        if self._rag is None:
            self._rag = get_rag_service()
        return self._rag

    def handle(
        self,
        query: str,
        session_id: str = "default",
        model: str = "remote",
        confirm: Optional[bool] = None,
        active_seat: Optional[str] = None,
    ) -> Generator[StreamEvent, None, TurnMetrics]:
        metrics = TurnMetrics()
        sess = self.store.get(session_id)
        llm = get_llm(model)
        q = (query or "").strip()

        # Claude Code 同款：先确定性写入偏好，再解析生效座位
        pref_delta = sess.memory.ingest_utterance(q)
        seat, seat_src = sess.memory.resolve_active_seat(active_seat or sess.slots.get("active_seat"), q)
        if pref_delta.preferred_seat:
            seat = normalize_active_seat(pref_delta.preferred_seat)
            seat_src = "memory"
        sess.slots["active_seat"] = seat
        turn = TurnTrace(session_id=session_id, query=q, model=model)
        metrics.turn_id = turn.turn_id

        yield StreamEvent("status", "Agent 上下文准备中...")
        yield StreamEvent(
            "active_seat",
            {"active_seat": seat, "active_seat_cn": SEAT_CN.get(seat, seat), "source": seat_src},
        )
        if pref_delta.applied:
            yield from self._trace(
                turn,
                StepType.MEMORY,
                "写入 Auto Memory / preferences",
                {
                    "preferred_seat": pref_delta.preferred_seat,
                    "climate_temps": pref_delta.climate_temps,
                    "notes": pref_delta.notes[:4],
                },
            )
            yield StreamEvent(
                "memory",
                {
                    "preferences": sess.memory.load_preferences(),
                    "delta": {
                        "preferred_seat": pref_delta.preferred_seat,
                        "climate_temps": pref_delta.climate_temps,
                    },
                },
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
            f"> **[{_ts()}] Agent Harness** · turn `{turn.turn_id}` · session `{session_id}`"
            f" · seat `{SEAT_CN.get(seat, seat)}` ({seat_src})\n>\n"
        )

        # 0) pending confirmation
        if sess.pending is not None:
            confirm_route = try_confirm_utterance(q)
            do_confirm = confirm is True or (confirm_route and confirm_route.intent == IntentType.CONFIRM)
            do_cancel = confirm is False or (confirm_route and confirm_route.intent == IntentType.CANCEL)
            if do_confirm:
                pending = sess.pending
                sess.pending = None
                privacy = (getattr(pending, "confirm_kind", None) or "safety") == "privacy"
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
                msg = self._warm_tool_reply(llm, q, raw_msg, results=results)
                metrics.llm_calls += 1
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                metrics.intent = "tool"
                metrics.tools = [c.name for c in pending.tool_calls]
                yield from self._commit_turn(sess, turn, metrics, "ok", msg)
                self.store.save(sess)
                yield from self._emit_text("\n" + msg)
                yield StreamEvent(
                    "final",
                    {
                        "turn_id": turn.turn_id,
                        "tool_results": [r.model_dump() for r in results],
                        "cite_pages": [],
                        "related_images": [],
                        "contexts": message_contexts,
                        "state": self._state_summary(sess),
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
                self.store.save(sess)
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
            sess.pending = None
            yield from self._trace(turn, StepType.CONFIRM, "新指令覆盖未确认动作", status="warn")
            yield from self._emit_text(f"> **[{_ts()}] 新指令覆盖未确认动作**\n\n---\n\n")

        # 1) append user turn
        sess.transcript.append(MessageRole.USER, q)

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
        metrics.context_chars = bundle.total_chars
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
        pref_block = sess.memory.format_preferences_block()
        if pref_block:
            memory_hint = f"{pref_block}\n{memory_hint}"

        direct = (
            try_nav_candidate_utterance(q, sess.slots.get("nav_candidates"))
            or try_status_utterance(q)
            or try_combo_cabin_utterance(q)
            or try_preference_utterance(q)
            or try_direct_cabin_utterance(q)
            or try_nearby_utterance(q)
        )
        # 偏好句：注入温控工具，保证仪表立刻变化
        if direct is not None and direct.reason == "记忆偏好并应用":
            tools = build_preference_tool_calls(pref_delta)
            if tools:
                direct = RouteResult(
                    intent=IntentType.MULTI_TOOL if len(tools) > 1 else IntentType.TOOL,
                    confidence=0.99,
                    reason="记忆偏好并应用",
                    tool_calls=tools,
                )
            else:
                # 只更新座位记忆等：直接确认，不进空工具
                msg = self._pref_ack(pref_delta)
                metrics.intent = "memory"
                yield from self._trace(turn, StepType.INTENT, "记忆偏好", {"reason": "仅写入记忆"})
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                yield from self._emit_text(msg)
                yield from self._commit_turn(sess, turn, metrics, "ok", msg)
                self.store.save(sess)
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

        if direct is not None:
            route = direct
            metrics.intent = route.intent.value
            metrics.tools = [c.name for c in route.tool_calls]
            if any(c.name.startswith("maps.") for c in route.tool_calls):
                fast_tag = "nearby"
            elif any(c.name.startswith("navigation.") for c in route.tool_calls):
                fast_tag = "combo" if len(route.tool_calls) > 1 else "nav"
            elif route.reason == "记忆偏好并应用":
                fast_tag = "memory"
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
            if route.tool_calls:
                yield from self._handle_tools(sess, q, route, llm, memory_hint, metrics, turn, active_seat=seat)
            else:
                msg = self._pref_ack(pref_delta)
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                yield from self._emit_text(msg)
                yield from self._commit_turn(sess, turn, metrics, "ok", msg)
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
            self.store.save(sess)
            return metrics

        yield from self._emit_text(f"> **[{_ts()}] StructuredNLU（语义规划）...**\n>\n")
        yield StreamEvent("status", "规划中...")
        nlu = StructuredNLU(llm, self.registry)
        route = nlu.plan(q, sess.gateway.snapshot(), memory_hint, active_seat=seat)
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
            },
        )
        yield from self._emit_text(
            f"> **[{_ts()}] 意图**: `{route.intent.value}` "
            f"(置信度 {route.confidence:.2f}) · {route.reason}\n\n---\n\n"
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
            self.store.save(sess)
            return metrics

        if route.intent == IntentType.SEARCH:
            yield from self._handle_search(sess, q, llm, metrics, bundle, turn, active_seat=seat)
            self._post_turn_memory(sess, llm, q, metrics, turn)
            self.store.save(sess)
            return metrics

        if route.intent == IntentType.KNOWLEDGE:
            yield from self._handle_knowledge(sess, q, llm, metrics, turn)
            self._post_turn_memory(sess, llm, q, metrics, turn)
            self.store.save(sess)
            return metrics

        yield from self._handle_chat(sess, q, llm, metrics, bundle, turn)
        self._post_turn_memory(sess, llm, q, metrics, turn)
        self.store.save(sess)
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
            answer_preview=answer,
            tool_names=list(metrics.tools),
        )
        sess.traces.append_turn(turn)
        yield StreamEvent("turn", turn.summary())

    def _post_turn_memory(
        self,
        sess: SessionData,
        llm: LLMClient,
        query: str,
        metrics: TurnMetrics,
        turn: Optional[TurnTrace] = None,
    ):
        if not config.AGENT_ENABLE_AUTO_MEMORY:
            return
        msgs = sess.transcript.load()
        assistant = ""
        for m in reversed(msgs):
            if m.role == MessageRole.ASSISTANT:
                assistant = m.content
                break
        note = sess.memory.maybe_extract(llm, query, assistant)
        if note:
            metrics.llm_calls += 1
            if turn is not None:
                turn.add(StepType.MEMORY, "写入 Auto Memory", {"note": note})
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
                    yield from self._emit_text(f"> {ev.data}\n")
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
            yield from self._commit_turn(sess, turn, metrics, "error", "工具循环异常结束")
            yield from self._emit_text("工具循环异常结束。")
            yield StreamEvent(
                "final",
                {"turn_id": turn.turn_id, "cite_pages": [], "related_images": [], "state": self._state_summary(sess)},
            )
            return

        metrics.llm_calls += loop_result.llm_calls
        metrics.loop_iters = loop_result.iterations
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
        evidence_cards = [*poi_cards, *message_cards]
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

        msg_raw = self._format_tool_results(results)
        detail = "；".join(
            f"{r.message} (`{c.name}` {json.dumps(c.arguments, ensure_ascii=False)})"
            for c, r in pairs
        )
        msg = self._warm_tool_reply(llm, query, msg_raw, results=results)
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

    def _pref_ack(self, delta) -> str:
        bits = []
        if getattr(delta, "preferred_seat", None):
            bits.append(f"以后默认按{SEAT_CN.get(delta.preferred_seat, delta.preferred_seat)}来")
        for z, t in (getattr(delta, "climate_temps", None) or {}).items():
            bits.append(f"{SEAT_CN.get(z, z)}温度记成 {float(t):.0f}°C")
        if not bits:
            bits.append("偏好已记下来")
        return "好，" + "，".join(bits) + "。换个话题再说空调，我也会按这个来。"

    def _format_tool_results(self, results: List[ToolResult]) -> str:
        parts = []
        for r in results:
            parts.append(r.message if r.success else f"失败：{r.message}")
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
        return out

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

    def _warm_tool_reply(
        self,
        llm: LLMClient,
        query: str,
        tool_msg: str,
        results: Optional[List[ToolResult]] = None,
    ) -> str:
        """把工具结果转成温暖口语；对话框只留口语，绝不回吐工具原文/名单。"""
        if results:
            map_fail = [
                r
                for r in results
                if (r.tool or "").startswith("maps.") and not r.success
            ]
            if map_fail:
                return self._strip_oral_reply(
                    "；".join(r.message for r in map_fail) or "地图这会儿连不上。"
                )
            spoken = self._messages_spoken_summary(results)
            if spoken:
                return self._strip_oral_reply(spoken)
            nearby = self._nearby_wrap_payload(query, results)
            if nearby:
                try:
                    text = llm.chat(
                        TOOL_WRAP_STYLE,
                        f"用户原话：{query}\n可供口述的材料（禁止照抄成名单）：\n{nearby}",
                        temperature=0.35,
                    )
                    text = self._strip_oral_reply((text or "").strip())
                    if text and "【听】" not in text:
                        text = f"【听】{text}"
                    return text or self._nearby_spoken_fallback(query, results)
                except Exception:
                    return self._nearby_spoken_fallback(query, results)
            clarify_spoken = self._nav_clarify_spoken(results)
            if clarify_spoken:
                return self._strip_oral_reply(f"【听】{clarify_spoken}")
            if all(not r.success for r in results):
                return self._strip_oral_reply(tool_msg)
        try:
            text = llm.chat(
                TOOL_WRAP_STYLE,
                f"用户原话：{query}\n工具结果摘要（禁止照抄后台原文，禁止 markdown）：\n{tool_msg}",
                temperature=0.35,
            )
            text = self._strip_oral_reply((text or "").strip())
            if text and "【听】" not in text:
                text = f"【听】{text}"
            return text or "【听】好，我这边处理好了。"
        except Exception:
            return "【听】好，我这边处理好了。"

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
        try:
            for token in llm.chat_stream(system, user, temperature=0.45):
                full.append(token)
                yield StreamEvent("token", token)
            metrics.llm_calls += 1
            ans = "".join(full).strip() or "这一块我暂时没读到，你再问具体一点我帮你看。"
        except Exception as e:
            if full:
                ans = "".join(full).strip()
            else:
                ans = f"状态我这边刚看岔了：{e}。你稍后再试一次好不好？"
                yield from self._emit_text(ans)
        sess.transcript.append(MessageRole.ASSISTANT, ans)
        yield from self._trace(turn, StepType.RESPONSE, "状态回答", {"answer": ans[:200]})
        yield from self._commit_turn(sess, turn, metrics, "ok", ans)
        yield StreamEvent(
            "final",
            {"turn_id": turn.turn_id, "cite_pages": [], "related_images": [], "state": self._state_summary(sess)},
        )

    def _handle_knowledge(
        self, sess: SessionData, query: str, llm: LLMClient, metrics: TurnMetrics, turn: TurnTrace
    ):
        yield StreamEvent("status", "检索手册知识库...")
        yield from self._trace(turn, StepType.KNOWLEDGE, "检索手册")
        yield from self._emit_text(f"> **[{_ts()}] 知识查询，检索中...**\n>\n")
        rag = self._get_rag()
        try:
            docs = rag.retrieve(query)
        except Exception as e:
            msg = f"知识库暂时不可用：{e}"
            sess.transcript.append(MessageRole.ASSISTANT, msg)
            yield from self._commit_turn(sess, turn, metrics, "error", msg)
            yield from self._emit_text(msg)
            yield StreamEvent(
                "final",
                {"turn_id": turn.turn_id, "cite_pages": [], "related_images": [], "state": self._state_summary(sess)},
            )
            return
        if not docs:
            msg = KNOWLEDGE_EMPTY
            sess.transcript.append(MessageRole.ASSISTANT, msg)
            yield from self._commit_turn(sess, turn, metrics, "ok", msg)
            yield from self._emit_text(msg)
            yield StreamEvent(
                "final",
                {"turn_id": turn.turn_id, "cite_pages": [], "related_images": [], "state": self._state_summary(sess)},
            )
            return

        yield from self._emit_text(f"> **[{_ts()}] 检索到{len(docs)}篇文档，生成回答中...**\n\n---\n\n")
        yield from self._trace(turn, StepType.KNOWLEDGE, f"命中 {len(docs)} 篇文档", {"doc_count": len(docs)})
        context_str, context_cards = rag.build_context_cards(docs)
        yield StreamEvent("context", context_cards)
        system = KNOWLEDGE_STYLE
        user = (
            f"用户问题: {query}\n\n参考文档:\n{context_str}\n\n"
            "请严格按系统要求的结构作答：先结论，再编号步骤，必要时一小提示。"
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
        except Exception:
            answer = llm.chat(system, user, temperature=0.35)
            metrics.llm_calls += 1
            yield from self._emit_text(answer)

        sess.transcript.append(MessageRole.ASSISTANT, answer)
        post = rag.post_process(answer, docs)
        yield from self._trace(turn, StepType.RESPONSE, "知识回答", {"answer": answer[:200]})
        yield from self._commit_turn(sess, turn, metrics, "ok", answer)
        yield StreamEvent(
            "final",
            {
                "turn_id": turn.turn_id,
                "cite_pages": post.get("cite_pages", []),
                "related_images": post.get("related_images", []),
                "contexts": context_cards,
                "state": self._state_summary(sess),
                "metrics": _metrics_dict(metrics),
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

        yield StreamEvent("status", "思考中...")
        yield from self._trace(turn, StepType.CHAT, "闲聊路径")
        yield from self._emit_text(f"> **[{_ts()}] 闲聊（带上下文）...**\n\n---\n\n")
        if bundle.recent_dialog:
            yield from self._emit_text("> [Transcript] 已注入最近对话\n\n")
        st = sess.gateway.snapshot()
        nav = st.get("navigation") or {}
        pos = nav.get("position") or {}
        conn = st.get("connectivity") or {}
        note = st.get("notifications") or {}
        wifi = conn.get("wifi") or {}
        cell = conn.get("cellular") or {}
        msgs = [m for m in (note.get("messages") or []) if isinstance(m, dict)]
        unread_n = sum(1 for m in msgs if not m.get("read"))
        loc_hint = ""
        if pos.get("lng") is not None and pos.get("lat") is not None:
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
                    "用户问位置时可顺带提剩余里程；若问附近地点，建议直接问「附近有什么美食/充电站」。"
                )
            else:
                loc_hint = (
                    f"\n当前车辆定位：{place}；导航未开启（navigating=false）。"
                    "用户问「在哪里」时只报当前位置路名，禁止说剩余公里、ETA、路况、目的地，"
                    "也禁止说「正往某某开/导航显示…」；后台道路巡航不是导航。"
                    "若问起附近地点，应建议他直接问「附近有什么美食/充电站」，你会调用地图能力。"
                )
        sys_hint = (
            f"\n车机连接与通知（已同步）：Wi‑Fi={'开·'+str(wifi.get('ssid') or '热点') if wifi.get('on') else '关'}；"
            f"蜂窝={cell.get('carrier') or ''}{cell.get('type') or ''}；"
            f"未读消息 {unread_n} 条；"
            f"电话={note.get('phone_status') or '空闲'}。"
            "消息无需授权：仪表盘可直接点开查看。"
            "用户要你读消息时，调用 notifications.list_messages（会先隐私确认）；"
            "确认后口头只摘要未读与紧急项，完整正文在依据面板；不要编造正文。"
        )
        system = CHAT_STYLE + "\n\n" + bundle.user_context + loc_hint + sys_hint
        user = f"最近对话:\n{bundle.recent_dialog}\n\n用户: {query}"
        try:
            full = []
            for token in llm.chat_stream(system, user, temperature=0.8):
                full.append(token)
                yield StreamEvent("token", token)
            metrics.llm_calls += 1
            answer = "".join(full)
        except Exception:
            answer = CHAT_FALLBACK
            yield from self._emit_text(answer)
        sess.transcript.append(MessageRole.ASSISTANT, answer)
        yield from self._trace(turn, StepType.RESPONSE, "闲聊回答", {"answer": answer[:200]})
        yield from self._commit_turn(sess, turn, metrics, "ok", answer)
        yield StreamEvent(
            "final",
            {"turn_id": turn.turn_id, "cite_pages": [], "related_images": [], "state": self._state_summary(sess)},
        )

    def _state_summary(self, sess: SessionData) -> Dict[str, Any]:
        st = sess.gateway.snapshot()
        climate = st.get("climate", {})
        seat = normalize_active_seat(sess.slots.get("active_seat"))
        zone = (climate.get("zones") or {}).get(seat) or (climate.get("zones") or {}).get("front_left") or {}
        media = st.get("media", {})
        prefs = sess.memory.load_preferences()
        return {
            "climate_power": climate.get("power"),
            "temp": zone.get("temp"),
            "fan": zone.get("fan"),
            "active_seat": seat,
            "active_seat_cn": SEAT_CN.get(seat, seat),
            "preferences": {
                "preferred_seat": prefs.get("preferred_seat"),
                "climate_temp_c": prefs.get("climate_temp_c"),
            },
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
        if text:
            yield StreamEvent("token", text)


_ORCH: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    global _ORCH
    if _ORCH is None:
        _ORCH = Orchestrator()
    return _ORCH
