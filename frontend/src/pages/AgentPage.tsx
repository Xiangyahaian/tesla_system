import { useCallback, useEffect, useState } from "react";
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

export function AgentPage() {
  const sessionId = useCabinStore((s) => s.sessionId);
  const model = useCabinStore((s) => s.model);
  const agentMeta = useCabinStore((s) => s.agentMeta);
  const [turns, setTurns] = useState<AgentTurnSummary[]>([]);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
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

  const steps = (selected?.steps || selected?.trace || []) as TraceStep[];

  return (
    <div className="page-agent">
      <TopBar title="Agent" subtitle="Turn Timeline · Transcript · Compact" />
      <div className="agent-body">
        <aside className="agent-list">
          <div className="agent-list-head">
            <span>Turns</span>
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
                Compact
              </button>
            </div>
          </div>
          {err ? <p className="page-error">{err}</p> : null}
          <ul className="turn-list">
            {turns.map((t, i) => {
              const id = String(t.turn_id || t.id || i);
              const q = t.query || t.user_query || "—";
              return (
                <li key={id}>
                  <button type="button" className="turn-card" onClick={() => void openTurn(t)}>
                    <div className="turn-card-id">{id.slice(0, 10)}</div>
                    <div className="turn-card-q">{q}</div>
                    <div className="turn-card-meta">
                      {t.status || "ok"} · {t.step_count ?? t.steps?.length ?? "?"} steps
                    </div>
                  </button>
                </li>
              );
            })}
            {turns.length === 0 ? <li className="empty-hint">尚无轨迹，先在 Drive 对话一轮。</li> : null}
          </ul>
        </aside>

        <section className="agent-detail">
          <div className="agent-meta-grid">
            <div className="meta-tile">
              <div className="hud-label">Transcript</div>
              <div className="hud-value">
                {agentMeta?.transcript_messages ?? "—"}
                <small> msgs</small>
              </div>
            </div>
            <div className="meta-tile">
              <div className="hud-label">Chars</div>
              <div className="hud-value">{agentMeta?.transcript_chars ?? "—"}</div>
            </div>
            <div className="meta-tile">
              <div className="hud-label">Context</div>
              <div className="hud-value">
                {context?.total_chars ?? "—"}
                <small> chars</small>
              </div>
            </div>
          </div>

          {selected ? (
            <div className="turn-detail">
              <h3>Turn Detail</h3>
              <pre className="code-block">{JSON.stringify(selected, null, 2).slice(0, 6000)}</pre>
              {Array.isArray(steps) && steps.length > 0 ? <TurnRail steps={steps} /> : null}
            </div>
          ) : (
            <div className="empty-panel">
              <h3>选择左侧 Turn</h3>
              <p>查看完整 JSON、工具调用与状态机步骤，对应后端 `turns.jsonl`。</p>
            </div>
          )}

          {context?.user_context_preview ? (
            <div className="context-preview">
              <div className="context-title">Memory / Context Preview</div>
              <pre className="code-block soft">{context.user_context_preview}</pre>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
