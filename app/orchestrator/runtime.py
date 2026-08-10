# -*- coding: utf-8 -*-
"""编排：Claude Code 风格 Agent Harness + 车载专用路径。

每轮：
  1) 写入 user transcript
  2) 分层 compact（如需要）
  3) assemble context（CABIN.md / MEMORY / vehicle / recent）
  4) NLU 规划
  5) tool → AgentLoop（gather/act/verify）；其它路径专用 handler
  6) 写入 assistant/tool transcript + 持久化 session
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

from app import config
from app.agent.hooks import HookBus
from app.agent.loop import AgentLoop
from app.agent.trace import StepType, TurnTrace
from app.agent.types import MessageRole
from app.llm.client import LLMClient, get_llm
from app.models import IntentType, PendingAction, RouteResult, ToolCall, ToolResult
from app.nlu.fast_path import try_confirm_utterance
from app.nlu.planner import StructuredNLU
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
    ) -> Generator[StreamEvent, None, TurnMetrics]:
        metrics = TurnMetrics()
        sess = self.store.get(session_id)
        llm = get_llm(model)
        q = (query or "").strip()
        turn = TurnTrace(session_id=session_id, query=q, model=model)
        metrics.turn_id = turn.turn_id

        yield StreamEvent("status", "Agent 上下文准备中...")
        yield from self._trace(
            turn,
            StepType.SESSION,
            "加载会话",
            {"session_id": session_id, "turn_id": turn.turn_id},
        )
        yield from self._emit_text(
            f"> **[{_ts()}] Agent Harness** · turn `{turn.turn_id}` · session `{session_id}`\n>\n"
        )

        # 0) pending confirmation
        if sess.pending is not None:
            confirm_route = try_confirm_utterance(q)
            do_confirm = confirm is True or (confirm_route and confirm_route.intent == IntentType.CONFIRM)
            do_cancel = confirm is False or (confirm_route and confirm_route.intent == IntentType.CANCEL)
            if do_confirm:
                pending = sess.pending
                sess.pending = None
                sess.transcript.append(MessageRole.USER, q, kind="confirm")
                yield from self._trace(turn, StepType.CONFIRM, "用户确认高风险操作", {"summary": pending.summary})
                yield from self._emit_text(
                    f"> **[{_ts()}] 用户已确认高风险操作**\n>\n"
                    f"> 待执行: `{pending.summary}`\n\n---\n\n"
                )
                results = self._exec_tools(sess, pending.tool_calls)
                for call, result in zip(pending.tool_calls, results):
                    sess.transcript.append(
                        MessageRole.TOOL,
                        result.message,
                        tool=call.name,
                        success=result.success,
                    )
                    yield from self._trace(
                        turn,
                        StepType.TOOL,
                        f"执行 {call.name}",
                        {"arguments": call.arguments, "result": result.message, "success": result.success},
                        status="ok" if result.success else "error",
                    )
                    yield from self._emit_text(f"> `{call.name}` → {result.message}\n")
                msg = self._format_tool_results(results)
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
                        "state": self._state_summary(sess),
                    },
                )
                return metrics
            if do_cancel:
                sess.pending = None
                sess.transcript.append(MessageRole.USER, q, kind="cancel")
                msg = "好的，已取消操作。"
                sess.transcript.append(MessageRole.ASSISTANT, msg)
                yield from self._trace(turn, StepType.CONFIRM, "用户取消操作")
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

        # 4) NLU
        yield from self._emit_text(f"> **[{_ts()}] StructuredNLU（语义规划）...**\n>\n")
        yield StreamEvent("status", "规划中...")
        memory_hint = self.store.assembler.memory_hint(bundle, sess.transcript)
        nlu = StructuredNLU(llm, self.registry)
        route = nlu.plan(q, sess.gateway.snapshot(), memory_hint)
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
                "tool_calls": [c.model_dump() for c in route.tool_calls],
                "context_sources": bundle.sources,
                "compact_layers": metrics.compact_layers,
            },
        )

        if route.intent in {IntentType.TOOL, IntentType.MULTI_TOOL}:
            yield from self._handle_tools(sess, q, route, llm, memory_hint, metrics, turn)
            self.store.save(sess)
            return metrics

        if route.intent == IntentType.SEARCH:
            yield from self._handle_search(sess, q, llm, metrics, bundle, turn)
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
    ):
        yield from self._emit_text(f"> **[{_ts()}] Agent Loop（gather→act→verify）...**\n\n---\n\n")
        yield from self._trace(turn, StepType.LOOP, "进入 Agent Loop")

        def _exec(call: ToolCall) -> ToolResult:
            block = self.hooks.run_pre(call, sess.gateway.snapshot())
            if block:
                return ToolResult(success=False, message=block, tool=call.name)
            result = self.registry.execute(sess.gateway, call)
            self.hooks.run_post(call, result, sess.gateway.snapshot())
            return result

        gen = self.agent_loop.run_tools(
            query=query,
            llm=llm,
            gateway=sess.gateway,
            vehicle_state=sess.gateway.snapshot(),
            memory_hint=memory_hint,
            initial_route=route,
            execute=_exec,
            on_persist_pending=lambda p: setattr(sess, "pending", p),
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
                    msg = data.get("message") or "请确认高风险操作"
                    summary = data.get("summary")
                    yield StreamEvent("confirm", data)
                    text = (
                        f"> **[{_ts()}] 等待确认**\n>\n> 待执行: `{summary}`\n\n---\n\n"
                        f"{msg}\n\n请回复「确认」或「取消」。"
                    )
                    sess.transcript.append(MessageRole.ASSISTANT, text)
                    yield from self._trace(turn, StepType.CONFIRM, "等待用户确认", data, status="warn")
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
            metrics.tools = [c.name for c in loop_result.route.tool_calls]
            metrics.intent = loop_result.route.intent.value

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
        calls = (loop_result.route.tool_calls if loop_result.route else [])[: len(results)]
        for call, result in zip(calls, results):
            sess.transcript.append(
                MessageRole.TOOL,
                result.message,
                tool=call.name,
                arguments=call.arguments,
                success=result.success,
            )
            yield from self._trace(
                turn,
                StepType.TOOL,
                f"{call.name}",
                {"arguments": call.arguments, "result": result.message, "success": result.success},
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

        msg = self._format_tool_results(results)
        detail = "；".join(
            f"{r.message} (`{c.name}` {json.dumps(c.arguments, ensure_ascii=False)})"
            for c, r in zip(calls, results)
        )
        sess.transcript.append(MessageRole.ASSISTANT, detail or msg)
        yield from self._trace(turn, StepType.RESPONSE, "工具执行完成", {"answer": detail or msg})
        yield from self._commit_turn(sess, turn, metrics, "ok", detail or msg)
        yield from self._emit_text("\n---\n\n" + (detail or msg))

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

    def _format_tool_results(self, results: List[ToolResult]) -> str:
        parts = []
        for r in results:
            parts.append(r.message if r.success else f"失败：{r.message}")
        return "；".join(parts) if parts else "已处理完成。"

    def _handle_search(
        self, sess: SessionData, query: str, llm: LLMClient, metrics: TurnMetrics, bundle, turn: TurnTrace
    ):
        yield StreamEvent("status", "查询车辆状态...")
        yield from self._trace(turn, StepType.SEARCH, "读取车辆状态")
        yield from self._emit_text(f"> **[{_ts()}] SEARCH: 读取车辆状态...**\n\n---\n\n")
        state = sess.gateway.snapshot()
        system = (
            bundle.system
            + "\n你当前任务是根据车辆 JSON 状态回答，简洁1-3句，不要编造。"
            + "\n\n"
            + bundle.user_context
        )
        user = f"最近对话:\n{bundle.recent_dialog}\n\n完整状态JSON:\n{json.dumps(state, ensure_ascii=False)}\n\n用户问: {query}"
        full: List[str] = []
        try:
            for token in llm.chat_stream(system, user, temperature=0.2):
                full.append(token)
                yield StreamEvent("token", token)
            metrics.llm_calls += 1
            ans = "".join(full).strip() or "暂时读不到相关状态。"
        except Exception as e:
            if full:
                ans = "".join(full).strip()
            else:
                ans = f"状态查询失败: {e}"
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
            msg = "手册里没找到足够相关的内容，换个问法试试？"
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
        context_str, context_list = rag.build_context(docs)
        yield StreamEvent("context", context_list)
        system = (
            "你是 Tesla 车载知识助手小特。基于参考文档回答，简洁1-2句，"
            "末尾用中文方括号标注引用如【1】或【1, 2】，不要 emoji。"
        )
        user = f"用户问题: {query}\n\n参考文档:\n{context_str}\n\n请基于参考文档回答。"
        try:
            full = []
            for token in llm.chat_stream(system, user, temperature=0.3):
                full.append(token)
                yield StreamEvent("token", token)
            metrics.llm_calls += 1
            answer = "".join(full)
        except Exception:
            answer = llm.chat(system, user, temperature=0.3)
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
                "state": self._state_summary(sess),
                "metrics": _metrics_dict(metrics),
            },
        )

    def _handle_chat(
        self, sess: SessionData, query: str, llm: LLMClient, metrics: TurnMetrics, bundle, turn: TurnTrace
    ):
        yield StreamEvent("status", "思考中...")
        yield from self._trace(turn, StepType.CHAT, "闲聊路径")
        yield from self._emit_text(f"> **[{_ts()}] 闲聊（带上下文）...**\n\n---\n\n")
        if bundle.recent_dialog:
            yield from self._emit_text("> [Transcript] 已注入最近对话\n\n")
        system = (
            "你是车载助手「小特」。闲聊时像正常朋友聊天：口语、自然、可轻松可俏皮。"
            "直接回答用户问题（吃什么、聊天气、开玩笑都可以），1–3 句即可。"
            "硬性规则：你不能真正控车；禁止说「已打开/已关闭」等假装执行成功。"
            "若用户像在下控车指令但对象不清，可简短追问对象；不要编造执行结果。"
            "除非用户明确问行车安全或明显危险操作，否则不要提「专注驾驶」「先停车再…」「注意安全」。"
            "\n\n"
            + bundle.user_context
        )
        user = f"最近对话:\n{bundle.recent_dialog}\n\n用户: {query}"
        try:
            full = []
            for token in llm.chat_stream(system, user, temperature=0.7):
                full.append(token)
                yield StreamEvent("token", token)
            metrics.llm_calls += 1
            answer = "".join(full)
        except Exception:
            answer = "我在呢，想聊天、查手册还是控制车？说一声就行。"
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
        fl = climate.get("zones", {}).get("front_left", {})
        media = st.get("media", {})
        return {
            "climate_power": climate.get("power"),
            "temp": fl.get("temp"),
            "fan": fl.get("fan"),
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
