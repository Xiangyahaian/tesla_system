import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  compactAgent,
  fetchAgentHistory,
  fetchAgentTurn,
  type AgentTurnMetrics,
  type AgentTurnSummary,
} from "@/lib/api";
import { useCabinStore } from "@/store/cabinStore";
import { TopBar } from "@/components/layout/TopBar";
import { PromptCalls } from "@/components/agent/PromptCalls";
import { TurnRail } from "@/components/agent/TurnRail";
import type { TraceStep } from "@/lib/types";
import { intentLabel, statusLabel, toShowcaseSteps, formatElapsed } from "@/lib/trace";

function formatTime(ts?: number) {
  if (!ts) return "";
  const d = new Date(ts * (ts < 1e12 ? 1000 : 1));
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function readMetrics(raw: unknown): AgentTurnMetrics {
  if (!raw || typeof raw !== "object") return {};
  return raw as AgentTurnMetrics;
}

function tokenSourceLabel(src?: string) {
  if (src === "api") return "接口返回";
  if (src === "estimate") return "估算（接口未给 usage）";
  if (src === "mixed") return "混合（部分接口返回、部分估算）";
  return "";
}

function turnListHint(t: AgentTurnSummary) {
  const m = t.metrics || {};
  const elapsed = formatElapsed(t.duration_ms);
  if (typeof m.llm_used === "boolean") {
    if (!m.llm_used) return elapsed ? `未调模型 · ${elapsed}` : "未调模型";
    const tok = Number(m.total_tokens || 0);
    const bits = [tok ? `${tok} token` : "", elapsed].filter(Boolean);
    return bits.length ? bits.join(" · ") : null;
  }
  return t.tool_names?.length ? `${t.tool_names.length} 个工具` : elapsed || null;
}

export function AgentPage() {
  const loc = useLocation();
  const sessionId = useCabinStore((s) => s.sessionId);
  const model = useCabinStore((s) => s.model);
  const [turns, setTurns] = useState<AgentTurnSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      setErr(null);
      const h = await fetchAgentHistory(sessionId, 50);
      setTurns(h.turns || []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (loc.pathname !== "/agent") return;
    void reload();
  }, [loc.pathname, reload]);

  const openTurn = async (turn: AgentTurnSummary) => {
    const id = String(turn.turn_id || turn.id || "");
    if (!id) return;
    setSelectedId(id);
    setRawOpen(false);
    try {
      const detail = await fetchAgentTurn(id, sessionId);
      setSelected(detail);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "打开 turn 失败");
    }
  };

  const onCompact = async () => {
    setBusy(true);
    try {
      await compactAgent(sessionId, model);
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "压缩失败");
    } finally {
      setBusy(false);
    }
  };

  const steps = useMemo(() => {
    const raw = (selected?.steps || selected?.trace || []) as TraceStep[];
    return Array.isArray(raw) ? raw : [];
  }, [selected]);

  const showcase = useMemo(() => toShowcaseSteps(steps), [steps]);
  const query = String(selected?.query || selected?.user_query || "");
  const intent = String(selected?.intent || "");
  const status = String(selected?.status || "");
  const answer = String(selected?.answer_preview || "");
  const metrics = useMemo(() => readMetrics(selected?.metrics), [selected]);
  const prompts = Array.isArray(metrics.prompts) ? metrics.prompts : [];
  const recorded = typeof metrics.llm_used === "boolean";
  const endedAt = Number(selected?.ended_at) || undefined;
  const startedAt = Number(selected?.started_at) || undefined;
  const turnMs =
    startedAt && endedAt && endedAt >= startedAt
      ? Math.round((endedAt - startedAt) * 1000)
      : typeof selected?.duration_ms === "number"
        ? Number(selected.duration_ms)
        : undefined;
  const consumeLabel = formatElapsed(turnMs ?? metrics.llm_elapsed_ms);

  return (
    <div className="page-agent">
      <TopBar title="执行轨迹" subtitle="点开一轮，只看这一轮真实送给模型的内容、字数和 token" />
      <div className="agent-body">
        <aside className="agent-list">
          <div className="agent-list-head">
            <span>对话轮次</span>
            <div className="agent-list-actions">
              <button type="button" className="btn ghost compact" onClick={() => void reload()}>
                刷新
              </button>
              <button
                type="button"
                className="btn ghost compact"
                disabled={busy}
                onClick={() => void onCompact()}
              >
                压缩上下文
              </button>
            </div>
          </div>
          {err ? <p className="page-error">{err}</p> : null}
          <ul className="turn-list">
            {turns.map((t, i) => {
              const id = String(t.turn_id || t.id || i);
              const q = t.query || t.user_query || "—";
              const active = selectedId === id;
              const hint = turnListHint(t);
              const meta = [formatTime(t.started_at) || id.slice(0, 8), hint].filter(Boolean).join(" · ");
              return (
                <li key={id}>
                  <button
                    type="button"
                    className={`turn-card${active ? " active" : ""}`}
                    onClick={() => void openTurn(t)}
                    aria-pressed={active}
                  >
                    <div className="turn-card-top">
                      <span className="turn-card-intent">{intentLabel(t.intent)}</span>
                      <span className="turn-card-status">{statusLabel(t.status)}</span>
                    </div>
                    <div className="turn-card-q">{q}</div>
                    <div className="turn-card-meta">{meta}</div>
                  </button>
                </li>
              );
            })}
            {loading ? (
              <li className="empty-hint">正在加载轨迹…</li>
            ) : turns.length === 0 ? (
              <li className="empty-hint">尚无轨迹，先在「驾驶助手」对话一轮。</li>
            ) : null}
          </ul>
        </aside>

        <section className="agent-detail">
          {selected ? (
            <div className="turn-detail-panel">
              <header className="turn-detail-head">
                <div>
                  <p className="turn-detail-kicker">本轮对话</p>
                  <h3>{query || "（无用户问题）"}</h3>
                </div>
                <div className="turn-detail-pills">
                  <span className="trace-pill">{intentLabel(intent)}</span>
                  <span className={`trace-pill tone-${(status || "ok").toLowerCase()}`}>
                    {statusLabel(status)}
                  </span>
                </div>
              </header>

              <div className="agent-meta-grid">
                <div className="meta-tile">
                  <div className="hud-label">步骤数</div>
                  <div className="hud-value">
                    {showcase.length}
                    <small> 步</small>
                  </div>
                </div>
                <div className="meta-tile">
                  <div className="hud-label">送入模型</div>
                  <div className="hud-value">
                    {recorded ? metrics.prompt_chars ?? 0 : "—"}
                    <small> 字</small>
                  </div>
                </div>
                <div className="meta-tile">
                  <div className="hud-label">Token</div>
                  <div className="hud-value">
                    {recorded ? metrics.total_tokens ?? 0 : "—"}
                    <small>
                      {recorded && metrics.llm_used
                        ? ` 入 ${metrics.prompt_tokens ?? 0} / 出 ${metrics.completion_tokens ?? 0}`
                        : ""}
                    </small>
                  </div>
                </div>
                <div className="meta-tile">
                  <div className="hud-label">响应时间</div>
                  <div className="hud-value">
                    {consumeLabel || "—"}
                    <small> 提问到回答</small>
                  </div>
                </div>
              </div>
              {recorded && metrics.token_source && metrics.llm_used ? (
                <p className="turn-metric-note">
                  Token 来源：{tokenSourceLabel(metrics.token_source) || metrics.token_source}
                  {metrics.llm_calls ? ` · 本轮调用 ${metrics.llm_calls} 次` : ""}
                </p>
              ) : null}
              {recorded && !metrics.llm_used ? (
                <p className="turn-metric-note">
                  这一轮没有调用大模型，所以没有送入字符，也没有 token。下面不会再展示会话级的人设/记忆拼装。
                </p>
              ) : null}
              {!recorded ? (
                <p className="turn-metric-note">
                  这是改版前记下的回合：当时没有保存真正送进模型的原文和 token，这里也不再用「当前会话组装结果」冒充。
                </p>
              ) : null}

              {answer ? (
                <div className="turn-answer-card">
                  <div className="turn-answer-label">小特回复</div>
                  <p>{answer}</p>
                </div>
              ) : null}

              <div className="turn-process">
                <div className="turn-process-label">执行过程</div>
                {showcase.length > 0 ? (
                  <TurnRail steps={steps} endedAt={endedAt} />
                ) : (
                  <p className="empty-hint soft">本轮没有可展示的关键步骤。</p>
                )}
              </div>

              <PromptCalls recorded={recorded} llmUsed={metrics.llm_used} prompts={prompts} />

              <div className="turn-raw">
                <button
                  type="button"
                  className="reply-details-btn"
                  onClick={() => setRawOpen((v) => !v)}
                  aria-expanded={rawOpen}
                >
                  {rawOpen ? "收起原始数据" : "查看原始 JSON"}
                </button>
                <AnimatePresence initial={false}>
                  {rawOpen ? (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.22 }}
                    >
                      <pre className="code-block">
                        {JSON.stringify(selected, null, 2).slice(0, 8000)}
                      </pre>
                    </motion.div>
                  ) : null}
                </AnimatePresence>
              </div>
            </div>
          ) : (
            <div className="empty-panel">
              <h3>选择左侧一轮对话</h3>
              <p>右侧只展示这一轮的步骤、送入字数和 token，不再显示整段会话的总量。</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
