import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AgentTurnSummary,
  compactAgent,
  fetchAgentContext,
  fetchAgentHistory,
  fetchAgentTurn,
} from "@/lib/api";
import { useCabinStore } from "@/store/cabinStore";
import { TopBar } from "@/components/layout/TopBar";
import { TurnRail } from "@/components/agent/TurnRail";
import type { TraceStep } from "@/lib/types";
import { intentLabel, statusLabel, toShowcaseSteps } from "@/lib/trace";

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

export function AgentPage() {
  const sessionId = useCabinStore((s) => s.sessionId);
  const model = useCabinStore((s) => s.model);
  const agentMeta = useCabinStore((s) => s.agentMeta);
  const [turns, setTurns] = useState<AgentTurnSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const [context, setContext] = useState<{
    sources: string[];
    total_chars: number;
    recent_dialog: string;
    user_context_preview: string;
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      setErr(null);
      const [h, c] = await Promise.all([
        fetchAgentHistory(sessionId, 50),
        fetchAgentContext(sessionId),
      ]);
      setTurns(h.turns || []);
      setContext(c);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    }
  }, [sessionId]);

  useEffect(() => {
    void reload();
  }, [reload]);

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

  return (
    <div className="page-agent">
      <TopBar title="执行轨迹" subtitle="按回合查看意图、工具与回复，一眼看清 Agent 做了什么" />
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
              const meta = [
                formatTime(t.started_at) || id.slice(0, 8),
                t.tool_names?.length ? `${t.tool_names.length} 个工具` : null,
              ]
                .filter(Boolean)
                .join(" · ");
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
            {turns.length === 0 ? (
              <li className="empty-hint">尚无轨迹，先在「驾驶助手」对话一轮。</li>
            ) : null}
          </ul>
        </aside>

        <section className="agent-detail">
          <div className="agent-meta-grid">
            <div className="meta-tile">
              <div className="hud-label">对话条数</div>
              <div className="hud-value">
                {agentMeta?.transcript_messages ?? "—"}
                <small> 条</small>
              </div>
            </div>
            <div className="meta-tile">
              <div className="hud-label">字符数</div>
              <div className="hud-value">{agentMeta?.transcript_chars ?? "—"}</div>
            </div>
            <div className="meta-tile">
              <div className="hud-label">上下文</div>
              <div className="hud-value">
                {context?.total_chars ?? "—"}
                <small> 字</small>
              </div>
            </div>
          </div>

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
                  <span className="trace-pill mute">{showcase.length} 步</span>
                </div>
              </header>

              {answer ? (
                <div className="turn-answer-card">
                  <div className="turn-answer-label">小特回复</div>
                  <p>{answer}</p>
                </div>
              ) : null}

              <div className="turn-process">
                <div className="turn-process-label">执行过程</div>
                {showcase.length > 0 ? (
                  <TurnRail steps={steps} />
                ) : (
                  <p className="empty-hint soft">本轮没有可展示的关键步骤。</p>
                )}
              </div>

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
              <p>右侧会按「意图 → 工具/检索 → 回复」展示可读的执行过程。</p>
            </div>
          )}

          {context?.user_context_preview ? (
            <div className="context-preview">
              <div className="context-title">当前上下文预览</div>
              <pre className="code-block soft">{context.user_context_preview}</pre>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
