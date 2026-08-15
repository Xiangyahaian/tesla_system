import { useCallback, useEffect, useState } from "react";
import {
  createSession,
  deleteSession,
  fetchSessions,
  purgeAllSessions,
  renameSession,
  type SessionSummary,
} from "@/lib/api";
import { useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";

function fmtTime(ts?: number) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function SessionManagerPanel({ compact = false }: { compact?: boolean }) {
  const sessionId = useCabinStore((s) => s.sessionId);
  const sessionTitle = useCabinStore((s) => s.sessionTitle);
  const clearUser = useCabinStore((s) => s.clearUser);
  const { switchSession, doReset } = useCabinRuntime();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  const reload = useCallback(async () => {
    try {
      const data = await fetchSessions();
      setSessions(data.sessions || []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载会话失败");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, sessionId]);

  const onCreate = async () => {
    setBusy(true);
    try {
      const res = await createSession();
      setSessions(res.sessions || []);
      await switchSession(res.session_id, res.title);
    } catch (e) {
      setError(e instanceof Error ? e.message : "新建失败");
    } finally {
      setBusy(false);
    }
  };

  const onRename = async (id: string) => {
    const title = editTitle.trim();
    if (!title) return;
    setBusy(true);
    try {
      const res = await renameSession(id, title);
      setSessions(res.sessions || []);
      if (id === sessionId) useCabinStore.getState().setSessionTitle(title);
      setEditingId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (id: string) => {
    if (id === "default") return;
    if (!window.confirm(`确定删除会话「${id}」？对话与轨迹将一并清除。`)) return;
    setBusy(true);
    try {
      const res = await deleteSession(id);
      setSessions(res.sessions || []);
      if (id === sessionId) {
        await switchSession("default", "默认会话");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  };

  const onPurgeAll = async () => {
    if (
      !window.confirm(
        "确定清空全部用户会话与昵称？仅保留重置后的默认会话，此操作不可恢复。",
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      const res = await purgeAllSessions();
      setSessions(res.sessions || []);
      clearUser();
    } catch (e) {
      setError(e instanceof Error ? e.message : "清空失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`session-manager${compact ? " compact" : ""}`}>
      <div className="session-manager-head">
        <div>
          <strong>会话管理</strong>
          <p>当前：{sessionTitle || sessionId}</p>
        </div>
        <div className="session-manager-actions">
          <button type="button" className="btn ghost compact" disabled={busy} onClick={() => void onCreate()}>
            新建会话
          </button>
          <button type="button" className="btn ghost compact" disabled={busy} onClick={() => void doReset()}>
            重置当前
          </button>
          <button
            type="button"
            className="btn ghost compact danger"
            disabled={busy}
            onClick={() => void onPurgeAll()}
          >
            清空全部
          </button>
        </div>
      </div>
      {error ? <div className="inline-error">{error}</div> : null}
      <div className="session-list">
        {sessions.map((s) => {
          const active = s.session_id === sessionId;
          const editing = editingId === s.session_id;
          return (
            <div key={s.session_id} className={`session-row${active ? " active" : ""}`}>
              <button
                type="button"
                className="session-main"
                disabled={busy || active}
                onClick={() => void switchSession(s.session_id, s.title)}
              >
                <span className="session-title">{s.title || s.session_id}</span>
                <span className="session-meta">
                  {s.message_count ?? 0} 条 · {s.turn_count ?? 0} 轮 · {fmtTime(s.updated_at)}
                </span>
                {s.preview ? <span className="session-preview">{s.preview}</span> : null}
              </button>
              <div className="session-row-actions">
                {editing ? (
                  <>
                    <input
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="session-rename-input"
                      maxLength={80}
                      aria-label="会话标题"
                    />
                    <button type="button" className="btn primary compact" onClick={() => void onRename(s.session_id)}>
                      保存
                    </button>
                    <button type="button" className="btn ghost compact" onClick={() => setEditingId(null)}>
                      取消
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="btn ghost compact"
                      onClick={() => {
                        setEditingId(s.session_id);
                        setEditTitle(s.title || "");
                      }}
                    >
                      重命名
                    </button>
                    {s.session_id !== "default" ? (
                      <button
                        type="button"
                        className="btn ghost compact danger"
                        onClick={() => void onDelete(s.session_id)}
                      >
                        删除
                      </button>
                    ) : null}
                  </>
                )}
              </div>
            </div>
          );
        })}
        {!sessions.length ? <div className="session-empty">暂无会话</div> : null}
      </div>
    </div>
  );
}
